"""Content-addressed Seafile publishing. Credentials are never part of a bundle.

Authenticate once with a user-created API token via `login`; subsequent commands
use the OS-protected external token file. Every completed object is downloaded
and hashed. Unknown POST outcomes are reconciled, never blindly retransmitted.
"""
from __future__ import annotations
import argparse, getpass, hashlib, json, os, re, sys, tempfile, uuid, subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, urlopen
from urllib.error import HTTPError
from .schema import file_sha256, load_manifest, privacy_findings

class StorageError(RuntimeError): pass
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def now(): return datetime.now(timezone.utc).isoformat()

def require_https(url,origin=False):
    try:u=urlsplit(url)
    except (ValueError,TypeError):raise StorageError('Valid HTTPS URL required') from None
    if u.scheme!='https' or not u.hostname or u.username or u.password or (origin and (u.path not in ('','/') or u.query or u.fragment)):
        raise StorageError('HTTPS server origin required' if origin else 'Public HTTPS URL without embedded credentials required')
    return u

def credential_destination(path):
    candidate=Path(path).expanduser()
    if candidate.is_symlink():raise StorageError('Credential file cannot be a symlink')
    p=candidate.resolve();roots={Path(__file__).resolve().parents[1],Path.cwd().resolve()}
    try:
        r=subprocess.run(['git','rev-parse','--show-toplevel'],capture_output=True,text=True,timeout=5)
        if r.returncode==0:roots.add(Path(r.stdout.strip()).resolve())
    except (OSError,subprocess.TimeoutExpired):pass
    if any(p==root or root in p.parents for root in roots):raise StorageError('Token must be outside this repository and the current working directory')
    return p

@contextmanager
def publication_lock(server,library):
    """Serialize this user's local publishers; not a global Seafile lock."""
    try:import fcntl
    except ImportError:raise StorageError('Local publication locking requires POSIX; use a supported Linux/macOS control host') from None
    lockroot=Path.home()/'.config'/'robodojo-collab'/'publication-locks';lockroot.mkdir(parents=True,exist_ok=True,mode=0o700)
    key=hashlib.sha256((server.rstrip('/')+'\n'+library).encode()).hexdigest()
    fd=os.open(lockroot/(key+'.lock'),os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise StorageError('Another local process is publishing to this library; wait and reconcile before retrying') from None
        yield
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n');os.replace(tmp,path)

def public_probe(url,expected_sha=None):
    """No auth headers; proves public download bytes, not browser codec/CORS."""
    try:
        require_https(url)
        with urlopen(Request(url,headers={'User-Agent':'RoboDojo-Collab/0.1'}),timeout=60) as r:
            h=hashlib.sha256();size=0;typ=r.headers.get('Content-Type','');cors=r.headers.get('Access-Control-Allow-Origin');rng=r.headers.get('Accept-Ranges')
            for b in iter(lambda:r.read(1024*1024),b''):h.update(b);size+=len(b)
        good=expected_sha is None or h.hexdigest()==expected_sha
        return {'ok':good,'sha256':h.hexdigest(),'bytes':size,'content_type':typ,'cors':cors,'accept_ranges':rng,'checked_at':now()}
    except Exception as ex:return {'ok':False,'error_type':type(ex).__name__,'checked_at':now()}

class Seafile:
    def __init__(self,server,repo_id,token):
        require_https(server,origin=True)
        if not re.fullmatch(r'[a-f0-9-]{36}',repo_id):raise StorageError('Invalid library ID')
        self.server=server.rstrip('/');self.repo=repo_id;self.token=token
    def api(self,path,method='GET',payload=None):
        data=json.dumps(payload).encode() if payload is not None else None
        req=Request(self.server+path,data=data,method=method,headers={'Authorization':'Token '+self.token,'Accept':'application/json','Content-Type':'application/json'})
        # Never carry the API credential to a redirect or file-storage host.
        try:
            with build_opener(NoRedirect()).open(req,timeout=60) as r:return json.load(r)
        except HTTPError as ex:raise StorageError(f'Seafile API returned HTTP {ex.code}; no credentials or response body logged') from None
    def directory(self):return self.api(f'/api2/repos/{self.repo}/dir/?p=/')
    def remote_file(self,name):return next((x for x in self.directory() if x.get('name')==name),None)
    def verify(self,name,sha):
        url=self.api(f'/api2/repos/{self.repo}/file/?'+urlencode({'p':'/'+name}))
        require_https(url)
        probe=public_probe(url,sha)
        if not probe['ok']:raise StorageError('Remote read-back SHA256 mismatch or unavailable; preserve local state')
        # Temporary authenticated download capabilities never enter receipts.
        return probe
    def upload(self,path):
        path=Path(path);sha=file_sha256(path);name=sha+'--'+path.name
        if any(ord(c)<32 for c in path.name) or '"' in path.name or '\\' in path.name:raise StorageError('Unsafe filename for multipart upload')
        if self.remote_file(name):return name,sha,self.verify(name,sha),'reused'
        if path.stat().st_size>128*1024*1024:raise StorageError('Object exceeds 128 MiB. Use pack --chunk-mib 64 first; do not load a giant artifact in memory')
        url=self.api(f'/api2/repos/{self.repo}/upload-link/?p=/')
        require_https(url)
        # The upload capability is scoped by Seafile, not an API bearer token.
        boundary='robodojo'+uuid.uuid4().hex
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="parent_dir"\r\n\r\n/\r\n--{boundary}\r\nContent-Disposition: form-data; name="replace"\r\n\r\n0\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()+path.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
        req=Request(url+('&' if '?' in url else '?')+'ret-json=1',data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
        receipt=None
        try:
            with urlopen(req,timeout=180) as r:receipt=json.load(r)
        except Exception:
            # A lost acknowledgement may have committed. One read-only lookup,
            # zero automatic repeat uploads; caller can resume later.
            if not self.remote_file(name):raise StorageError('Upload outcome unknown or incomplete. Resume later to reconcile by name and SHA; no blind retry was made') from None
        if isinstance(receipt,list) and any(x.get('name')!=name for x in receipt):raise StorageError('Server renamed upload; possible concurrent duplicate. Reconcile manually; no success receipt was published')
        return name,sha,self.verify(name,sha),'uploaded'
    def share(self,name):
        links=self.api('/api/v2.1/share-links/?'+urlencode({'repo_id':self.repo,'path':'/'+name}))
        if isinstance(links,list) and links:return links[0]['link']
        item=self.api('/api/v2.1/share-links/','POST',{'repo_id':self.repo,'path':'/'+name,'permissions':{'can_download':True,'can_edit':False}})
        return item['link']

def token_path():return Path(os.environ.get('ROBOCOLLAB_SEAFILE_TOKEN_FILE',str(Path.home()/'.config'/'robodojo-collab'/'seafile-token')))
def token():
    value=os.environ.get('ROBOCOLLAB_SEAFILE_TOKEN')
    if value:
        if '\n' in value.strip() or '\r' in value:raise StorageError('Invalid API credential')
        return value.strip()
    p=token_path()
    if not p.exists():raise StorageError('No Seafile API login. Run python -m robodojo_collab.storage login in your terminal; do not paste credentials into chat or Git')
    if p.is_symlink():raise StorageError('Token file cannot be a symlink')
    if p.stat().st_mode & 0o077:raise StorageError('Token file permissions must be 0600')
    return p.read_text().strip()

def publish(args):
    client=Seafile(args.server,args.library,token());p=Path(args.file)
    if not p.is_file():raise StorageError('File missing')
    with publication_lock(args.server,args.library):
        name,sha,verified,action=client.upload(p);landing=client.share(name)
    require_https(landing)
    dl=landing+('?dl=1' if '?' not in landing else '&dl=1');pub=public_probe(dl,sha)
    receipt={'provider':'tsinghua' if urlsplit(args.server).hostname=='cloud.tsinghua.edu.cn' else 'seafile','sha256':sha,'bytes':p.stat().st_size,'remote_name':name,'landing_url':landing,'download_url':dl if pub['ok'] else None,'playback_url':None,'verification':'remote_sha256','verified_at':now(),'public_download_verified':pub['ok'],'public_probe':pub,'action':action}
    if pub['ok'] and p.suffix.lower() in ('.mp4','.webm'):
        raw=landing+('?raw=1' if '?' not in landing else '&raw=1');v=public_probe(raw,sha)
        # Candidate still needs browser media loaded/playback QA before promotion.
        if v['ok'] and v['content_type'].startswith('video/'):
            receipt['playback_candidate']=raw;receipt['browser_playback_verified']=False
    if pub['ok'] and p.suffix.lower()=='.json' and pub.get('cors') in ('*',args.site_origin):receipt['json_url']=dl
    if privacy_findings(receipt):raise StorageError('Public receipt failed privacy scan')
    write_json(args.receipt,receipt);print(json.dumps({'action':action,'sha256':sha,'remote_sha256':True,'public_download_verified':pub['ok'],'receipt':str(args.receipt)}))

def pack(args):
    """Split an already validated deterministic archive into immutable chunks."""
    src=Path(args.file);out=Path(args.output);out.mkdir(parents=True,exist_ok=True);parts=[]
    source_sha=file_sha256(src);source_size=src.stat().st_size;manifest_path=out/'chunks.json'
    if manifest_path.exists():
        prior=json.loads(manifest_path.read_text())
        if (prior.get('file'),prior.get('sha256'),prior.get('bytes'))!=(src.name,source_sha,source_size):raise StorageError('Output already contains a different immutable chunk manifest')
        for part in prior['chunks']:
            p=out/part['path']
            if not p.is_file() or p.stat().st_size!=part['bytes'] or file_sha256(p)!=part['sha256']:raise StorageError('Existing chunk manifest is incomplete or corrupt; preserve it for diagnosis')
        print(json.dumps({'chunks':len(prior['chunks']),'sha256':source_sha,'status':'already_present'}));return
    with src.open('rb') as f:
        for i in range(100000):
            b=f.read(args.chunk_mib*1024*1024)
            if not b:break
            sha=hashlib.sha256(b).hexdigest();p=out/f'{i:05d}-{sha}.part'
            if p.exists() and file_sha256(p)!=sha:raise StorageError('Existing chunk content conflict')
            if not p.exists():
                fd,tmp=tempfile.mkstemp(prefix='.chunk-',dir=out)
                try:
                    with os.fdopen(fd,'wb') as stream:stream.write(b);stream.flush();os.fsync(stream.fileno())
                    try:os.link(tmp,p)
                    except FileExistsError:
                        if file_sha256(p)!=sha:raise StorageError('Concurrent chunk content conflict')
                finally:os.unlink(tmp)
            parts.append({'path':p.name,'sha256':sha,'bytes':len(b)})
    if sum(part['bytes'] for part in parts)!=source_size or file_sha256(src)!=source_sha:raise StorageError('Source changed during packing or exceeds chunk limit; no manifest published')
    manifest={'file':src.name,'sha256':source_sha,'bytes':source_size,'chunks':parts}
    raw=(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n').encode();fd,tmp=tempfile.mkstemp(prefix='.manifest-',dir=out)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        try:os.link(tmp,manifest_path)
        except FileExistsError:
            if manifest_path.read_bytes()!=raw:raise StorageError('Concurrent immutable manifest conflict')
    finally:os.unlink(tmp)
    print(json.dumps({'chunks':len(parts),'sha256':manifest['sha256']}))

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    sub.add_parser('login',help='Prompt locally for an existing API token; save outside the repository with mode0600')
    p=sub.add_parser('status');p.add_argument('--server',default='https://cloud.tsinghua.edu.cn');p.add_argument('--library',required=True)
    p=sub.add_parser('publish');p.add_argument('file');p.add_argument('--server',default='https://cloud.tsinghua.edu.cn');p.add_argument('--library',required=True);p.add_argument('--receipt',required=True);p.add_argument('--site-origin',default='')
    p=sub.add_parser('probe');p.add_argument('url');p.add_argument('--sha256',required=True)
    p=sub.add_parser('pack');p.add_argument('file');p.add_argument('--output',required=True);p.add_argument('--chunk-mib',type=int,default=64)
    a=ap.parse_args(argv)
    try:
        if a.command=='login':
            p=credential_destination(token_path())
            value=getpass.getpass('Seafile API token (hidden; never logged): ').strip()
            if not value or '\n' in value:raise StorageError('Empty/invalid token')
            p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,'O_NOFOLLOW',0),0o600);os.fchmod(fd,0o600)
            with os.fdopen(fd,'w') as f:f.write(value+'\n')
            print('API credential saved outside repository; status verifies access.')
        elif a.command=='status':
            c=Seafile(a.server,a.library,token());items=c.directory();print(json.dumps({'authenticated':True,'library_access':True,'objects':len(items)}))
        elif a.command=='publish':publish(a)
        elif a.command=='probe':print(json.dumps(public_probe(a.url,a.sha256),indent=2))
        elif a.command=='pack':
            if not 1<=a.chunk_mib<=128:raise StorageError('chunk-mib must be1..128')
            pack(a)
        return 0
    except (StorageError,OSError,ValueError) as ex:print(str(ex),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
