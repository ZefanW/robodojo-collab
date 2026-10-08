#!/usr/bin/env python3
"""Select a real, SHA-bound official scene. No download or model inference."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from robodojo_collab.transport import safe_id
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--task',required=True);p.add_argument('--seed',type=int,choices=[0,1,2],required=True);p.add_argument('--layout',type=int,required=True);p.add_argument('--run-id',required=True);p.add_argument('--contributor',required=True);p.add_argument('--attempt',type=int,default=0);p.add_argument('--repeats-run-id');p.add_argument('--reason',default='original assigned scene');p.add_argument('--output',required=True);a=p.parse_args()
if a.attempt<0 or (a.attempt>0 and not a.repeats_run_id):p.error('Nonzero attempt requires --repeats-run-id; negative attempt is invalid')
catalog=json.loads((ROOT/'registry/scenes.json').read_text());scene=catalog[str(a.seed)][a.task][a.layout]
round_index=sum(max(len(v) for v in catalog[str(seed)].values()) for seed in range(a.seed))+a.layout
assert scene['layout_ordinal']==a.layout and a.layout>=0
contracts=json.loads((ROOT/'registry/prompt-contracts.json').read_text())['tasks'][a.task]
value={'package_version':'1.0','run_id':safe_id(a.run_id),'algorithm':{'algorithm_id':'astra-l3-persistent-cap20','version':'1.0','source_commit':'9ffacc54f372beef6479d61711bf4945e31ae4ce','model':'gpt-6-astra','reasoning_effort':'medium','codex_client_version':'0.153.4',**contracts},'protocol':{'id':'official-cap20-matched','version':'1','action_limit':20,'max_model_decisions':100},'scene':{'task':a.task,'official_seed':a.seed,'layout_ordinal':a.layout,'asset_path':scene['original_asset_path'],'asset_sha256':scene['layout_sha256'],'round_index':round_index},'attempt':{'index':a.attempt,'contributor_id':safe_id(a.contributor),'repeats_run_id':a.repeats_run_id,'reason':a.reason}}
from robodojo_collab.runner import work_id
value['work_id']=work_id(value)
with Path(a.output).open('x') as f:json.dump(value,f,indent=2);f.write('\n')
print('Created immutable task package; acquire an accepted assignment before execution.')
