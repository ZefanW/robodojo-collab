#!/usr/bin/env python3
"""Apply recorded compatibility/audit sources to a contributor-owned clean checkout."""
import argparse,json,shutil,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from robodojo_collab.doctor import sha
from robodojo_collab.transport import atomic
ROOT=Path(__file__).resolve().parents[1]
REV='08b7ee46034c3d0c8a389b2b7bfc138f4d55ee4d'
def main():
 p=argparse.ArgumentParser();p.add_argument('--robodojo',required=True);p.add_argument('--roboprobe',required=True);p.add_argument('--family',choices=['Sim5.1','Sim6'],required=True);p.add_argument('--output-lock',required=True);a=p.parse_args()
 repo=Path(a.robodojo).resolve();probe=Path(a.roboprobe).resolve();runtime=ROOT/'scripts/runtime';family='sim51' if a.family=='Sim5.1' else 'sim6';src=runtime/'native'/family
 if subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()!=REV:raise RuntimeError('Pinned RoboDojo checkout required')
 if subprocess.check_output(['git','-C',str(repo),'status','--porcelain','--untracked-files=no'],text=True).strip():raise RuntimeError('Use a clean contributor-owned checkout; never patch a live tree')
 if subprocess.check_output(['git','-C',str(probe),'rev-parse','HEAD'],text=True).strip()!='9ffacc54f372beef6479d61711bf4945e31ae4ce':raise RuntimeError('Pinned RoboProbe required')
 patch=src/'compatibility.patch';subprocess.run(['git','-C',str(repo),'apply','--check',str(patch)],check=True)
 policy=probe/'policy/L3_PersistentCap20'
 if policy.exists():raise RuntimeError('Policy directory exists; verify it rather than overwrite')
 subprocess.run(['git','-C',str(repo),'apply',str(patch)],check=True)
 for name in ['main.py','eval_env.py']:shutil.copy2(src/name,repo/'src/eval_client'/name)
 for name in ['rollout_audit.py','case_comparability.py']:shutil.copy2(runtime/'native'/name,repo/'src/eval_client'/name)
 shutil.copytree(runtime/'policy',policy,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 # Runtime imports XPolicyLab from RoboProbe through PYTHONPATH; no existing submodule is replaced.
 files=['src/eval_client/main.py','src/eval_client/eval_env.py','src/eval_client/rollout_audit.py','src/eval_client/case_comparability.py','env/seed_manager/seed_manager.py','env/planner_manager/curobo_planner.py','utils/save_file.py','env_cfg/sim/sim_config.yml']
 atomic(Path(a.output_lock),{name:sha(repo/name) for name in files})
 print(json.dumps({'prepared':True,'paid_calls':0,'gpu_launches':0,'limitation':'Source preparation only. Dependency/renderer/physics compatibility remains unverified.'}))
if __name__=='__main__':main()
