"""Export a completed portable runner collection; no network or model calls."""
from __future__ import annotations
import argparse, base64, hashlib, html, json, mimetypes, re, shutil
from pathlib import Path
from .export_legacy import canonical, digest, read, write, public, take, iso, sha_file, cost_attempts, deterministic_tar
from .schema import load_manifest, safe_relative
ROOT=Path(__file__).resolve().parents[1]


def verify_collection(root, run_id):
    root=Path(root)
    proof=read(root/'collection-proof.json')
    if proof.get('run_id')!=run_id or proof.get('verified') is not True:
        raise ValueError('Collection has no verified matching identity')
    files=proof.get('files',{})
    if not files:raise ValueError('Collection manifest has no file checksums')
    names=set()
    for record in files:
        name=record['path']
        if name in names:raise ValueError('Duplicate collection path')
        names.add(name)
        if not safe_relative(name):raise ValueError('Unsafe collection path')
        path=root/name; expected=record['sha256']
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or path.stat().st_size!=record['size'] or sha_file(path)!=expected:
            raise ValueError('Collected native bytes changed: '+name)
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='collection-proof.json'}
    if actual!=names:raise ValueError('Collection includes unverified or missing files')
    return proof


def demo_html(timeline):
    data=json.dumps(timeline,ensure_ascii=False).replace('<','\\u003c')
    return '''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>RoboDojo public demonstration</title>
<style>body{font:16px system-ui;margin:2rem;background:#0e1523;color:#eef3ff}.views{display:flex;gap:1rem;flex-wrap:wrap}video{width:31%;min-width:240px}button{padding:.6rem}#note{white-space:pre-wrap;line-height:1.6;margin:1rem 0}</style>
<h1>Original three-view demonstration</h1><p>Original PUBLIC note and tool feedback. No private model reasoning. Use the head video to play or seek all views together.</p>
<div class="views"><video id="head" controls src="../videos/head.mp4"></video><video id="left" controls src="../videos/left_wrist.mp4"></video><video id="right" controls src="../videos/right_wrist.mp4"></video></div><p id="note"></p><ol id="timeline"></ol>
<script>const rows='''+data+''';const head=document.querySelector('#head'),others=[document.querySelector('#left'),document.querySelector('#right')];
for(const ev of ['play','pause','seeked'])head.addEventListener(ev,()=>{for(const v of others){if(Math.abs(v.currentTime-head.currentTime)>.12)v.currentTime=head.currentTime;if(ev==='play')v.play().catch(()=>{});else if(ev==='pause')v.pause()}});
const end=Math.max(1,...rows.map(r=>r.cameras?.head?.end||0));function seek(r){const frame=r.cameras?.head?.start||0;if(head.duration)head.currentTime=head.duration*frame/end}
rows.forEach(r=>{const li=document.createElement('li'),b=document.createElement('button');b.textContent='Control '+r.control_start+' · '+(r.tool||'');b.onclick=()=>seek(r);li.append(b,document.createTextNode(' '+(r.public_note||'[No public note supplied]')));document.querySelector('#timeline').append(li)});
head.addEventListener('timeupdate',()=>{const frame=head.duration?head.currentTime/head.duration*end:0;const row=[...rows].reverse().find(r=>(r.cameras?.head?.start||0)<=frame);document.querySelector('#note').textContent=row?(row.public_note||'[No public note supplied]')+'\\n'+(row.feedback||''):''});</script>'''


def export_portable(controller, native, destination, package=None):
    controller,native,destination=map(lambda p:Path(p).resolve(),(controller,native,destination))
    pkg=read(package or controller/'package.json');run=pkg['run_id']
    if read(controller/'package.json')!=pkg:raise ValueError('Controller package mismatch')
    if any(destination==x or x in destination.parents for x in (controller,native)):
        raise ValueError('Public destination must be outside private input trees')
    proof=verify_collection(native,run)
    info=read(native/'run/native.json')
    if info.get('run_id')!=run or info.get('package_sha256')!=digest(canonical(pkg)):
        raise ValueError('Native scene package mismatch')
    result=read(native/'native/_result.json')
    events=[json.loads(line) for line in (native/'native/audit/events.jsonl').read_text().splitlines() if line.strip()]
    terminals=[e for e in events if e.get('kind')=='episode_complete']
    if len(terminals)!=1:raise ValueError('One actual native episode terminal is required')
    terminal=terminals[0]
    if terminal.get('unstable_envs')!=[] or terminal.get('native_results')!=result:raise ValueError('Native terminal/result mismatch')
    outcome=result['details']['0'];controls=terminal['control_steps'][0]
    if outcome['layout_id']!=pkg['scene']['layout_ordinal']:raise ValueError('Terminal layout mismatch')
    traces=list((native/'run/trace').rglob('l3_inspect_transcript.json'))
    if len(traces)!=1:raise ValueError('Expected exactly one original completed native transcript')
    trace=read(traces[0])
    if trace.get('in_progress') is not False or trace.get('run_id')!=run:raise ValueError('Unfinished/mismatched native trace')
    bundle=destination/run;bundle.mkdir(parents=True,exist_ok=True);arts=[];source_hashes={}
    def observe(path):
        path=Path(path);value=sha_file(path);source_hashes[path]=value;return value
    observe(controller/'package.json')
    def register(rel,kind,view=None):
        p=bundle/rel;item={'path':rel,'kind':kind,'sha256':sha_file(p),'bytes':p.stat().st_size,'media_type':mimetypes.guess_type(rel)[0] or 'application/octet-stream'}
        if view:item['view']=view
        arts.append(item)
    def put(rel,data,kind):write(bundle/rel,public(data));register(rel,kind)
    def copy(src,rel,kind,view=None):
        expected=observe(src);target=bundle/rel;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and sha_file(target)!=expected:raise ValueError('Conflicting export artifact')
        if not target.exists():shutil.copyfile(src,target)
        if sha_file(target)!=expected:raise ValueError('Copy SHA mismatch')
        register(rel,kind,view)
    put('evidence/native-result.json',result,'native_result');put('evidence/episode-complete.json',terminal,'episode_complete')
    keys=('kind','time_unix','layout_by_env','control_steps','elapsed_s','native_end','native_success','native_results','unstable_envs','actions','action')
    put('evidence/native-acks.json',[take(e,keys) for e in events if e.get('kind') in {'action_complete','action_submit','episode_complete'}],'native_ack')
    turns=[];timeline=[]
    for turn in trace['turns']:
        t=take(turn,('policy_step','observation','decision','execution'));t['calls']=[]
        for c in turn.get('llm_calls',[]):
            t['calls'].append(take(c,('call_index','repair_attempt','latency_s','model','accepted','tool','arguments','validation_error','tool_result')))
            args=c.get('arguments',{})
            timeline.append({'policy_step':turn.get('policy_step'),'control_start':turn.get('observation',{}).get('env_step'),'control_end':turn.get('execution',{}).get('env_step_end'),'tool':c.get('tool'),'arguments':public(args),'public_note':public(args.get('note',args.get('reason'))),'feedback':public(c.get('tool_result')),'accepted':c.get('accepted'),'cameras':turn.get('execution',{}).get('cameras',{})})
        turns.append(t)
    put('evidence/trajectory.json',{'run_id':run,'instruction':trace.get('instruction'),'turns':turns},'trajectory')
    put('evidence/public-timeline.json',timeline,'public_timeline')
    history=controller/'session/permanent-history';inputs=[];images=set()
    for p in sorted(history.glob('input-*.json')):
        original=read(p);messages=[];observe(p)
        for m in original.get('new_messages',[]):
            if m.get('role') not in {'system','user','tool'}:continue
            content=m.get('content')
            if isinstance(content,list):
                output=[]
                for c in content:
                    if c.get('type')=='text':output.append({'type':'text','text':public(c.get('text',''))})
                    elif c.get('type')=='image_url':
                        url=c.get('image_url',{}).get('url')
                        if not isinstance(url,str) or not url.startswith('data:image/'):raise ValueError('Original image unavailable')
                        header,b64=url.split(',',1);raw=base64.b64decode(b64,validate=True)
                        ext='jpg' if 'jpeg' in header else 'png' if 'png' in header else None
                        if ext is None:raise ValueError('Unsupported original image type')
                        rel='images/'+digest(raw)+'.'+ext;pout=bundle/rel;pout.parent.mkdir(exist_ok=True)
                        if pout.exists() and pout.read_bytes()!=raw:raise ValueError('Conflicting original image')
                        pout.write_bytes(raw)
                        if rel not in images:register(rel,'original_image');images.add(rel)
                        output.append({'type':'image','path':rel,'data_url_sha256':digest(url.encode())})
                content=output
            messages.append({'role':m['role'],'content':public(content)})
        inputs.append({'index':original['index'],'messages':messages,'source_input_sha256':observe(p)})
    if not images:raise ValueError('No original observation images')
    request=read(controller/'calls/0000/request.json');observe(controller/'calls/0000/request.json')
    systems=[m['content'] for m in request['messages'] if m.get('role')=='system']
    if digest('\n\n'.join(systems).encode())!=pkg['algorithm']['prompt_sha256'] or digest(json.dumps(request['tools'],sort_keys=True).encode())!=pkg['algorithm']['tools_sha256']:
        raise ValueError('Actual prompt/tools differ from frozen package')
    put('evidence/public-session.json',{'export_policy':'public-input-tools-feedback-v1','inputs':inputs,'tool_calls':timeline,'tools':request['tools']},'public_session')
    for p in (controller/'calls').rglob('*'):
        if p.is_file() and p.name in {'paid-start.json','usage.json','response.json','accounting.json','raw-response-receipts.json','journal-response-receipts.json'}:observe(p)
    attempts=cost_attempts(controller/'calls');put('evidence/costs.json',{'attempts':attempts,'cache_is_input_subset':True},'costs')
    for view in ('head','left_wrist','right_wrist'):
        videos=list((native/'native').glob('episode_*_cam_'+view+'_*.mp4'))
        if len(videos)!=1:raise ValueError('Missing/ambiguous original native camera')
        copy(videos[0],'videos/'+view+'.mp4','native_video',view)
    demo=bundle/'demo/index.html';demo.parent.mkdir(exist_ok=True);body=demo_html(timeline).encode()
    if demo.exists() and demo.read_bytes()!=body:raise ValueError('Conflicting public demo')
    demo.write_bytes(body);register('demo/index.html','public_demo')
    environment=info.get('public_environment')
    if not environment:raise ValueError('Native launch must record public_environment before exporting')
    put('evidence/environment.json',environment,'environment')
    lock_sha=info.get('source_lock_sha256')
    if not lock_sha or not info.get('policy_sha256'):raise ValueError('Launch-time source/policy identity is missing')
    put('evidence/source-lock.json',{'registry_source_lock_sha256':lock_sha,'native_source_sha256':info['native_source_sha256'],'algorithm':pkg['algorithm'],'package_sha256':info['package_sha256']},'source_lock')
    task_registry=read(ROOT/'registry/tasks.json');tasks=task_registry.get('tasks',task_registry) if isinstance(task_registry,dict) else task_registry
    task=next(x for x in tasks if x['task']==pkg['scene']['task']) if isinstance(tasks,list) else tasks[pkg['scene']['task']]
    scene={**pkg['scene'],'capability':task['capability'],'variant':task.get('variant','random' if pkg['scene']['task'].endswith('_random') else 'standard'),'round_index':pkg['scene'].get('round_index',pkg['scene']['layout_ordinal'])}
    budget=re.search(r'Env steps remaining before the episode ends: (\d+)',json.dumps(inputs[0]['messages']))
    algorithm={**pkg['algorithm'],'source_commit':pkg['algorithm'].get('source_commit'), 'policy_sha256':info['policy_sha256']}
    limitations=['Public demo uses only original visible tool notes; no private model reasoning is exported.','Scene assets/checkpoints remain external and are identified by SHA.','Video timeline seeks scale native camera frame indices to recorded duration.']
    if algorithm['source_commit'] is None:limitations.append('Source commit is unavailable; exact locked file SHAs identify this run.')
    if any(environment.get(k) is None for k in ('gpu','driver','os','simulator_version')):limitations.append('Some recorded environment fields are unknown; null values are not inferred from another machine.')
    manifest={'schema_version':'1.0','run_id':run,'algorithm':algorithm,'protocol':{**pkg['protocol'],'scope':'official-scene','selection_policy':'all declared attempts; no best-of selection','episode_control_limit':int(budget.group(1)) if budget else None},'scene':scene,'attempt':{'reason':'original contributor run','repeats_run_id':None,**pkg['attempt']},'environment':environment,'status':'complete','timestamps':{'started_at':iso(info.get('started_unix')),'finished_at':iso(terminal.get('time_unix'))},'outcome':{'native_result':True,'episode_complete':True,'score':outcome['score'],'score_scale':'0..1','success':outcome['success'],'control_steps':controls,'model_decisions':trace['llm_calls'],'actual_responses':None if any(a['model_responses'] is None for a in attempts) else sum(a['model_responses'] for a in attempts),'unstable_envs':[],'evidence_consistent':True},'costs':{'attempts':attempts},'artifacts':sorted(arts,key=lambda x:x['path']),'audit':{'session_public_id':'public-'+digest(run.encode())[:20],'export_policy':'explicit-allowlist-v1','redactions':['private reasoning','account and native session identifiers','credentials','private paths'],'limitations':limitations}}
    verify_collection(native,run)
    if any(sha_file(p)!=expected for p,expected in source_hashes.items()):raise ValueError('Private source changed while exporting; preserve and reconcile')
    write(bundle/'manifest.json',manifest);load_manifest(bundle)
    return {'run_id':run,'bundle':str(bundle),'manifest_sha256':sha_file(bundle/'manifest.json'),'artifact_count':len(arts),'bytes':sum(x['bytes'] for x in arts)}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--controller',required=True);p.add_argument('--native',required=True);p.add_argument('--destination',required=True);p.add_argument('--package');p.add_argument('--tar',action='store_true');args=vars(p.parse_args());tar=args.pop('tar');result=export_portable(**args)
    if tar:result['archive']=deterministic_tar(result['bundle'],Path(result['bundle']).with_suffix('.tar'))
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
