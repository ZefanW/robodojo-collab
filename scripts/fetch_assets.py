#!/usr/bin/env python3
"""Plan or resume a pinned asset download; no model calls, no checkpoints."""
import argparse,hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def matches(path,row):
 if not path.is_file() or path.stat().st_size!=row['size']:return False
 h=hashlib.sha256() if row['sha256'] else hashlib.sha1(b'blob '+str(row['size']).encode()+b'\0')
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()==(row['sha256'] or row['git_blob_sha1'])
def main():
 p=argparse.ArgumentParser();p.add_argument('--destination',required=True);p.add_argument('--download',action='store_true');p.add_argument('--accept-upstream-licenses',action='store_true');a=p.parse_args()
 lock=json.loads((ROOT/'registry/assets.lock.json').read_text());dest=Path(a.destination).expanduser().resolve();parent=dest
 while not parent.exists():parent=parent.parent
 remaining=[row for row in lock['files'] if not matches(dest/row['path'],row)];amount=sum(row['size'] for row in remaining);free=shutil.disk_usage(parent).free
 print(json.dumps({'repo':lock['repo_id'],'revision':lock['revision'],'files':len(lock['files']),'remaining_files':len(remaining),'remaining_bytes':amount,'space_required_bytes':amount*2+5*1024**3,'free_bytes':free,'download_requested':a.download}))
 if not a.download:return
 if not a.accept_upstream_licenses:raise RuntimeError('Review original upstream terms before accepting')
 if free<amount*2+5*1024**3:raise RuntimeError('Insufficient space including cache/temp allowance')
 from huggingface_hub import hf_hub_download
 dest.mkdir(parents=True,exist_ok=True)
 for row in remaining:
  # Standard client manages range-based resume and a local cache. Never replace a mismatched old artifact silently.
  target=dest/row['path']
  if target.exists():raise RuntimeError('Existing file digest differs; preserve and reconcile: '+row['path'])
  file=Path(hf_hub_download(repo_id=lock['repo_id'],repo_type='dataset',revision=lock['revision'],filename=row['path'],local_dir=dest))
  if not matches(file,row):raise RuntimeError('Downloaded digest mismatch: '+row['path'])
 print(json.dumps({'verified_files':len(lock['files']),'paid_model_calls':0}))
if __name__=='__main__':main()
