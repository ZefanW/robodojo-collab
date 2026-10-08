"""Single contributor, single immutable scene. No central coordinator or account sharing."""
from __future__ import annotations
import argparse, fcntl, hashlib, importlib, json, os, re, shutil, socket, subprocess, sys, threading, time
from pathlib import Path
import platform, shlex, secrets
from .doctor import sha, cgroup_limits, memory_headroom
from .transport import Mailbox, atomic, safe_id
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'scripts/runtime'
MODEL='gpt-6-astra'

def read(p):return json.loads(Path(p).read_text())
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def load(config):return read(config)

def work_id(package):
    a=package['algorithm'];s=package['scene']
    return ':'.join([a['algorithm_id'],a['version'],s['task'],'s'+str(s['official_seed']),'l'+str(s['layout_ordinal']),s['asset_sha256'],'a'+str(package['attempt']['index'])])


class AssignmentGuard:
    def __init__(self,cfg,package):
        self.cfg=cfg;self.package=package;self.last=0;self.observed=None
        self.token=Path(cfg['token_file']).expanduser().read_text().strip()
        self.work=work_id(package);self.owner=package['attempt']['contributor_id'];self.run=package['run_id'];self.execution=None
        if package.get('work_id')!=self.work:raise RuntimeError('Shared work identity differs from immutable package')
    def operation(self,action):
        from . import claims
        if self.cfg['mode']=='git':
            return claims.git_ledger(self.cfg['remote'],self.cfg.get('branch','work-claims'),action,self.work,self.owner,self.token,run_id=self.run,execution_instance_id=self.execution)
        if self.cfg['mode']=='shared':
            if action=='bind':return claims.bind(self.cfg['ledger'],self.work,self.owner,self.token,self.run,self.execution)
            return claims._owned(claims._path(self.cfg['ledger'],self.work),self.owner,self.token)
        raise RuntimeError('Use authoritative Git CAS or shared POSIX ledger; independent clone assertions are insufficient')
    def bind(self,execution_instance_id=None):
        self.execution=execution_instance_id
        self.observed=self.operation('bind');self.last=time.time();return self.check()
    def check(self):
        if self.observed is None or time.time()-self.last>=60:
            self.observed=self.operation('inspect');self.last=time.time()
        d=self.observed;expected=hashlib.sha256(self.token.encode()).hexdigest()
        token_ok=d.get('token_sha256')==expected or d.get('token')==self.token
        if d.get('owner')!=self.owner or not token_ok or d.get('run_id')!=self.run or (self.execution and d.get('execution_instance_id')!=self.execution) or d.get('status')!='claimed' or d.get('expires_unix',0)<=time.time():
            raise RuntimeError('Shared claim expired, changed owner or bound to another run; preserve original session')
        return d

def verify_sources(config):
    lock=read(ROOT/'registry/source-lock.json')
    for name, expected in lock['portable_files'].items():
        if sha(ROOT/name)!=expected:raise RuntimeError('Portable source changed: '+name)
    upstream=Path(config['controller']['roboprobe'])
    for name,expected in lock['roboprobe_files'].items():
        if sha(upstream/name)!=expected:raise RuntimeError('RoboProbe source mismatch: '+name)
    return lock


def validate_package(package):
    safe_id(package['run_id']); scene=package['scene'];safe_id(scene['task'])
    if type(scene['official_seed']) is not int or scene['official_seed'] not in (0,1,2):raise ValueError('Only real official directories 0/1/2')
    if type(scene['layout_ordinal']) is not int or scene['layout_ordinal']<0:raise ValueError('Invalid independent layout ordinal')
    if not re.fullmatch('[0-9a-f]{64}',scene['asset_sha256']):raise ValueError('Asset SHA required')
    a=package['algorithm']
    if (a['algorithm_id'],a['model'],a['reasoning_effort'],a['codex_client_version'])!=('astra-l3-persistent-cap20','gpt-6-astra','medium','0.153.4'):
        raise ValueError('Unsupported frozen algorithm/client; register a different algorithm explicitly')
    if package['protocol']['action_limit']!=20 or package['protocol'].get('max_model_decisions')!=100:raise ValueError('Frozen cap20/cap100 mismatch')
    return package


def verify_scene(package, cfg):
    scene=package['scene'];repo=Path(cfg['simulator']['robodojo'])
    directory=repo/'Assets/Eval_Layout/RoboDojo/arx_x5'/str(scene['official_seed'])
    pattern=re.compile(re.escape(scene['task'])+r'_(\d+)\.json')
    files=sorted([p for p in directory.iterdir() if pattern.fullmatch(p.name)],key=lambda p:int(pattern.fullmatch(p.name)[1]))
    if scene['layout_ordinal']>=len(files):raise ValueError('Structural absence: requested layout does not exist')
    asset=files[scene['layout_ordinal']]
    if asset.relative_to(repo).as_posix()!=scene['asset_path'] or sha(asset)!=scene['asset_sha256']:raise ValueError('True asset selection/SHA differs')
    mapping=read(ROOT/'registry/simulator-mapping.json')['tasks']
    if mapping[scene['task']]!=cfg['simulator']['family']:raise ValueError('Simulator differs from matched baseline; use separate protocol')
    return asset


class BudgetGuard:
    """Fresh passive evidence only. Shared account consumption remains account-wide."""
    def __init__(self,cfg):
        self.cfg=cfg;self.path=Path(cfg['snapshot_file'])
        reserve=cfg.get('reserve_percent')
        if type(reserve) not in (int,float) or not 0<=reserve<=100:raise ValueError('Contributor must explicitly set reserve_percent')
        if not re.fullmatch('[0-9a-f]{64}',cfg.get('account_identity_sha256','')):raise ValueError('Local identity binding must be configured')
        if cfg.get('allow_existing_credits') not in (True,False):raise ValueError('Explicit credit policy required')
    def observe(self,snapshot,observed,source):
        account=snapshot.get('accountId')
        if not account or hashlib.sha256(account.encode()).hexdigest()!=self.cfg['account_identity_sha256']:
            raise RuntimeError('Passive notification identity unknown or changed')
        atomic(self.path,{'observed_unix':observed,'source':'native-passive-notification','snapshot':snapshot})
        self.check()
    def check(self):
        data=read(self.path);snapshot=data['snapshot'];now=time.time()
        if data.get('source')!='native-passive-notification' or not 0<=now-data['observed_unix']<=self.cfg.get('max_age_seconds',300):
            raise RuntimeError('Fresh passive allowance unavailable; preserve scene')
        account=snapshot.get('accountId')
        if not account or hashlib.sha256(account.encode()).hexdigest()!=self.cfg['account_identity_sha256']:raise RuntimeError('Account identity changed')
        sources=list((snapshot.get('rateLimitsByLimitId') or {}).values()) or [snapshot.get('rateLimits')]
        windows=[s[k] for s in sources if isinstance(s,dict) for k in ('primary','secondary') if isinstance(s.get(k),dict)]
        if not windows or any(type(w.get('usedPercent')) not in (int,float) for w in windows):raise RuntimeError('Allowance unknown')
        if snapshot.get('spendControlReached') or any(s.get('spendControlReached') for s in sources if isinstance(s,dict)):raise RuntimeError('Spend control reached')
        if any(type(w.get('resetsAt')) in (float,int) and w['resetsAt']<=now for w in windows):raise RuntimeError('Passive allowance crossed reset time; fresh evidence needed')
        stop=100-self.cfg['reserve_percent'];used=max(w['usedPercent'] for w in windows)
        if used>=stop:
            credits=[s.get('credits') for s in sources if isinstance(s,dict)]
            usable=False
            if self.cfg['allow_existing_credits'] and self.cfg['reserve_percent']==0:
                for credit in credits:
                    if isinstance(credit,dict) and credit.get('hasCredits') is True:
                        try:usable |= float(credit.get('balance'))>float(self.cfg.get('credit_reserve',0))
                        except (TypeError,ValueError):pass
            if not usable:raise RuntimeError('Contributor reserve reached')
        return snapshot


def prepare_bridge(cfg, folder, stop, guard):
    verify_sources(cfg);c=cfg['controller'];codex=Path(c['codex']).expanduser().resolve()
    if sha(codex)!=c['codex_sha256']:raise RuntimeError('Client binary SHA differs')
    version=subprocess.check_output([str(codex),'--version'],text=True).strip()
    if version!='codex-cli 0.153.4':raise RuntimeError('Frozen client 0.153.4 required; no silent upgrade')
    authhome=Path(c['auth_home']).expanduser().resolve()
    if not (authhome/'auth.json').is_file():raise RuntimeError('Sign in with your own pinned Codex client first')
    # Read only the identity field in-process; never print, copy, or archive credential contents.
    identity=(read(authhome/'auth.json').get('tokens') or {}).get('account_id')
    if not identity or hashlib.sha256(identity.encode()).hexdigest()!=guard.cfg['account_identity_sha256']:
        raise RuntimeError('Own login identity does not match passive allowance; no paid call')
    os.environ['ROBODOJO_CODEX']=str(codex);os.environ['ROBODOJO_AUTH_HOME']=str(authhome)
    for key in ('OPENAI_API_KEY','OPENAI_BASE_URL','CODEX_API_KEY','OPENAI_ORG_ID','OPENAI_PROJECT_ID'):os.environ.pop(key,None)
    sys.path.insert(0,str(Path(c['roboprobe']).resolve()));sys.path.insert(0,str(RUNTIME))
    from persistent_v1.bridge import PersistentBridge
    return PersistentBridge(folder,guard.cfg['account_identity_sha256'],stop,guard,retry_authorization=None)


def native_owner(cfg,package,local,require_existing=False):
    mailbox=Mailbox(cfg['transport']);run=package['run_id'];status=mailbox.request('status',run)
    if status.get('package_sha256')!=digest(package):raise RuntimeError('Native scene package differs')
    if not status.get('native_result_exists') and not all(status.get('owned_processes_alive',{}).get(k) for k in ('server','simulator')):
        raise RuntimeError('Original native process identity unavailable; do not deliver any pending action')
    execution=status.get('execution_instance_id')
    if not isinstance(execution,str) or not re.fullmatch('[0-9a-f]{64}',execution):raise RuntimeError('Native execution-instance binding missing')
    assignment=AssignmentGuard(cfg['claim'],package);assignment.bind(execution)
    owner=local/'controller-identity'
    if not owner.exists():
        if require_existing:raise RuntimeError('Original controller identity missing; explicit migration audit required')
        with owner.open('x') as f:f.write(secrets.token_hex(32))
        owner.chmod(0o600)
    mailbox.request('owner-acquire',run,{'controller_id':owner.read_text().strip(),'package_sha256':digest(package)})
    return assignment

def reconcile(cfg, package, local):
    """Deliver existing immutable receipts before proving a clean next boundary."""
    mailbox=Mailbox(cfg['transport']);run=package['run_id'];calls=local/'calls'
    receipts=sorted(calls.glob('*/response.json'))
    for paid in sorted(calls.glob('*/paid-start.json')):
        if not (paid.parent/'response.json').exists():raise RuntimeError('Unresolved paid boundary '+paid.parent.name+'; inspect original journal, never regenerate')
    if receipts:native_owner(cfg,package,local,require_existing=True)
    for p in receipts:
        receipt=read(p);index=int(p.parent.name);remote=mailbox.request('receipt',run,{'index':index})
        if remote is None:mailbox.request('deliver',run,{'index':index,'receipt':receipt})
        elif remote!=receipt:raise RuntimeError('Remote paid receipt differs')
    history=local/'session/permanent-history/state.json'
    if not history.exists():return {'next_index':0,'thread':None}
    h=read(history)
    if len(receipts)!=h['next_index']:raise RuntimeError('History commit does not match paid receipts; reconcile locally first')
    if not receipts:raise RuntimeError('Partially initialized session needs journal reconciliation')
    if (history.parent/f"input-{h['next_index']:04d}.json").exists():raise RuntimeError('Pending input was already ingested; reconcile its original native injection receipt before continuing')
    last=read(receipts[-1].parent/'thread.json');journal=Path(last['thread']['path'])
    if not journal.is_file():raise RuntimeError('Original native journal unavailable; no fresh-thread fallback')
    proof={'next_index':h['next_index'],'thread':last['thread']['id'],'history_sha256':sha(history),'journal':str(journal),'journal_sha256':sha(journal)}
    atomic(local/'resume-proof.json',proof);return proof


def controller(cfg, package, resume=False, once=False):
    package=validate_package(package);run=package['run_id'];root=Path(cfg['controller']['state_root']).expanduser().resolve();root.mkdir(parents=True,exist_ok=True)
    local=root/run;local.mkdir(exist_ok=True)
    lock=(local/'owner.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    package_path=local/'package.json'
    if package_path.exists() and read(package_path)!=package:raise RuntimeError('Run package changed')
    atomic(package_path,package)
    if not cfg.get('execution_authorized'):raise RuntimeError('Set execution_authorized only after your budget/claim review')
    # Read actual native ownership before any delivery or new paid call.
    guard=BudgetGuard(cfg['budget']);guard.check()
    existing=bool(list((local/'calls').glob('*/paid-start.json')))
    if (existing or (local/'session/permanent-history/state.json').exists()) and not resume:raise RuntimeError('Existing private history: use resume/reconcile; never start a replacement thread')
    assignment=native_owner(cfg,package,local,require_existing=existing)
    proof=reconcile(cfg,package,local) if resume else {'next_index':0,'thread':None}
    mailbox=Mailbox(cfg['transport'])
    stop=threading.Event();bridge=prepare_bridge(cfg,local/'session',stop,guard)
    try:
        if proof['thread']:
            if sha(proof['journal'])!=proof['journal_sha256']:raise RuntimeError('Journal changed after reconciliation')
            import codex_bridge
            t=bridge.transport.request('thread/resume',dict(threadId=proof['thread'],cwd=str(bridge.agent),model=MODEL,modelProvider='openai',config={'model_reasoning_effort':'medium'},excludeTurns=True,approvalPolicy='never',permissions='rollout_agent',runtimeWorkspaceRoots=[str(bridge.agent)]),60)
            if t['thread']['id']!=proof['thread'] or t['thread']['status']['type']!='idle' or t.get('model')!=MODEL or t.get('reasoningEffort')!='medium' or t.get('instructionSources'):
                raise RuntimeError('Original session is not a clean matching idle boundary')
            base,*_=codex_bridge.pack(bridge.history.messages,bridge.history.tools)
            bridge.episode_thread=t;bridge.episode_contract=(base,bridge.history.tools)
        while True:
            if (local/'pause.request').exists():raise RuntimeError('User pause; native scene remains alive')
            assignment.check();guard.check()
            native_state=mailbox.request('status',run)
            if native_state.get('package_sha256')!=digest(package):raise RuntimeError('Native scene package differs')
            if not native_state.get('native_result_exists') and not all(native_state.get('owned_processes_alive',{}).get(k) for k in ('server','simulator')):
                raise RuntimeError('Original native process identity unavailable; no paid continuation')
            pending=mailbox.request('next',run)
            if pending is None:
                status=mailbox.request('status',run)
                if status.get('native_result_exists'):
                    atomic(local/'native-result-observed.json',{'time':time.time(),'requires_terminal_validation':True});return
                if once:return
                time.sleep(2);continue
            index=pending['index'];payload=pending['payload']
            if payload.get('run_id')!=run or payload.get('index')!=index:raise RuntimeError('Request identity mismatch')
            systems=[m['content'] for m in payload['messages'] if m.get('role')=='system']
            prompt=hashlib.sha256('\n\n'.join(systems).encode()).hexdigest()
            tools=hashlib.sha256(json.dumps(payload['tools'],sort_keys=True).encode()).hexdigest()
            if prompt!=package['algorithm']['prompt_sha256'] or tools!=package['algorithm']['tools_sha256']:raise RuntimeError('Prompt/tool contract changed before paid turn')
            if index!=bridge.history.next_index:raise RuntimeError('Pending boundary/history mismatch')
            folder=local/'calls'/f'{index:04d}'
            saved=bridge.complete(payload,pending['request_sha256'],folder)
            mailbox.request('deliver',run,{'index':index,'receipt':saved})
            atomic(folder/'delivered.json',{'request_sha256':pending['request_sha256'],'time':time.time()})
            if once:return
    finally:bridge.close()


def native_start(cfg,package):
    """Run on simulator host. Launch once; never stop/restart someone else's process."""
    validate_package(package);verify_scene(package,cfg);sim=cfg['simulator'];run=package['run_id']
    if not cfg.get('execution_authorized') or not sim.get('license_accepted'):raise RuntimeError('Execution/license acceptance must be explicit')
    safe_id(sim['machine_id'])
    root=Path(sim['output_root']).expanduser().resolve();root.mkdir(parents=True,exist_ok=True);out=root/run
    if out.exists():raise RuntimeError('Native run directory exists; preserve original scene, never relaunch')
    repo=Path(sim['robodojo']).resolve();upstream=Path(sim['roboprobe']).resolve();python=str(Path(sim['python']).resolve());gpu=int(sim['gpu']);port=int(sim['port'])
    for rel,expected in read(ROOT/'registry/source-lock.json')['roboprobe_files'].items():
        if sha(upstream/rel)!=expected:raise RuntimeError('RoboProbe runtime differs: '+rel)
    for rel,expected in sim['native_source_sha256'].items():
        if sha(repo/rel)!=expected:raise RuntimeError('Native source mismatch: '+rel)
    for required in ['src/eval_client/main.py','src/eval_client/rollout_audit.py','env/seed_manager/seed_manager.py']:
        if required not in sim['native_source_sha256']:raise RuntimeError('Missing native source lock '+required)
    usage=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free','--format=csv,noheader,nounits'],text=True)
    free={int(a):int(b) for a,b in (line.split(',') for line in usage.splitlines())}
    if free[gpu]<sim.get('minimum_free_vram_mib',12000):raise RuntimeError('Insufficient free VRAM; no process displaced')
    memory=memory_headroom()
    if memory['available_bytes'] is None or memory['available_bytes']<47*1024**3:raise RuntimeError('Need verified available memory >=47 GiB for startup; cgroup limits included when present')
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('Configured native port is busy')
    if shutil.disk_usage(root).free<sim.get('minimum_disk_free_bytes',20*1024**3):raise RuntimeError('Insufficient output/temp storage')
    # Policy is installed in contributor's own RoboProbe checkout; exact copied wrapper is checked.
    policy_dir=upstream/'policy/L3_PersistentCap20'
    for source in (RUNTIME/'policy').iterdir():
        if source.is_file() and source.suffix in ('.py','.yml') and sha(policy_dir/source.name)!=sha(source):raise RuntimeError('Install locked policy wrapper with prepare-native first')
    metadata_script="""import importlib.metadata as m,json,re
pending=['isaacsim','isaaclab','curobo','torch','websockets','numpy','openai','pillow','pyyaml','opencv-python-headless','h5py','msgpack','msgpack-numpy','pydantic','requests','omegaconf'];out={};seen=set()
while pending:
 n=pending.pop();n=n.lower().replace('_','-')
 if n in seen:continue
 seen.add(n)
 try:d=m.distribution(n)
 except m.PackageNotFoundError:continue
 out[n]=d.version
 for entry in d.requires or []:
  match=re.match(r'[A-Za-z0-9_.-]+',entry)
  if match:pending.append(match.group())
print(json.dumps(dict(sorted(out.items()))))"""
    versions=json.loads(subprocess.check_output([python,'-c',metadata_script],text=True))
    family_prefix='5.1' if sim['family']=='Sim5.1' else '6.0'
    if not str(versions.get('isaacsim') or '').startswith(family_prefix):raise RuntimeError('Actual simulator version differs from assigned family')
    gpu_metadata=subprocess.check_output(['nvidia-smi','--query-gpu=index,name,driver_version','--format=csv,noheader'],text=True)
    gpu_info={int(row.split(',')[0]):[v.strip() for v in row.split(',')[1:]] for row in gpu_metadata.splitlines()}[gpu]
    public_environment={'simulator_version':versions['isaacsim'],'machine_id':sim['machine_id'],'gpu':gpu_info[0],'driver':gpu_info[1],'os':platform.system()+' '+platform.release(),'dependencies':versions}
    execution_instance_id=digest({'machine_id':sim['machine_id'],'output_root':str(root),'run_id':run})
    AssignmentGuard(cfg['claim'],package).bind(execution_instance_id)
    out.mkdir();scene=package['scene'];label='collab-cap20-v1';seed=scene['official_seed']
    env={**os.environ,**sim.get('environment',{})}
    for key in list(env):
        if key in ('CUDA_VISIBLE_DEVICES','OPENAI_API_KEY','OPENAI_API_KEY_BACKUP','CODEX_API_KEY','OPENAI_BASE_URL','AZURE_OPENAI_API_KEY','MOONSHOT_API_KEY'):env.pop(key,None)
    env.update(PYTHONPATH=os.pathsep.join([str(upstream),str(repo),str(upstream/'utils')]),PYTHONNOUSERSITE='1',OMP_NUM_THREADS='4',MKL_NUM_THREADS='4',OPENBLAS_NUM_THREADS='4',
        OMNI_KIT_ACCEPT_EULA='YES',ACCEPT_EULA='Y',ROBODOJO_RUN_ID=run,ROBODOJO_ROOT=str(repo),ROBODOJO_LAYOUT_IDS=str(scene['layout_ordinal']),EVAL_NUM='1',
        ROBODOJO_MAX_INPROC_RESTARTS='0',ROBODOJO_MAX_BASH_RETRIES='0',ROBODOJO_AUDIT='1',ROBODOJO_CUROBO_DEVICE=f'cuda:{gpu}',ROBODOJO_ACTION_TYPE='joint',
        L3_INSPECT_ACTION_TYPE='joint',L3_INSPECT_TRACE_DIR=str(out/'trace'),L3_CODEX_MAILBOX=str(out/'mailbox'),L3_INSPECT_MAX_RETRIES='0',L3_INSPECT_MAX_LLM_CALLS='100',
        L3_INSPECT_REASONING_EFFORT='medium',L3_INSPECT_IMAGE_HORIZON='2',L3_INSPECT_KEEP_ALL_IMAGES='1',L3_INSPECT_USE_RECIPE='1',L3_CAP20_SOURCE_POLICY_KIND='eef',L3_CAP20_AUDIT_DIR=str(out/'cap20-audit'))
    server=[python,'-u',str(upstream/'scripts/setup_policy_server.py'),'--config_path',str(policy_dir/'deploy.yml'),'--overrides','task_name='+scene['task'],f'port={port}',f'gpu_id={gpu}']
    command=[python,'-u','src/eval_client/main.py','--task_name',scene['task'],'--env_cfg_type','arx_x5','--num_envs','1','--enable_cameras','--device_id',str(gpu),'--device',f'cuda:{gpu}','--policy_name','L3_PersistentCap20','--port',str(port),'--protocol','ws','--host','127.0.0.1','--additional_info',label,'--seed',str(seed),'--headless','--kit_args',f'--/app/fastShutdown=true --/renderer/multiGpu/enabled=false --/renderer/activeGpu={gpu} --/physics/cudaDevice={gpu}']
    info={'run_id':run,'execution_instance_id':execution_instance_id,'package_sha256':digest(package),'policy_sha256':sha(policy_dir/'cap20_policy.py'),'source_lock_sha256':sha(ROOT/'registry/source-lock.json'),'public_environment':public_environment,'native_source_sha256':sim['native_source_sha256'],'startup_memory':memory,'status':'initializing','started_unix':time.time(),'server_command':server,'simulator_command':command,'native_dir':str(repo/'eval_result/RoboDojo'/scene['task']/'L3_PersistentCap20/arx_x5'/f'{seed}_{label}'/run)}
    atomic(out/'native.json',info)
    with (out/'server.log').open('x') as log:proc=subprocess.Popen(server,cwd=repo,env=env,stdout=log,stderr=log,start_new_session=True)
    info['server_pid']=proc.pid;atomic(out/'native.json',info)
    for _ in range(60):
        if proc.poll() is not None:raise RuntimeError('Policy server exited; logs retained, no relaunch')
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1',port))==0:break
        time.sleep(1)
    else:raise RuntimeError('Policy server readiness timeout; process retained')
    with (out/'simulator.log').open('x') as log:native=subprocess.Popen(command,cwd=repo,env=env,stdout=log,stderr=log,start_new_session=True)
    info['simulator_pid']=native.pid;info['status']='launched_not_yet_native_action';atomic(out/'native.json',info)
    return info


def collect(cfg,package,destination):
    """Copy only native/run artifacts; compare pre/post remote file manifests and local SHA."""
    validate_package(package);run=package['run_id'];mailbox=Mailbox(cfg['transport']);proof=mailbox.request('archive-manifest',run)
    out=Path(destination).expanduser().resolve()/run;out.mkdir(parents=True,exist_ok=True)
    transport=cfg['transport']
    for label,key in [('native','native_root'),('run','run_root')]:
        dest=out/label;dest.mkdir(exist_ok=True)
        if transport['mode']=='local':
            for row in proof['files']:
                if not row['path'].startswith(label+'/'):continue
                relative=Path(row['path']).relative_to(label);source=Path(proof[key])/relative;target=dest/relative
                target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists():shutil.copy2(source,target)
        else:
            # rsync's protected-args prevents remote shell expansion of configured paths.
            subprocess.run(['rsync','-a','--protect-args','--ignore-existing','--exclude=server.log','--exclude=simulator.log','--exclude=*.tmp','-e','ssh -o BatchMode=yes -o ForwardAgent=no -o StrictHostKeyChecking=yes',transport['host']+':'+proof[key]+'/',str(dest)+'/'],check=True)
    for row in proof['files']:
        p=out/row['path']
        if not p.is_file() or p.stat().st_size!=row['size'] or sha(p)!=row['sha256']:raise RuntimeError('Collected file collision/SHA mismatch: '+row['path'])
    after=mailbox.request('archive-manifest',run)
    if after['files']!=proof['files']:raise RuntimeError('Source changed during collection; preserve both evidence and original')
    # Local-only proof may contain source paths; public exporter projects an allowlisted copy.
    atomic(out/'collection-proof.json',{'schema_version':'1.0','run_id':run,'verified':True,'files':proof['files'],'native_result_sha256':proof['native_result_sha256'],'collected_unix':time.time()})
    return {'collected':str(out),'verified_files':len(proof['files']),'paid_calls':0}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['check','start','resume','reconcile','native-start','status','collect','binding-info']);parser.add_argument('--config',required=True);parser.add_argument('--package',required=True);parser.add_argument('--once',action='store_true');parser.add_argument('--destination')
    a=parser.parse_args(argv);cfg=load(a.config);package=validate_package(read(a.package))
    if a.command=='binding-info':
        sim=cfg['simulator'];root=Path(sim['output_root']).expanduser().resolve()
        print(json.dumps({'work_id':work_id(package),'run_id':package['run_id'],'execution_instance_id':digest({'machine_id':sim['machine_id'],'output_root':str(root),'run_id':package['run_id']})},indent=2));return
    if a.command=='check':verify_sources(cfg);print(json.dumps({'package_valid':True,'sources_valid':True,'paid_calls':0}));return
    if a.command=='collect':
        if not a.destination:parser.error('--destination required for collect')
        print(json.dumps(collect(cfg,package,a.destination),indent=2));return
    if a.command=='status':print(json.dumps(Mailbox(cfg['transport']).request('status',package['run_id']),indent=2));return
    if a.command=='native-start':print(json.dumps(native_start(cfg,package),indent=2));return
    if a.command=='reconcile':
        print(json.dumps(reconcile(cfg,package,Path(cfg['controller']['state_root']).expanduser()/package['run_id']),indent=2));return
    controller(cfg,package,resume=a.command=='resume',once=a.once)
if __name__=='__main__':main()
