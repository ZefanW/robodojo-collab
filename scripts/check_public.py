#!/usr/bin/env python3
"""Audit tracked public files and immutable result manifests, without networking.

The scanner reports locations/categories, never matched secret values. Tests and
scanner definitions have exact narrow fixtures below; these are not blanket
path exclusions. Ignored local staging is never traversed.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from robodojo_collab.schema import privacy_findings

PRIVATE_SEGMENTS={'.private','.local','private','staging','vendor','.venv','__pycache__','.ssh','.codex'}
PRIVATE_NAMES={'auth.json','credentials.json','credentials','cookies.json','cookies.txt','id_rsa','id_ed25519','seafile-token'}
BINARY_SUFFIXES={'.mp4','.webm','.mov','.avi','.mkv','.zip','.tar','.gz','.xz','.7z','.pt','.pth','.ckpt','.bin','.sqlite','.sqlite3','.db','.p12','.pfx','.pem','.key','.pyc'}
INTERNAL=re.compile(r'/(?:Users|home|root|cephfs|localssd)/|/nfs_[A-Za-z0-9_-]*/|[A-Za-z]:\\Users\\|\b10\.(?:\d{1,3}\.){2}\d{1,3}\b')
SECRETS=re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{20,}|\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}|\bBearer\s+[A-Za-z0-9._-]{12,}')
# Exact scanner declarations intentionally describe forbidden strings.
DECLARATIONS={
    'robodojo_collab/schema.py':('SECRET_RE = re.compile(', 'INTERNAL_PATH = re.compile('),
    'robodojo_collab/export_legacy.py':('INTERNAL = re.compile(',),
    'scripts/check_public.py':('INTERNAL=re.compile(', 'SECRETS=re.compile('),
}
# Deliberately fake regression inputs. A real added token elsewhere in tests fails.
FIXTURE_LINES={
    'tests/test_core.py':(
        "self.assertTrue(privacy_findings({'reasoning':'private','x':'/"+"Users/private/data','authorization':'Bearer '+'abcdefghijklmn'+'o'}))",
        "self.m['audit']['limitations']=['-----BEGIN "+"OPENSSH PRIVATE KEY-----']",
    ),
}
# Existing fixture uses a single literal; build it without embedding a scannable token.
FIXTURE_LINES['tests/test_core.py']=(
    "self.assertTrue(privacy_findings({'reasoning':'private','x':'/"+"Users/private/data','authorization':'Bea"+"rer abcdefghijklmno'}))",
    FIXTURE_LINES['tests/test_core.py'][1],
)
FIXTURE_LINES['tests/test_export.py']=(
    "x=public({'account_id':'private','safe':'abc','nested':{'reasoning':'hidden','path':'/"+"Users/person/private'},'list':[{'thread_id':'s','value':3}]})",
)

class PublicCheckError(ValueError):pass

def git(root,*args):
    p=subprocess.run(['git',*args],cwd=root,text=False,capture_output=True)
    if p.returncode:raise PublicCheckError('Git inspection failed; run from a repository with the requested base commit available')
    return p.stdout

def tracked_files(root):
    rows=git(root,'ls-files','--stage','-z').split(b'\0');result=[]
    for row in rows:
        if not row:continue
        meta,name=row.split(b'\t',1);mode,oid,stage=meta.decode().split(' ')
        path=name.decode('utf-8')
        if stage!='0':raise PublicCheckError('Unmerged Git index entries must be resolved before publishing')
        result.append((path,mode))
    return result

def allowed_fixture(path,line):
    stripped=line.strip()
    return any(stripped.startswith(prefix) for prefix in DECLARATIONS.get(path,())) or stripped in FIXTURE_LINES.get(path,())

def check_text(path,text):
    issues=[]
    for number,line in enumerate(text.splitlines(),1):
        if allowed_fixture(path,line):continue
        if SECRETS.search(line):issues.append(f'{path}:{number}: credential-shaped/private-key content')
        if INTERNAL.search(line):issues.append(f'{path}:{number}: private absolute path or internal IP')
    if path.endswith(('.json','.jsonl')):
        try:
            items=[json.loads(text)] if path.endswith('.json') else [json.loads(line) for line in text.splitlines() if line.strip()]
            for item in items:
                for finding in privacy_findings(item):issues.append(f'{path}: {finding}')
        except (UnicodeError,json.JSONDecodeError):issues.append(f'{path}: malformed public JSON')
    return issues

def immutable_findings(root,base,tracked):
    if not base:return []
    if not re.fullmatch(r'[A-Za-z0-9_./~^-]+',base) or base.startswith('-'):raise PublicCheckError('Unsafe base revision')
    revision=git(root,'rev-parse','--verify',base+'^{commit}').decode().strip()
    if not re.fullmatch('[0-9a-f]{40,64}',revision):raise PublicCheckError('Base must resolve to one commit')
    old=git(root,'ls-tree','-r','--name-only','-z',revision,'--','results').split(b'\0')
    issues=[];tracked=set(tracked)
    for raw in old:
        if not raw:continue
        name=raw.decode()
        if not name.endswith('/manifest.json'):continue
        path=Path(root)/name
        if name not in tracked or not path.is_file():issues.append(f'{name}: immutable published manifest removed/renamed');continue
        if git(root,'show',revision+':'+name)!=path.read_bytes():issues.append(f'{name}: immutable published manifest changed; add an explicit new attempt instead')
    return issues

def scan_repo(root,base=None):
    root=Path(root).resolve();tracked=tracked_files(root);issues=[]
    for name,mode in tracked:
        parts=Path(name).parts;p=root/name
        if mode in ('120000','160000') or p.is_symlink():issues.append(f'{name}: symlinks/submodules are not audited public files');continue
        if any(ord(c)<32 for c in name) or Path(name).is_absolute() or '..' in parts:issues.append('unsafe tracked filename');continue
        if set(parts)&PRIVATE_SEGMENTS or p.name in PRIVATE_NAMES or p.name.startswith('.env') or p.suffix.lower() in BINARY_SUFFIXES:
            issues.append(f'{name}: private/local/artifact filename must not be tracked');continue
        if not p.is_file():issues.append(f'{name}: tracked file missing from worktree');continue
        try:text=p.read_text(encoding='utf-8')
        except UnicodeError:issues.append(f'{name}: unreviewed binary belongs in artifact storage');continue
        issues.extend(check_text(name,text))
    issues.extend(immutable_findings(root,base,[p for p,_ in tracked]))
    return {'tracked_files':len(tracked),'base_checked':base is not None,'issues':sorted(set(issues))}

def event_base():
    if os.environ.get('GITHUB_EVENT_NAME') not in ('pull_request','pull_request_target'):return None
    path=os.environ.get('GITHUB_EVENT_PATH')
    if not path:raise PublicCheckError('Pull-request event lacks its base metadata')
    data=json.loads(Path(path).read_text());base=data.get('pull_request',{}).get('base',{}).get('sha')
    if not isinstance(base,str) or not re.fullmatch('[0-9a-f]{40,64}',base):raise PublicCheckError('Pull-request base SHA unavailable')
    return base

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',default=str(ROOT));p.add_argument('--base',help='Reject modifications/deletions of existing result manifests since this Git revision')
    a=p.parse_args(argv)
    try:
        result=scan_repo(a.root,a.base or event_base());print(json.dumps(result,indent=2));return 1 if result['issues'] else 0
    except (OSError,ValueError,PublicCheckError) as ex:print(json.dumps({'error':str(ex)}),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
