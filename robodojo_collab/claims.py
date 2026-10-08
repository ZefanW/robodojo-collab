"""Small shared-filesystem claim ledger. Expiration NEVER authorizes paid takeover.

Use one agreed ledger (shared POSIX disk or one maintainer checkout). Independent
clones have independent locks. Git merges do not provide distributed locking.
"""
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import re
import subprocess
import tempfile
import time
from .schema import canonical_bytes, privacy_findings, IDENT

class ClaimError(ValueError):pass

def utc():return datetime.now(timezone.utc).isoformat()
def _path(root,work_id):return Path(root)/hashlib.sha256(work_id.encode()).hexdigest()

@contextmanager
def locked(root,work_id):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);lock=root/(hashlib.sha256(work_id.encode()).hexdigest()+'.lock')
    try:lock.mkdir()
    except FileExistsError:raise ClaimError('Concurrent ledger operation or interrupted lock; reconcile manually, do not start paid work')
    try:yield _path(root,work_id)
    finally:lock.rmdir()

def _write(path,data):
    tmp=path.with_name(path.name+'.'+secrets.token_hex(8)+'.tmp')
    try:
        with tmp.open('xb') as f:f.write(canonical_bytes(data));f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()

def acquire(root,work_id,owner,lease_seconds=3600):
    if not owner or not work_id or not 0<lease_seconds<=86400:raise ClaimError('owner/work_id and lease 1..86400 seconds required')
    if not IDENT.fullmatch(owner) or privacy_findings({'work_id':work_id,'owner':owner}):raise ClaimError('Public work identity/pseudonym failed privacy validation')
    with locked(root,work_id) as path:
        if path.exists():
            prior=json.loads(path.read_text())
            raise ClaimError('Claim already exists'+(' and lease expired; original scene/session/paid receipts must be reconciled explicitly' if prior['expires_unix']<time.time() else '')+'; never auto takeover')
        now=time.time();data={'schema_version':'1.0','work_id':work_id,'owner':owner,'token':secrets.token_hex(24),'status':'claimed','created_at':utc(),'updated_at':utc(),'expires_unix':now+lease_seconds,'history':[]}
        public={k:v for k,v in data.items() if k!='token'}
        public['token_sha256']=hashlib.sha256(data['token'].encode()).hexdigest()
        _write(path,public);return data

def _owned(path,owner,token):
    if not path.exists():raise ClaimError('Unknown claim')
    d=json.loads(path.read_text())
    expected=d.get('token_sha256')
    token_ok=secrets.compare_digest(expected,hashlib.sha256(token.encode()).hexdigest()) if expected else secrets.compare_digest(d.get('token',''),token)
    if d['owner']!=owner or not token_ok:raise ClaimError('Owner/token mismatch')
    return d

def renew(root,work_id,owner,token,lease_seconds=3600):
    if not 0<lease_seconds<=86400:raise ClaimError('lease 1..86400 seconds required')
    with locked(root,work_id) as path:
        d=_owned(path,owner,token)
        if d['status']!='claimed' or d['expires_unix']<time.time():raise ClaimError('Expired or closed claim requires explicit reconciliation before renewal')
        d.update(updated_at=utc(),expires_unix=time.time()+lease_seconds);_write(path,d);return d

def reconcile(root,work_id,owner,token,evidence_path,lease_seconds=3600):
    """Only the original owner can continue; evidence records actual paid boundary."""
    if not 0<lease_seconds<=86400:raise ClaimError('lease 1..86400 seconds required')
    evidence=json.loads(Path(evidence_path).read_text())
    required=('work_id','original_session_preserved','native_state_verified','paid_receipts_reconciled','no_unknown_delivery','account_allowance_verified','next_boundary','reviewed_at')
    if any(k not in evidence for k in required) or evidence['work_id']!=work_id:raise ClaimError('Incomplete reconciliation record')
    for k in required[1:6]:
        if evidence[k] is not True:raise ClaimError(k+' must be true; preserve scene and stop')
    if type(evidence['next_boundary']) is not int or evidence['next_boundary']<0:raise ClaimError('next_boundary must be a known nonnegative integer')
    public_evidence={k:evidence[k] for k in required}
    if privacy_findings(public_evidence):raise ClaimError('Reconciliation evidence contains private fields or paths')
    with locked(root,work_id) as path:
        d=_owned(path,owner,token)
        if d['status']=='complete':raise ClaimError('Complete claim cannot resume')
        d['history'].append({'event':'reconciled','at':utc(),'evidence_sha256':hashlib.sha256(canonical_bytes(public_evidence)).hexdigest(),'evidence':public_evidence})
        d.update(status='claimed',updated_at=utc(),expires_unix=time.time()+lease_seconds);_write(path,d);return d

def complete(root,work_id,owner,token,run_id):
    with locked(root,work_id) as path:
        d=_owned(path,owner,token)
        if d.get('run_id') and d['run_id']!=run_id:raise ClaimError('A different run already completed this claim')
        d.update(status='complete',run_id=run_id,updated_at=utc());_write(path,d);return d


def bind(root,work_id,owner,token,run_id,execution_instance_id=None):
    """Bind a reservation to one immutable run before any paid launch."""
    if not run_id:raise ClaimError('run_id required')
    if execution_instance_id is not None and (not isinstance(execution_instance_id,str) or not re.fullmatch('[0-9a-f]{64}',execution_instance_id)):raise ClaimError('execution_instance_id must be SHA256')
    with locked(root,work_id) as path:
        d=_owned(path,owner,token)
        if d['status']!='claimed' or d['expires_unix']<time.time():raise ClaimError('Only a current claimed reservation may bind a run')
        if d.get('run_id') and d['run_id']!=run_id:raise ClaimError('Claim is already bound to another immutable run_id')
        if d.get('execution_instance_id') and d['execution_instance_id']!=execution_instance_id:raise ClaimError('Claim is bound to a different native execution instance; preserve original scene and reconcile migration explicitly')
        if d.get('run_id')==run_id and d.get('execution_instance_id')==execution_instance_id:return d
        if execution_instance_id is not None:d['execution_instance_id']=execution_instance_id
        d.update(run_id=run_id,updated_at=utc());_write(path,d);return d


def _git(cwd,*args):
    """Never invoke a shell or print credential-bearing remote URLs/errors."""
    env=os.environ.copy();env['GIT_TERMINAL_PROMPT']='0'
    try:
        result=subprocess.run(['git',*args],cwd=cwd,env=env,text=True,capture_output=True,timeout=120)
    except (OSError,subprocess.TimeoutExpired):
        raise ClaimError('Git operation unavailable or timed out. Keep the private token and inspect the remote ledger before retrying.') from None
    if result.returncode:
        raise ClaimError('Git operation failed (authentication, missing branch, or concurrent update). Do not start paid work; keep the token and inspect remote claim state.')
    return result.stdout.strip()


def git_ledger(remote,branch,action,work_id,owner=None,token=None,lease_seconds=3600,evidence_path=None,run_id=None,execution_instance_id=None):
    """Compare-and-swap through a protected dedicated Git branch, without force push.

    The branch must already exist. Every mutation commits on the fetched tip and
    a normal push atomically rejects a stale parent. Git permissions are the
    authority; public owner pseudonyms alone do not authenticate a contributor.
    """
    if action not in ('acquire','inspect','renew','reconcile','bind','complete'):raise ClaimError('Unknown Git ledger action')
    if not remote or not branch or branch.startswith('-') or any(x in branch for x in ('..','~','^',':',' ','\\')):raise ClaimError('Invalid remote/branch')
    if action!='inspect' and (not owner or not token):raise ClaimError('Owner and pre-saved private claim token are required')
    if action!='inspect' and (not IDENT.fullmatch(owner) or privacy_findings({'work_id':work_id,'owner':owner})):raise ClaimError('Public work identity/pseudonym failed privacy validation')
    # Remote references belong only in local configuration, never public manifests.
    with tempfile.TemporaryDirectory(prefix='robodojo-claims-') as directory:
        base=Path(directory);checkout=base/'ledger'
        _git(base,'clone','--quiet','--single-branch','--branch',branch,'--',remote,str(checkout))
        ledger=checkout/'claims';path=_path(ledger,work_id)
        before=path.read_bytes() if path.exists() else None
        if action=='inspect':
            return json.loads(path.read_text()) if path.exists() else {'work_id':work_id,'status':'unclaimed'}
        if action=='acquire':
            if path.exists():raise ClaimError('Work already claimed, including if expired. Reconcile original owner/session instead of creating a duplicate paid attempt.')
            if not 0<lease_seconds<=86400:raise ClaimError('lease 1..86400 seconds required')
            data={'schema_version':'1.0','work_id':work_id,'owner':owner,'token_sha256':hashlib.sha256(token.encode()).hexdigest(),'status':'claimed','created_at':utc(),'updated_at':utc(),'expires_unix':time.time()+lease_seconds,'history':[]}
            ledger.mkdir(exist_ok=True);_write(path,data)
        elif action=='renew':data=renew(ledger,work_id,owner,token,lease_seconds)
        elif action=='reconcile':data=reconcile(ledger,work_id,owner,token,evidence_path,lease_seconds)
        elif action=='bind':data=bind(ledger,work_id,owner,token,run_id,execution_instance_id)
        else:data=complete(ledger,work_id,owner,token,run_id)
        if before is not None and path.read_bytes()==before:
            return {**data,'ledger_commit':_git(checkout,'rev-parse','HEAD'),'remote_readback_verified':True,'unchanged':True}
        _git(checkout,'config','user.name','RoboDojo contributor')
        _git(checkout,'config','user.email','robodojo-contributor@users.noreply.github.com')
        relative=path.relative_to(checkout).as_posix()
        _git(checkout,'add','--',relative)
        _git(checkout,'commit','--quiet','-m','Record '+action+' for work '+hashlib.sha256(work_id.encode()).hexdigest()[:16])
        commit=_git(checkout,'rev-parse','HEAD')
        _git(checkout,'push','--quiet','origin','HEAD:refs/heads/'+branch)
        _git(checkout,'fetch','--quiet','origin',branch)
        _git(checkout,'merge-base','--is-ancestor',commit,'FETCH_HEAD')
        observed=json.loads(_git(checkout,'show','FETCH_HEAD:'+relative))
        if observed.get('owner')!=owner or observed.get('token_sha256')!=hashlib.sha256(token.encode()).hexdigest():
            raise ClaimError('Remote read-back differs from submitted ownership; do not start paid work')
        return {**observed,'ledger_commit':commit,'remote_readback_verified':True}
