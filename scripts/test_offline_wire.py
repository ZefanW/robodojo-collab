"""Exercise actual context-v2 bridge with a local synthetic provider, no paid calls."""
import base64,hashlib,io,json,sys,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from PIL import Image
import argparse,os
p=argparse.ArgumentParser();p.add_argument('--codex',required=True);p.add_argument('--roboprobe',required=True);p.add_argument('--output',required=True);a=p.parse_args()
os.environ['ROBODOJO_CODEX']=str(Path(a.codex).resolve())
for key in ('OPENAI_API_KEY','OPENAI_BASE_URL','CODEX_API_KEY'):os.environ.pop(key,None)
P=Path(__file__).resolve().parents[1];sys.path.insert(0,str(Path(a.roboprobe).resolve()));sys.path.insert(0,str(P/'scripts/runtime'))
from persistent_v1.bridge import PersistentBridge as ContextBridge
from codex_bridge import write
OUT=Path(a.output).resolve();OUT.mkdir(parents=True,exist_ok=False)
requests=[]
class H(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  d=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(d)
  write(OUT/f'wire-{len(requests)}.json',d)
  i=len(requests);rid=f'resp_synthetic_{i}'
  reason={'id':f'rs_{i}','type':'reasoning','summary':[],'encrypted_content':f'SYNTHETIC_STATE_ONLY_{i}'}
  decision={'content':'Synthetic assistant text '+str(i),'tool_calls':[{'name':'move_eef','arguments':'{"targets": {"left_z": 1.1}, "note": "synthetic"}'}]}
  text=json.dumps(decision);msg={'id':f'msg_{i}','type':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':text,'annotations':[]}]}
  ev=[{'type':'response.created','response':{'id':rid,'status':'in_progress','output':[]}}, {'type':'response.output_item.added','output_index':0,'item':reason},{'type':'response.output_item.done','output_index':0,'item':reason},{'type':'response.output_item.added','output_index':1,'item':dict(msg,content=[])},{'type':'response.content_part.added','output_index':1,'content_index':0,'item_id':msg['id'],'part':{'type':'output_text','text':'','annotations':[]}},{'type':'response.output_text.delta','output_index':1,'content_index':0,'item_id':msg['id'],'delta':text},{'type':'response.output_item.done','output_index':1,'item':msg},{'type':'response.completed','response':{'id':rid,'status':'completed','output':[reason,msg],'usage':{'input_tokens':100*i,'output_tokens':20,'total_tokens':100*i+20,'input_tokens_details':{'cached_tokens':0 if i==1 else 100},'output_tokens_details':{'reasoning_tokens':10}}}}]
  body=''.join('data: '+json.dumps(x)+'\n\n' for x in ev).encode();self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
s=ThreadingHTTPServer(('127.0.0.1',0),H);threading.Thread(target=s.serve_forever,daemon=True).start()
b=None
try:
 b=ContextBridge(OUT/'adapter','synthetic-account',offline=True,provider='local_wire',provider_config=dict(name='Local offline wire',base_url=f'http://127.0.0.1:{s.server_port}/v1',wire_api='responses',requires_openai_auth=False,request_max_retries=0,stream_max_retries=0))
 buf=io.BytesIO();Image.new('RGB',(16,16),'blue').save(buf,format='PNG');url='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()
 messages=[dict(role='system',content='SYNTHETIC OFFICIAL SYSTEM')]
 tools=[dict(type='function',function=dict(name=n,description='Synthetic tool',parameters=dict(type='object',properties={}))) for n in ('move_eef','give_up')]
 for i in range(3):
  if i==2:
   original_thread=b.episode_thread['thread']['id'];b.close()
   b=ContextBridge(OUT/'adapter','synthetic-account',offline=True,provider='local_wire',provider_config=dict(name='Local offline wire',base_url=f'http://127.0.0.1:{s.server_port}/v1',wire_api='responses',requires_openai_auth=False,request_max_retries=0,stream_max_retries=0))
   t=b.transport.request('thread/resume',dict(threadId=original_thread,cwd=str(b.agent),model='gpt-6-astra',modelProvider='local_wire',config=dict(model_reasoning_effort='medium'),excludeTurns=True,approvalPolicy='never',permissions='rollout_agent',runtimeWorkspaceRoots=[str(b.agent)]),60)
   assert t['thread']['id']==original_thread and t['thread']['status']['type']=='idle'
   from codex_bridge import pack
   base,*_=pack(b.history.messages,b.history.tools)
   b.episode_thread=t;b.episode_contract=(base,b.history.tools)
  messages.append(dict(role='user',content=[dict(type='text',text='OBSERVATION_'+str(i))]+[dict(type='image_url',image_url={'url':url})]*3))
  payload=dict(model='gpt-6-astra',reasoning_effort='medium',messages=messages,tools=tools,index=i,run_id='synthetic')
  receipt=b.complete(payload,hashlib.sha256(json.dumps(payload).encode()).hexdigest(),OUT/'calls'/f'{i:04d}')
  msg=receipt['response']['choices'][0]['message'];messages=b.history.project()[0]+[msg,dict(role='tool',tool_call_id=msg['tool_calls'][0]['id'],content='Native feedback '+str(i))]
 assert len(requests)==3
 thread_ids={json.loads(p.read_text())['thread_id'] for p in (OUT/'calls').glob('*/response.json')}
 assert len(thread_ids)==1,thread_ids
 assert sum(json.loads(p.read_text())['tokens']['totalTokens'] for p in (OUT/'calls').glob('*/response.json'))==660
 assert 'model_auto_compact_token_limit=10000000' not in json.dumps(json.loads((OUT/'adapter/launch.json').read_text()))
 audits=[]
 for i,request in enumerate(requests):
  inp=request['input'];reasons=[x for x in inp if x.get('type')=='reasoning']
  assert [x['encrypted_content'] for x in reasons]==['SYNTHETIC_STATE_ONLY_'+str(k+1) for k in range(i)],[(x.get('id'),x.get('encrypted_content')) for x in reasons]
  images=sum(y.get('type')=='input_image' for x in inp if isinstance(x.get('content'),list) for y in x['content'])
  assert images==3*(i+1),images
  tools=[x for x in inp if x.get('type')=='additional_tools']
  assert 'collaboration' not in json.dumps(tools)
  assert request['reasoning']==dict(effort='medium',context='all_turns'),request.get('reasoning')
  assert 'AGENTS.md' not in json.dumps(inp)
  audits.append(dict(index=i,prior_reasoning_items=len(reasons),active_images=images,official_system_present='SYNTHETIC OFFICIAL SYSTEM' in json.dumps(inp),no_global_project_instructions=True))
 write(OUT/'verified.json',dict(real_model_calls=0,synthetic_requests=3,same_original_thread_after_process_restart=True,checks=audits))
 print(json.dumps(json.loads((OUT/'verified.json').read_text())),flush=True)
finally:
 if b:b.close()
 s.shutdown()
