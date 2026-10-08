"""Read-only diagnosis. Never installs, starts a GPU job, or calls a model."""
from __future__ import annotations
import argparse, hashlib, importlib.metadata, json, os, platform, re, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def capture(argv):
    try:
        p=subprocess.run(argv,capture_output=True,text=True,timeout=20)
        return {'ok':p.returncode==0,'output':p.stdout.strip()[:5000]}
    except (OSError,subprocess.TimeoutExpired):return {'ok':False,'output':None}

def cgroup_limits():
    if platform.system()!='Linux':return {'version':None,'limitation':'Controller OS; simulator must be diagnosed on its own host'}
    membership=Path('/proc/self/cgroup').read_text().splitlines()
    mount_lines=Path('/proc/self/mountinfo').read_text().splitlines(); out={}
    for line in membership:
        _, controllers, subgroup=line.split(':',2)
        for mount in mount_lines:
            left,right=mount.split(' - ',1); fields=left.split(); fs=right.split()
            if fs[0]=='cgroup2' and not controllers: names=('memory.max','memory.current','cpu.max');version=2
            elif fs[0]=='cgroup' and set(controllers.split(',')) & set(fs[2].split(',')):names=('memory.limit_in_bytes','memory.usage_in_bytes','cpu.cfs_quota_us','cpu.cfs_period_us');version=1
            else:continue
            mountroot=fields[3];point=Path(fields[4]); rel=os.path.relpath(subgroup,mountroot)
            # Namespaced cgroups may expose only the container root.
            path=point/rel if not rel.startswith('..') else point
            out['version']=version
            for name in names:
                file=path/name
                if file.exists():out[name]=file.read_text().strip()
    return out or {'error':'Actual process cgroup not resolved; no host-total substitution'}

def memory_headroom():
    """Actual Linux available memory, limited by a finite process cgroup when present."""
    if platform.system()!='Linux':return {'available_bytes':None,'source':'not-a-linux-simulator'}
    try:
        values={line.split(':',1)[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if len(line.split())>=3}
        physical=values['MemAvailable']
    except (OSError,ValueError,KeyError):return {'available_bytes':None,'source':'unavailable'}
    group=cgroup_limits();maximum=group.get('memory.max',group.get('memory.limit_in_bytes'));used=group.get('memory.current',group.get('memory.usage_in_bytes'))
    finite=maximum and maximum.isdigit() and int(maximum)<(1<<60) and used and used.isdigit()
    return {'available_bytes':min(physical,max(0,int(maximum)-int(used))) if finite else physical,
            'source':'min-MemAvailable-and-process-cgroup' if finite else 'proc-meminfo-MemAvailable',
            'physical_available_bytes':physical,'cgroup':group}

def run(config=None):
    cfg=json.loads(Path(config).read_text()) if config else {}
    client=cfg.get('controller',{}).get('codex','codex')
    out={'python':platform.python_version(),'os':platform.system(),'architecture':platform.machine(),'cgroup':cgroup_limits(),'memory':memory_headroom(),
         'codex':capture([client,'--version']),'tools':{p:bool(shutil.which(p)) for p in ['git','ssh','ffmpeg','nvidia-smi']},
         'gpu':capture(['nvidia-smi','--query-gpu=index,name,driver_version,memory.total,memory.free','--format=csv,noheader,nounits']),
         'dependencies':{},'paid_calls':0,'gpu_tasks_started':0,'limitations':[]}
    for package in ['isaacsim','torch','websockets','numpy','openai','pillow']:
        try:out['dependencies'][package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:out['dependencies'][package]=None
    if config:
        c=cfg.get('controller',{});sim=cfg.get('simulator',{})
        resolved=shutil.which(client) or client
        out['codex']['sha256']=sha(resolved) if Path(resolved).is_file() else None
        out['codex']['locked']=out['codex']['output']=='codex-cli 0.153.4' and out['codex']['sha256']==c.get('codex_sha256')
        target=Path(sim.get('output_root','.')).expanduser()
        while not target.exists():target=target.parent
        disk=shutil.disk_usage(target);out['disk']={'free_bytes':disk.free,'total_bytes':disk.total}
        out['budget_configured']=isinstance(cfg.get('budget',{}).get('reserve_percent'),(float,int))
    out['limitations'] += ['Package/version checks do not prove RTX rendering, native physics, three camera validity or Astra entitlement.',
                           'A100/A800 GPU compute availability does not prove RTX renderer support; run NVIDIA compatibility checker.',
                           'No login credentials are read or copied by doctor.']
    return out

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config');p.add_argument('--output')
    a=p.parse_args(argv);data=run(a.config);raw=json.dumps(data,indent=2)
    if a.output:Path(a.output).write_text(raw+'\n')
    print(raw)
if __name__=='__main__':main()
