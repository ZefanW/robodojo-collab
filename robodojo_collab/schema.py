"""Strict public-manifest validation and streaming file integrity checks.

Unknown measurements are null. Credential/private-session originals are never
accepted as public exports. Native result verification is an exporter duty;
this validator checks the declared evidence contract and every listed byte.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from datetime import datetime
from urllib.parse import urlsplit

CAPABILITIES = ('Generalization', 'Memory', 'Precision', 'Long-Horizon', 'Open')
STATUSES = ('queued', 'initializing', 'running', 'paused', 'failed', 'complete', 'invalid')
KINDS = ('native_result','episode_complete','trajectory','native_ack','public_session','public_timeline','original_image','native_video','public_demo','environment','source_lock','costs','other')
HEX = re.compile(r'^[0-9a-f]{64}$')
IDENT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,179}$')
PRIVATE_KEYS = {'token','access_token','refresh_token','id_token','authorization','cookie','cookies','sso_cookie','account_id','chatgpt_account_id','api_key','api_token','client_secret','password','passwd','private_key','encrypted_content','chain_of_thought','analysis','reasoning_content','reasoning'}
PRIVATE_KEY_COMPACT = {key.replace('_','') for key in PRIVATE_KEYS}
SECRET_RE = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:sk-[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,})|Bearer\s+[A-Za-z0-9._-]{12,}')
INTERNAL_PATH = re.compile(r'(?:/Users/|/home/|/root/|/cephfs/|/nfs_|/localssd/|[A-Za-z]:\\Users\\)')
SENSITIVE_NAME = re.compile(r'(^|/)(?:auth\.json|\.env(?:\.[^/]*)?|id_(?:rsa|ed25519)|cookies?\.(?:json|txt)|.*\.pem)$',re.I)

class ValidationError(ValueError):
    pass

def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)+'\n').encode()

def file_sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def safe_relative(value):
    return isinstance(value,str) and bool(value) and not any(ord(c)<32 for c in value) and not value.startswith(('/', '\\')) and '\\' not in value and ':' not in value and all(p not in ('..','.') for p in value.split('/')) and not any(p=='' for p in value.split('/'))

def privacy_findings(value, prefix='$'):
    issues=[]
    if isinstance(value,dict):
        for key,item in value.items():
            if key.lower().replace('-','').replace('_','') in PRIVATE_KEY_COMPACT:
                issues.append(f'{prefix}.{key}: private field prohibited')
            issues.extend(privacy_findings(item,f'{prefix}.{key}'))
    elif isinstance(value,list):
        for i,item in enumerate(value): issues.extend(privacy_findings(item,f'{prefix}[{i}]'))
    elif isinstance(value,str):
        if SECRET_RE.search(value): issues.append(f'{prefix}: credential-shaped content')
        if INTERNAL_PATH.search(value): issues.append(f'{prefix}: internal absolute path')
    return issues

def _integer(value, nullable=False):
    return (nullable and value is None) or (type(value) is int and value >= 0)

def _finite(value):
    return type(value) in (int,float) and math.isfinite(value)

def _timestamp(value):
    if value is None:return True
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).tzinfo is not None
    except (ValueError,TypeError,AttributeError):return False

def validate_manifest(m, bundle_dir=None, check_files=True):
    """Return all validation errors; a valid object returns []."""
    errors=[]
    def require(obj,fields,where):
        if not isinstance(obj,dict):errors.append(f'{where}: expected object');return {}
        for k in fields:
            if k not in obj:errors.append(f'{where}.{k}: missing')
        return obj
    m=require(m,('schema_version','run_id','algorithm','protocol','scene','attempt','environment','status','timestamps','outcome','costs','artifacts','audit'),'$')
    if m.get('schema_version')!='1.0':errors.append('schema_version: expected 1.0')
    if not isinstance(m.get('run_id'),str) or not IDENT.fullmatch(m.get('run_id','')):errors.append('run_id: unsafe identifier')
    a=require(m.get('algorithm'),('algorithm_id','version','source_commit','prompt_sha256','tools_sha256','policy_sha256','model','reasoning_effort','codex_client_version'),'algorithm')
    for k in ('algorithm_id','version','model','reasoning_effort','codex_client_version'):
        if not isinstance(a.get(k),str) or not a[k]:errors.append(f'algorithm.{k}: expected nonempty string')
    for k in ('prompt_sha256','tools_sha256','policy_sha256'):
        if a.get(k) is not None and (not isinstance(a[k],str) or not HEX.fullmatch(a[k])):errors.append(f'algorithm.{k}: expected SHA256 or null with limitation')
    if a.get('source_commit') is not None and not re.fullmatch(r'[0-9a-f]{40,64}',str(a['source_commit'])):errors.append('algorithm.source_commit: expected git hash or null')
    p=require(m.get('protocol'),('id','version','scope','action_limit','episode_control_limit','selection_policy'),'protocol')
    for k in ('id','version','scope','selection_policy'):
        if not isinstance(p.get(k),str) or not p[k]:errors.append(f'protocol.{k}: nonempty string required')
    for k in ('action_limit','episode_control_limit'):
        if not _integer(p.get(k),True):errors.append(f'protocol.{k}: nonnegative integer or null')
    s=require(m.get('scene'),('task','capability','variant','official_seed','layout_ordinal','asset_path','asset_sha256','round_index'),'scene')
    if s.get('capability') not in CAPABILITIES:errors.append('scene.capability: unknown capability')
    if s.get('variant') not in ('standard','random'):errors.append('scene.variant: standard or random required')
    if type(s.get('official_seed')) is not int or s['official_seed'] not in (0,1,2):errors.append('scene.official_seed: official asset directory must be 0, 1 or 2')
    for k in ('layout_ordinal','round_index'):
        if not _integer(s.get(k)):errors.append(f'scene.{k}: nonnegative integer required')
    if not safe_relative(s.get('asset_path')):errors.append('scene.asset_path: safe official relative path required')
    if not isinstance(s.get('asset_sha256'),str) or not HEX.fullmatch(s['asset_sha256']):errors.append('scene.asset_sha256: SHA256 required')
    attempt=require(m.get('attempt'),('index','contributor_id','reason','repeats_run_id'),'attempt')
    if not _integer(attempt.get('index')):errors.append('attempt.index: nonnegative integer required')
    if not isinstance(attempt.get('contributor_id'),str) or not IDENT.fullmatch(attempt.get('contributor_id','')):errors.append('attempt.contributor_id: public pseudonym required')
    if attempt.get('index',0)>0 and not attempt.get('repeats_run_id'):errors.append('attempt.repeats_run_id: required for repeated attempts')
    env=require(m.get('environment'),('simulator_version','machine_id','gpu','driver','os','dependencies'),'environment')
    if not isinstance(env.get('dependencies'),dict):errors.append('environment.dependencies: object required')
    if m.get('status') not in STATUSES:errors.append('status: invalid')
    if p.get('scope')=='synthetic-test-only' and m.get('status')=='complete':errors.append('synthetic fixture must not claim a native completed result')
    times=require(m.get('timestamps'),('started_at','finished_at'),'timestamps')
    for k,v in times.items():
        if k in ('started_at','finished_at') and not _timestamp(v):errors.append(f'timestamps.{k}: timezone-qualified ISO8601 or null')
    if times.get('started_at') and times.get('finished_at') and _timestamp(times['started_at']) and _timestamp(times['finished_at']):
        if datetime.fromisoformat(times['finished_at'].replace('Z','+00:00')) < datetime.fromisoformat(times['started_at'].replace('Z','+00:00')):errors.append('timestamps: finish precedes start')
    o=require(m.get('outcome'),('native_result','episode_complete','score','score_scale','success','control_steps','model_decisions','actual_responses','unstable_envs','evidence_consistent'),'outcome')
    if o.get('score_scale')!='0..1':errors.append('outcome.score_scale: expected 0..1')
    if o.get('score') is not None and (not _finite(o['score']) or not 0<=o['score']<=1):errors.append('outcome.score: expected normalized 0..1 or null')
    if o.get('success') is not None and type(o['success']) is not bool:errors.append('outcome.success: boolean or null')
    for k in ('control_steps','model_decisions','actual_responses'):
        if not _integer(o.get(k),True):errors.append(f'outcome.{k}: nonnegative integer or null')
    if not isinstance(o.get('unstable_envs'),list):errors.append('outcome.unstable_envs: list required')
    if m.get('status')=='complete':
        if not all(o.get(k) is True for k in ('native_result','episode_complete','evidence_consistent')):errors.append('complete: requires matched native result, episode_complete and evidence')
        if o.get('unstable_envs') or o.get('score') is None or o.get('success') is None or o.get('control_steps') is None:errors.append('complete: missing valid native terminal measurements')
    costs=require(m.get('costs'),('attempts',),'costs'); ca=costs.get('attempts',[])
    if not isinstance(ca,list):errors.append('costs.attempts: array required');ca=[]
    seen=set()
    for i,c in enumerate(ca):
        c=require(c,('attempt_id','input_tokens','cached_input_tokens','output_tokens','model_responses','paid_requests','usage_known'),f'costs.attempts[{i}]')
        cid=c.get('attempt_id')
        if not isinstance(cid,str) or not cid or cid in seen:errors.append('costs: missing/duplicate attempt_id')
        seen.add(cid)
        for k in ('input_tokens','cached_input_tokens','output_tokens','model_responses','paid_requests'):
            if not _integer(c.get(k),True):errors.append(f'costs.{i}.{k}: integer or null')
        if type(c.get('usage_known')) is not bool:errors.append(f'costs.{i}.usage_known: boolean required')
        if c.get('usage_known') and any(c.get(k) is None for k in ('input_tokens','cached_input_tokens','output_tokens')):errors.append('costs: usage_known conflicts with null usage')
        if c.get('input_tokens') is not None and c.get('cached_input_tokens') is not None and c['cached_input_tokens']>c['input_tokens']:errors.append('costs: cache must be a subset of input')
    audit=require(m.get('audit'),('session_public_id','export_policy','redactions','limitations'),'audit')
    if not isinstance(audit.get('limitations'),list):errors.append('audit.limitations: array required')
    unknowns=[f'algorithm.{k}' for k in ('source_commit','prompt_sha256','tools_sha256','policy_sha256') if a.get(k) is None]
    unknowns += [f'environment.{k}' for k in ('simulator_version','machine_id','gpu','driver','os') if env.get(k) is None]
    if unknowns and not audit.get('limitations'):errors.append('audit.limitations: document unknown fields '+', '.join(unknowns))
    arts=m.get('artifacts',[])
    if not isinstance(arts,list):errors.append('artifacts: array required');arts=[]
    paths=set();kinds=set();views=set();evidence={}
    for i,art in enumerate(arts):
        art=require(art,('path','kind','sha256','bytes','media_type'),f'artifacts[{i}]')
        path=art.get('path');kind=art.get('kind');kinds.add(kind)
        if not safe_relative(path) or path in paths:errors.append(f'artifacts[{i}].path: unsafe/duplicate');continue
        paths.add(path)
        if SENSITIVE_NAME.search(path):errors.append(f'artifacts[{i}].path: sensitive filename')
        if kind not in KINDS:errors.append(f'artifacts[{i}].kind: invalid')
        if not isinstance(art.get('sha256'),str) or not HEX.fullmatch(art['sha256']):errors.append(f'artifacts[{i}].sha256: SHA256 required')
        if not _integer(art.get('bytes')):errors.append(f'artifacts[{i}].bytes: integer required')
        if kind=='native_video':views.add(art.get('view'))
        storage=art.get('storage') or {}
        for key in ('landing_url','download_url','playback_url'):
            url=storage.get(key)
            if url is not None:
                parsed=urlsplit(url)
                if parsed.scheme!='https' or parsed.username or parsed.password:errors.append(f'artifact storage {key}: public HTTPS URL required')
        if bundle_dir is not None and check_files:
            root=Path(bundle_dir).resolve();target=root/path
            if target.is_symlink() or not target.resolve().is_relative_to(root):errors.append(f'{path}: symlink/escape prohibited');continue
            if not target.is_file():errors.append(f'{path}: missing file');continue
            if target.stat().st_size!=art.get('bytes'):errors.append(f'{path}: size mismatch')
            if file_sha256(target)!=art.get('sha256'):errors.append(f'{path}: SHA256 mismatch')
            if art.get('media_type','').startswith(('text/','application/json')) or target.suffix.lower() in ('.json','.jsonl','.txt','.html','.md','.csv'):
                try:
                    raw=target.read_text(); errors.extend(privacy_findings(raw,path))
                    if target.suffix=='.json':
                        parsed_data=json.loads(raw)
                        errors.extend(privacy_findings(parsed_data,path))
                        if kind in ('native_result','episode_complete','native_ack'):evidence[kind]=parsed_data
                    elif target.suffix=='.jsonl':
                        for n,line in enumerate(raw.splitlines()):
                            if line.strip():errors.extend(privacy_findings(json.loads(line),f'{path}:{n+1}'))
                except (UnicodeError,json.JSONDecodeError) as ex:errors.append(f'{path}: invalid public text/JSON: {type(ex).__name__}')
    if m.get('status')=='complete':
        required={'native_result','episode_complete','trajectory','native_ack','public_session','public_demo'}
        if required-kinds:errors.append('complete: missing artifacts '+', '.join(sorted(required-kinds)))
        if len(views-{None})<3:errors.append('complete: three distinct native video views required')
        if not ca:errors.append('complete: all-attempt cost accounting required, unknown attempts must remain null')
        if bundle_dir is not None and check_files:
            nr=evidence.get('native_result');ep=evidence.get('episode_complete');acks=evidence.get('native_ack')
            if not isinstance(nr,dict) or not isinstance(ep,dict):
                errors.append('complete: native result and episode_complete must be readable JSON objects')
            else:
                if ep.get('kind')!='episode_complete':errors.append('native evidence: wrong terminal event kind')
                if ep.get('native_results')!=nr:errors.append('native evidence: result differs from episode_complete')
                if ep.get('control_steps')!=[o.get('control_steps')]:errors.append('native evidence: terminal control count differs')
                if ep.get('unstable_envs')!=[]:errors.append('native evidence: unstable environments are present or unknown')
                details=nr.get('details',{});item=details.get('0',{}) if isinstance(details,dict) else {}
                if item.get('score')!=o.get('score') or item.get('success') is not o.get('success'):
                    errors.append('native evidence: score/success differs from manifest')
            if not isinstance(acks,list) or not acks:
                errors.append('complete: native_ack must be a nonempty JSON list')
            else:
                terminal=[ack for ack in acks if isinstance(ack,dict) and ack.get('kind')=='episode_complete']
                if not terminal or terminal[-1].get('control_steps')!=[o.get('control_steps')]:
                    errors.append('native evidence: final ACK does not match terminal controls')
                if terminal and terminal[-1].get('native_results')!=nr:
                    errors.append('native evidence: final ACK result differs')
    errors.extend(privacy_findings(m))
    return sorted(set(errors))

def load_manifest(path, check_files=True):
    path=Path(path); path=path/'manifest.json' if path.is_dir() else path
    m=json.loads(path.read_text());errors=validate_manifest(m,path.parent,check_files)
    if errors:raise ValidationError('\n'.join(errors))
    return m


def validate_registered_scene(m,registry):
    """Require the actual immutable inventory; hash-shaped strings are not evidence."""
    if m['protocol']['scope']=='synthetic-test-only':
        if m['status']=='complete':return ['synthetic fixture must not claim a native completed result']
        return []
    s=m['scene'];entries=registry.get(str(s['official_seed']),{}).get(s['task'],[])
    matches=[e for e in entries if e['layout_ordinal']==s['layout_ordinal']]
    if len(matches)!=1:return ['scene: no unique official inventory entry for seed/task/layout']
    actual=matches[0];errors=[]
    if actual['layout_sha256']!=s['asset_sha256']:errors.append('scene: asset SHA differs from registered official layout')
    if actual['original_asset_path']!=s['asset_path']:errors.append('scene: original asset path differs from registered official layout')
    return errors
