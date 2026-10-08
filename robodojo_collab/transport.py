"""Local or SSH mailbox transport. No secrets or model client on simulator hosts."""
from __future__ import annotations
import hashlib, json, os, re, shlex, subprocess
from pathlib import Path


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}', value):
        raise ValueError('Invalid run identifier')
    return value


def atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    tmp = path.with_name(path.name + '.tmp-' + str(os.getpid()))
    with tmp.open('wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp, path)


def mailbox_operation(root, op, run_id, value=None):
    root = Path(root).resolve(); run = root / safe_id(run_id)
    if run.is_symlink() or not run.is_dir(): raise ValueError('Unknown run or symlink')
    mailbox = run / 'mailbox'
    if op == 'owner-acquire':
        owner=run/'controller-owner.json'
        identity=value['controller_id']
        if not re.fullmatch(r'[0-9a-f]{64}',identity):raise ValueError('Controller identity malformed')
        native=json.loads((run/'native.json').read_text())
        if value['package_sha256']!=native['package_sha256']:raise ValueError('Controller package differs from native scene')
        if owner.exists():
            if json.loads(owner.read_text())!=value:raise ValueError('Native scene is already owned by another controller state; reconcile before migration')
        else:
            tmp=run/('controller-owner-'+str(os.getpid())+'.tmp');atomic(tmp,value)
            try:os.link(tmp,owner)
            except FileExistsError:
                if json.loads(owner.read_text())!=value:raise ValueError('Native controller ownership conflict')
            finally:tmp.unlink(missing_ok=True)
        return {'owned':True}
    if op == 'status':
        p = run / 'native.json'; data = json.loads(p.read_text()) if p.exists() else {'status':'unknown'}
        data['pending'] = json.loads((mailbox/'pending.json').read_text()) if (mailbox/'pending.json').exists() else None
        native = Path(data['native_dir']) if data.get('native_dir') else None
        data['native_result_exists'] = bool(native and (native/'_result.json').exists())
        identities={}
        for kind in ('server','simulator'):
            pid=data.get(kind+'_pid');command=data.get(kind+'_command');file=Path('/proc')/str(pid)/'cmdline'
            identities[kind]=bool(file.is_file() and file.read_bytes().rstrip(b'\0').decode().split('\0')==command)
        data['owned_processes_alive']=identities
        return data
    if op == 'archive-manifest':
        status=mailbox_operation(root,'status',run_id)
        if not status.get('native_result_exists'):raise ValueError('Native result missing')
        native=Path(status['native_dir'])
        result=json.loads((native/'_result.json').read_text())
        events=native/'audit/events.jsonl'
        if not events.is_file() or not any(json.loads(line).get('kind')=='episode_complete' for line in events.read_text().splitlines()):
            raise ValueError('Native episode_complete missing')
        rows=[]
        for label,folder in [('native',native),('run',run)]:
            for path in sorted(folder.rglob('*')):
                if path.is_symlink():raise ValueError('Archive symlink not permitted')
                if not path.is_file() or path.name.endswith('.tmp'):continue
                if label=='run' and path.name in ('server.log','simulator.log'):continue
                before=path.stat();h=hashlib.sha256()
                with path.open('rb') as f:
                    for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
                after=path.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Archive is still changing')
                rows.append({'path':label+'/'+path.relative_to(folder).as_posix(),'size':after.st_size,'sha256':h.hexdigest()})
        return {'run_id':run_id,'native_root':str(native),'run_root':str(run),'files':rows,'native_result_sha256':hashlib.sha256((native/'_result.json').read_bytes()).hexdigest()}
    if op == 'next':
        if not (mailbox/'pending.json').exists(): return None
        pending = json.loads((mailbox/'pending.json').read_text()); index = pending['index']
        if type(index) is not int or not 0 <= index < 100: raise ValueError('Decision outside cap100')
        folder = mailbox / f'{index:04d}'
        if (folder/'response.json').exists(): return None
        raw = (folder/'request.json').read_bytes()
        if pending['run_id'] != run_id or hashlib.sha256(raw).hexdigest() != pending['request_sha256']:
            raise ValueError('Mailbox request identity/SHA mismatch')
        return dict(pending, payload=json.loads(raw))
    if op == 'deliver':
        index = value['index']; receipt = value['receipt']
        if type(index) is not int or not 0 <= index < 100: raise ValueError('Decision outside cap100')
        folder = mailbox / f'{index:04d}'; raw = (folder/'request.json').read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != receipt['request_sha256']: raise ValueError('Receipt SHA mismatch')
        dst = folder/'response.json'
        if dst.exists():
            if json.loads(dst.read_text()) != receipt: raise ValueError('Immutable receipt collision')
            return {'saved':True, 'reused':True, 'request_sha256':digest}
        pending = json.loads((mailbox/'pending.json').read_text())
        if pending != {'index':index,'request_sha256':digest,'run_id':run_id}: raise ValueError('Pending boundary changed')
        # Fully write then publish without replacement; the simulator never sees partial JSON.
        tmp=folder/('delivery-'+str(os.getpid())+'.tmp'); atomic(tmp,receipt)
        try: os.link(tmp,dst)
        except FileExistsError:
            if json.loads(dst.read_text()) != receipt: raise ValueError('Concurrent receipt collision')
        finally: tmp.unlink(missing_ok=True)
        return {'saved':True, 'reused':False, 'request_sha256':digest}
    if op == 'receipt':
        index=value['index']
        if type(index) is not int or not 0 <= index < 100:raise ValueError('Invalid index')
        path=mailbox/f'{index:04d}'/'response.json'
        return json.loads(path.read_text()) if path.exists() else None
    raise ValueError('Unknown mailbox operation')


class Mailbox:
    def __init__(self, cfg): self.cfg=cfg
    def request(self, op, run_id, value=None):
        cfg=self.cfg
        if cfg['mode']=='local': return mailbox_operation(cfg['root'],op,run_id,value)
        if cfg['mode']!='ssh': raise ValueError('Transport must be local or ssh')
        host=cfg['host']
        if host.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_.@-]+',host):raise ValueError('Unsafe SSH alias')
        # Host must already have this repository; only paths configured by its owner are executed.
        command=shlex.join([cfg.get('python','python3'),str(Path(cfg['repository'])/'scripts/mailbox_rpc.py')])
        argv=['ssh','-o','BatchMode=yes','-o','ForwardAgent=no','-o','StrictHostKeyChecking=yes',host,command]
        packet={'root':cfg['root'],'op':op,'run_id':safe_id(run_id),'value':value}
        proc=subprocess.run(argv,input=json.dumps(packet),text=True,capture_output=True,timeout=cfg.get('timeout',120))
        if proc.returncode: raise RuntimeError('SSH mailbox unavailable; preserve session; no model retry')
        reply=json.loads(proc.stdout)
        if 'error' in reply: raise RuntimeError(reply['error'])
        return reply['result']
