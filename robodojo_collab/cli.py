"""Contribution CLI. Every default operation is offline and CPU-only."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import secrets
import sys
import tempfile
from .schema import canonical_bytes,file_sha256,load_manifest,privacy_findings,validate_manifest,validate_registered_scene,ValidationError
from .statistics import summarize
from . import claims


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=path.name+'.')
    try:
        with os.fdopen(fd,'wb') as f:f.write(canonical_bytes(value));f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def private_token_path(value,reading=False):
    from .storage import credential_destination,StorageError
    try:p=credential_destination(value)
    except StorageError as ex:raise ValidationError(str(ex)) from None
    if reading and p.stat().st_mode & 0o077:raise ValidationError('Claim token file must have mode 0600')
    return p


def registered_scene(m,registry_path=None):
    if m['protocol']['scope']=='synthetic-test-only':return
    path=Path(registry_path) if registry_path else Path(__file__).resolve().parents[1]/'registry/scenes.json'
    if not path.exists():raise ValidationError('Official scene inventory missing; supply --scenes registry/scenes.json')
    errors=validate_registered_scene(m,json.loads(path.read_text()))
    if errors:raise ValidationError('\n'.join(errors))


def import_bundle(bundle,store,scene_registry=None):
    """Copy only allowlisted, validated artifacts; immutable run_id publication."""
    bundle=Path(bundle).resolve();m=load_manifest(bundle);registered_scene(m,scene_registry);store=Path(store).resolve();store.mkdir(parents=True,exist_ok=True)
    target=store/m['run_id'];digest=hashlib.sha256(canonical_bytes(m)).hexdigest()
    lock=store/(m['run_id']+'.import-lock')
    try:lock.mkdir()
    except FileExistsError:raise ValidationError('Import currently locked; inspect interrupted importer before removing lock')
    tmp=None
    try:
        if target.exists():
            old=load_manifest(target)
            if canonical_bytes(old)!=canonical_bytes(m):raise ValidationError('run_id collision: refusing to overwrite existing attempt')
            return {'run_id':m['run_id'],'status':'already_present','manifest_sha256':digest}
        tmp=Path(tempfile.mkdtemp(prefix='.staging-',dir=store))
        for art in m['artifacts']:
            dst=tmp/art['path'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(bundle/art['path'],dst)
        (tmp/'manifest.json').write_bytes(canonical_bytes(m))
        load_manifest(tmp) # source changed during copying => fail before publication
        os.rename(tmp,target);tmp=None
        return {'run_id':m['run_id'],'status':'imported','manifest_sha256':digest,'artifact_count':len(m['artifacts'])}
    finally:
        if tmp and tmp.exists():shutil.rmtree(tmp)
        lock.rmdir()


def build_index(store,registry,output,manifests_only=False,storage_path=None,scene_registry=None):
    runs=[];store=Path(store)
    for p in sorted(store.glob('*/manifest.json')):
        if p.parent.name.startswith('.'):continue
        m=load_manifest(p,check_files=not manifests_only)
        registered_scene(m,scene_registry)
        m['score_percent']=m['outcome']['score']*100 if m['outcome']['score'] is not None else None
        runs.append(m)
    ids=[r['run_id'] for r in runs]
    if len(ids)!=len(set(ids)):raise ValidationError('duplicate run_id in index')
    task_registry=json.loads(Path(registry).read_text())
    if storage_path:
        receipts=json.loads(Path(storage_path).read_text())
        errors=privacy_findings(receipts)
        if errors:raise ValidationError('\n'.join(errors))
        locations=receipts.get('artifacts',{})
        for run in runs:
            for artifact in run['artifacts']:
                if artifact['sha256'] in locations:
                    artifact['storage']=locations[artifact['sha256']]
            errors=validate_manifest(run,check_files=False)
            if errors:raise ValidationError('\n'.join(errors))
    scenes_path=Path(scene_registry) if scene_registry else Path(__file__).resolve().parents[1]/'registry/scenes.json'
    scenes=json.loads(scenes_path.read_text()) if scenes_path.exists() else None
    index={'schema_version':'1.0','generated_at':datetime.now(timezone.utc).isoformat(),'runs':runs,'statistics':summarize(runs,task_registry,scenes),'task_registry':task_registry,
           'verification':{'files_checked':not manifests_only,'run_count':len(runs),'privacy_scan':'passed'}}
    errors=privacy_findings(index)
    if errors:raise ValidationError('\n'.join(errors))
    atomic_json(output,index);return {'output':str(output),'run_count':len(runs),'files_checked':not manifests_only}


def make_sample(destination):
    """An explicitly synthetic failed fixture, never a leaderboard completion."""
    dest=Path(destination)
    if dest.exists() and any(dest.iterdir()):raise ValidationError('sample destination must be empty')
    dest.mkdir(parents=True,exist_ok=True)
    record={'type':'public_fixture','message':'Synthetic offline fixture only. No simulator, model call, native terminal, video or score exists.'}
    data=canonical_bytes(record);(dest/'public-fixture.json').write_bytes(data)
    zero='0'*64
    m={'schema_version':'1.0','run_id':'offline-fixture-001','algorithm':{'algorithm_id':'offline-fixture','version':'1','source_commit':None,'prompt_sha256':zero,'tools_sha256':zero,'policy_sha256':zero,'model':'none-offline','reasoning_effort':'none','codex_client_version':'none'},
       'protocol':{'id':'offline-fixture','version':'1','scope':'synthetic-test-only','action_limit':20,'episode_control_limit':None,'selection_policy':'first-attempt'},
       'scene':{'task':'general_pickup','capability':'Open','variant':'standard','official_seed':0,'layout_ordinal':0,'asset_path':'fixture/not-an-official-layout.json','asset_sha256':zero,'round_index':0},
       'attempt':{'index':0,'contributor_id':'offline-tester','reason':'synthetic-validation-fixture','repeats_run_id':None},
       'environment':{'simulator_version':None,'machine_id':'offline-fixture','gpu':None,'driver':None,'os':None,'dependencies':{}},
       'status':'failed','timestamps':{'started_at':None,'finished_at':None},
       'outcome':{'native_result':False,'episode_complete':False,'score':None,'score_scale':'0..1','success':None,'control_steps':0,'model_decisions':0,'actual_responses':0,'unstable_envs':[],'evidence_consistent':False},
       'costs':{'attempts':[]},'artifacts':[{'path':'public-fixture.json','kind':'other','sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'media_type':'application/json'}],
       'audit':{'session_public_id':None,'export_policy':'allowlisted-public-v1','redactions':[],'limitations':['Synthetic fixture: all zero hashes are explicitly fictional and must not enter official result statistics. No paid model execution or simulation occurred.']}}
    (dest/'manifest.json').write_bytes(canonical_bytes(m));load_manifest(dest)
    return {'status':'created','run_id':m['run_id'],'synthetic':True}


def main(argv=None):
    parser=argparse.ArgumentParser(prog='robodojo-collab');sub=parser.add_subparsers(dest='command',required=True)
    val=sub.add_parser('validate');val.add_argument('bundle');val.add_argument('--manifest-only',action='store_true');val.add_argument('--scenes')
    imp=sub.add_parser('import');imp.add_argument('bundle');imp.add_argument('--store',required=True);imp.add_argument('--scenes')
    idx=sub.add_parser('index');idx.add_argument('--store',required=True);idx.add_argument('--registry',default='registry/tasks.json');idx.add_argument('--output',default='web/data/index.json');idx.add_argument('--manifest-only',action='store_true');idx.add_argument('--storage',help='Separate public storage receipts, keyed by artifact SHA256');idx.add_argument('--scenes')
    sample=sub.add_parser('sample');sample.add_argument('destination')
    gitclaim=sub.add_parser('git-claim');gcs=gitclaim.add_subparsers(dest='action',required=True)
    for action in ('acquire','inspect','renew','reconcile','bind','complete'):
        c=gcs.add_parser(action);c.add_argument('--remote',required=True);c.add_argument('--branch',default='work-claims');c.add_argument('--work-id',required=True)
        if action!='inspect':c.add_argument('--owner',required=True);c.add_argument('--token-file',required=True,help='Private token file; created once for acquire and retained on uncertain pushes')
        if action in ('acquire','renew','reconcile'):c.add_argument('--lease-seconds',type=int,default=3600)
        if action=='reconcile':c.add_argument('--evidence',required=True)
        if action in ('bind','complete'):c.add_argument('--run-id',required=True)
        if action=='bind':c.add_argument('--execution-instance-id')
    claim=sub.add_parser('claim');cs=claim.add_subparsers(dest='action',required=True)
    for action in ('acquire','renew','reconcile','bind','complete'):
        c=cs.add_parser(action);c.add_argument('--ledger',required=True);c.add_argument('--work-id',required=True);c.add_argument('--owner',required=True)
        if action!='acquire':c.add_argument('--token-file',required=True,help='Private file containing claim token; never commit it')
        if action in ('acquire','renew','reconcile'):c.add_argument('--lease-seconds',type=int,default=3600)
        if action=='acquire':c.add_argument('--token-output',required=True,help='New private token file, mode 0600')
        if action=='reconcile':c.add_argument('--evidence',required=True)
        if action in ('bind','complete'):c.add_argument('--run-id',required=True)
        if action=='bind':c.add_argument('--execution-instance-id')
    args=parser.parse_args(argv)
    try:
        if args.command=='validate':
            m=load_manifest(args.bundle,check_files=not args.manifest_only);registered_scene(m,args.scenes);result={'valid':True,'run_id':m['run_id'],'artifact_count':len(m['artifacts']),'files_checked':not args.manifest_only}
        elif args.command=='import':result=import_bundle(args.bundle,args.store,args.scenes)
        elif args.command=='index':result=build_index(args.store,args.registry,args.output,args.manifest_only,args.storage,args.scenes)
        elif args.command=='sample':result=make_sample(args.destination)
        elif args.command=='git-claim':
            token=None
            if args.action=='acquire':
                token=secrets.token_hex(24)
                token_path=private_token_path(args.token_file)
                fd=os.open(token_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
                with os.fdopen(fd,'w') as f:f.write(token+'\n');f.flush();os.fsync(f.fileno())
            elif args.action!='inspect':token=private_token_path(args.token_file,True).read_text().strip()
            result=claims.git_ledger(args.remote,args.branch,args.action,args.work_id,getattr(args,'owner',None),token,getattr(args,'lease_seconds',3600),getattr(args,'evidence',None),getattr(args,'run_id',None),getattr(args,'execution_instance_id',None))
        else:
            kw={'root':args.ledger,'work_id':args.work_id,'owner':args.owner}
            if args.action!='acquire':kw['token']=private_token_path(args.token_file,True).read_text().strip()
            if args.action in ('acquire','renew','reconcile'):kw['lease_seconds']=args.lease_seconds
            if args.action=='reconcile':kw['evidence_path']=args.evidence
            if args.action in ('bind','complete'):kw['run_id']=args.run_id
            if args.action=='bind':kw['execution_instance_id']=args.execution_instance_id
            if args.action=='acquire':
                token_path=private_token_path(args.token_output)
                if token_path.exists():raise ValidationError('Token output already exists')
                # Verify the destination can be created BEFORE permanently acquiring work.
                fd=os.open(token_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                try:
                    result=claims.acquire(**kw)
                    with os.fdopen(fd,'w') as f:f.write(result['token']+'\n')
                except BaseException:
                    try:os.close(fd)
                    except OSError:pass
                    token_path.unlink(missing_ok=True);raise
            else:result=getattr(claims,args.action)(**kw)
            result={k:v for k,v in result.items() if k!='token'}
        print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False));return 0
    except (ValidationError,claims.ClaimError,OSError,ValueError,TypeError,KeyError) as ex:
        print(json.dumps({'error':str(ex)},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
