"""Context-preserving upgrade for the existing labeled Codex JSON transport.

Prepared adapter, not proof of exact official native-function-tool equivalence.
Historical bridge and scores remain unchanged. One native case gates rollout.
"""
import hashlib
import json
import os
import subprocess
import time
import copy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import codex_bridge as old
from .history import History

class ObservedTransport:
 def __init__(self,transport,owner):self.transport=transport;self.owner=owner
 def request(self,method,params,timeout):
  params=dict(params)
  if method=='thread/start':params['experimentalRawEvents']=True
  elif method=='thread/inject_items':
   if self.owner.current_items is None:raise RuntimeError('Canonical history not prepared')
   params['items']=self.owner.current_items
  return self.transport.request(method,params,timeout)
 def next_message(self,timeout):
  event=self.transport.next_message(timeout)
  if event.get('method')=='rawResponseItem/completed':
   item=event.get('params',{}).get('item',{})
   if item.get('type')=='reasoning':
    self.owner.raw_reasoning.append(item)
    old.write(self.owner.current_folder/'raw-reasoning.json',self.owner.raw_reasoning)
  return event
 def __getattr__(self,name):return getattr(self.transport,name)

class PreparedLegacyContextBridge(old.Bridge):
 def __init__(self,output,account,stop_event=None,passive_quota=None):
  self.history=History(Path(output)/'permanent-history')
  self.current_items=None;self.raw_reasoning=[];self.current_folder=None
  super().__init__(output,account,stop_event,passive_quota)
  self.transport=ObservedTransport(self.transport,self)

 def complete(self,payload,digest,folder):
  folder=Path(folder);index=int(folder.name)
  existing=folder/'response.json'
  if existing.exists():
   saved=json.loads(existing.read_text())
   if saved['request_sha256']!=digest:raise RuntimeError('Saved paid response does not match pending request')
   if not (folder/'context-committed.json').exists():raise RuntimeError('Paid response exists but context commit is incomplete; reconcile without a paid retry')
   return saved
  if (folder/'paid-start.json').exists():raise RuntimeError('Earlier paid request unresolved; no automatic retry')
  view,self.current_items,audit=self.history.ingest(payload,index)
  self.current_folder=folder;self.raw_reasoning=[]
  old.write(folder/'context-before.json',audit)
  projected=dict(payload,messages=view)
  # Digest refers to the immutable simulator request. Image-only projection is
  # separately hashed; official source normally already sends this projection.
  try:
   saved=super().complete(projected,digest,folder)
   self.history.record(index,saved['response'],self.raw_reasoning,saved['tokens'].get('reasoningOutputTokens'))
   old.write(folder/'context-committed.json',dict(index=index,request_sha256=digest,archive_next_index=self.history.next_index,reasoning_items=len(self.raw_reasoning),model_view_audit=audit,transport='Codex JSON adaptation; native-function equivalence not claimed'))
   return saved
  except BaseException as error:
   if self.stop_event is not None:self.stop_event.set()
   self.hold_reason=repr(error)
   old.write(folder/'context-hold.json',dict(error=repr(error),paid_retry=False,inspect_saved_receipts=True))
   raise


def completion_schema():
 """Transport envelope; the native policy still validates action arguments."""
 return {'type':'object','additionalProperties':False,'required':['content','tool_calls'],
         'properties':{'content':{'type':['string','null']},'tool_calls':{'type':'array','items':{
          'type':'object','additionalProperties':False,'required':['name','arguments'],
          'properties':{'name':{'type':'string','enum':['move_eef','give_up']},
                        'arguments':{'type':'string'}}}}}}


def decode_completion(value,turn):
 """Do not parse/fix argument JSON or merge actions; upstream owns that logic."""
 if set(value)!={'content','tool_calls'} or not isinstance(value['tool_calls'],list):
  raise RuntimeError('Invalid transport envelope; retain paid reply for reconciliation')
 if value['content'] is not None and not isinstance(value['content'],str):
  raise RuntimeError('Invalid assistant content')
 calls=[]
 for index,call in enumerate(value['tool_calls']):
  if set(call)!={'name','arguments'} or call['name'] not in ('move_eef','give_up') or not isinstance(call['arguments'],str):
   raise RuntimeError('Invalid transport call envelope')
  calls.append(dict(id=f'call_{turn}_{index}',type='function',function=dict(call)))
 message=dict(role='assistant',content=value['content'])
 if calls:message['tool_calls']=calls
 return {'id':turn,'model':old.MODEL,'choices':[{'finish_reason':'tool_calls' if calls else 'stop','message':message}]}


DISABLED_HOST_OUTPUT = 'code-mode host is disabled'


def audit_host_items(items, *, final=False):
 """Accept only the CLI's exact disabled-host reply; never execute a host tool.

 A raw exec request can be observed before its disabled response. Preserve it
 while waiting, but any other tool or any non-disabled output fails closed.
 """
 calls={};outputs={}
 for item in items:
  kind=item.get('type')
  if kind in ('reasoning','message'):continue
  if kind=='custom_tool_call':
   call=item.get('call_id')
   if item.get('name')!='exec' or not isinstance(call,str) or not call:
    raise RuntimeError('Unexpected raw host tool; information boundary violated')
   if call in calls:raise RuntimeError('Duplicate raw host tool call identifier')
   calls[call]=item
  elif kind=='custom_tool_call_output':
   call=item.get('call_id')
   if call not in calls or call in outputs or item.get('output')!=DISABLED_HOST_OUTPUT:
    raise RuntimeError('Host tool output is not the exact disabled-host error; hold')
   outputs[call]=item
  else:raise RuntimeError('Unexpected raw response item may expose external information: '+str(kind))
 unresolved=set(calls)-set(outputs)
 if final and unresolved:raise RuntimeError('Host tool request has no verified disabled-host response')
 return dict(host_tool_attempts=len(calls),disabled_host_attempts=len(outputs),disabled_host_tool_attempts=len(outputs),
             unresolved_host_attempts=len(unresolved),successful_host_tool_executions=0,
             information_boundary_verified=not unresolved,
             disabled_host_call_ids=list(outputs),
             accepted_output=DISABLED_HOST_OUTPUT,
             note='Disabled tool error adds transport-only feedback and may cause extra model responses; no host code or environmental information returned.')


def raw_response_index(path):
 """Index actual model responses from saved events, excluding injected history."""
 result={}
 if not Path(path).exists():return result
 for line in Path(path).open():
  try:event=json.loads(line)
  except ValueError:continue
  if event.get('method')!='rawResponse/completed':continue
  p=event.get('params',{});key=(p.get('threadId'),p.get('turnId'))
  result.setdefault(key,[]).append(p)
 return result


def call_accounting(folder, *, event_index=None, final=True):
 """Derive counters without changing an immutable paid response receipt."""
 folder=Path(folder)
 raw=json.loads((folder/'raw-output.json').read_text())
 info=audit_host_items(raw,final=final)
 receipt=json.loads((folder/'response.json').read_text()) if (folder/'response.json').exists() else None
 events_path=folder/'raw-response-receipts.json'
 if events_path.exists():events=json.loads(events_path.read_text())
 elif (folder/'journal-response-receipts.json').exists():events=json.loads((folder/'journal-response-receipts.json').read_text())
 elif event_index is not None and receipt is not None:events=event_index.get((receipt['thread_id'],receipt['turn_id']),[])
 else:events=[]
 unique={}
 for event in events:
  identity=event.get('responseId')
  if not identity:raise RuntimeError('Actual model response has no response ID')
  if identity in unique and unique[identity]!=event:raise RuntimeError('Response ID has conflicting usage metadata')
  unique[identity]=event
 if final and not unique:raise RuntimeError('Actual model response accounting unavailable')
 fields=('inputTokens','cachedInputTokens','outputTokens','reasoningOutputTokens','totalTokens')
 totals={k:sum(e.get('usage',{}).get(k,0) for e in unique.values()) for k in fields}
 if final and receipt is not None and any(totals[k]!=receipt['tokens'].get(k,0) for k in fields):
  raise RuntimeError('Per-response token usage does not reconcile with the one-count-per-turn receipt')
 info.update(actual_model_responses=len(unique),actual_response_ids=list(unique),
             model_responses_lower_bound=len(unique),response_usage_totals=totals,
             logical_model_decisions=1 if receipt is not None else 0,
             codex_turns=1 if (folder/'paid-start.json').exists() else 0,
             source=('native journal token_usage_record IDs + response_item; explicit artifact recovery' if (folder/'journal-response-receipts.json').exists() else 'rawResponse/completed IDs, raw tool call/output pairs; thread token totals counted once'))
 return info


class ContextBridge(old.Bridge):
 """Full task information + opaque reasoning, with an explicit JSON wire adapter.

 A fresh native request context is projected from the immutable episode archive.
 This removes only old unprotected images; no summary substitutes for history.
 Official EEF policy handles all parsing, merges, repair feedback and controls.
 """
 def __init__(self,output,account,stop_event=None,passive_quota=None,*,provider='openai',provider_config=None,offline=False,retry_authorization=None):
  if passive_quota is None and not offline:raise ValueError('Passive quota guard required; no polling fallback')
  self.output=Path(output).resolve();self.output.mkdir(parents=True,exist_ok=True)
  self.agent=self.output/'agent';self.agent.mkdir(exist_ok=True)
  self.history=History(self.output/'permanent-history')
  self.account=account;self.stop_event=stop_event;self.passive_quota=passive_quota
  self.hold_reason=None;self.provider=provider;self.offline=offline
  self.retry_authorization=retry_authorization
  if retry_authorization:
   from .retry import validate_authorization
   validate_authorization(retry_authorization,account)
  # Isolate experiment context without changing the user's Codex configuration.
  self.codex_home=self.output/'codex-home';self.codex_home.mkdir(exist_ok=True)
  if not offline:
   auth=Path.home()/'.codex/auth.json';target=self.codex_home/'auth.json'
   if not target.exists():target.symlink_to(auth)
   if target.resolve()!=auth.resolve():raise RuntimeError('Unexpected experiment auth identity path')
  cfg=old.agent_config(self.output,self.agent)
  cfg.update({'model_provider':provider,'agents.enabled':False,'agents.interrupt_message':False,
   'features.shell_tool':False,'features.unified_exec':False,'features.view_image':False,
   'features.multi_agent':False,'features.image_generation':False,'features.sleep_tool':False,
   'features.code_mode.enabled':False,'features.code_mode_host':False,'features.code_mode_only':False,
   'features.responses_websockets':False,'features.responses_websockets_v2':False,
   'web_search':'disabled','model_auto_compact_token_limit':10000000})
  if provider_config is not None:cfg['model_providers.'+provider]=provider_config
  argv=[old.CODEX,'app-server','--stdio','--strict-config']
  for k,v in cfg.items():argv+=['-c',k+'='+old.toml_value(v)]
  env=dict(os.environ,CODEX_HOME=str(self.codex_home),ROLLOUT_ISOLATE_HOST_CONTEXT='1',ROLLOUT_CODEX_STATE_DIR=str(self.output/'state'))
  old.write(self.output/'launch.json',dict(argv=argv,account_id=account,codex_home=str(self.codex_home),
    method='L3 context-v2; official task information with JSON transport',paid_retry=False,offline=offline))
  self.transport=old.StdioAppServer(argv,self.output,popen=lambda *a,**k:subprocess.Popen(*a,**k,env=env))
  self.transport._in_log=old.CompactInputLog(self.transport._in_log)
  self.transport.request('initialize',dict(clientInfo=dict(name='robodojo-l3-context-v2',version='2'),capabilities=dict(experimentalApi=True)),60)
  self.transport.notify('initialized',{})

 def complete(self,payload,digest,folder):
  """One native decision, with at most two separately counted repair attempts."""
  from .retry import attempt_folders,selected_folder,retryable_attempt,FEEDBACK
  folder=Path(folder);index=int(folder.name)
  selected=selected_folder(folder)
  if (selected/'response.json').exists():
   result=self._complete_attempt(payload,digest,selected,index=index)
   if selected!=folder:
    old.write(folder/'response.json',result);old.write(folder/'context-committed.json',read_json(selected/'context-committed.json'))
   return result
  attempts=attempt_folders(folder)
  current=attempts[-1]
  while True:
   attempted=False
   try:
    if not (current/'paid-start.json').exists():
     attempted=True
     result=self._complete_attempt(payload,digest,current,index=index)
    else:
     if not self.retry_authorization:raise RuntimeError('Prior paid turn unresolved; no automatic retry')
     ordinal=len(attempts)
     if ordinal>2:raise RuntimeError('Same-step additional retry allowance exhausted; scene retained')
     if not self.offline:self.check_quota()
     audit=retryable_attempt(current,digest,expected_account=self.account)
     # A fully generated valid envelope must be reconciled, never regenerated.
     for item in audit['failed_turn_items']:
      if item.get('type')=='message':
       texts=[v.get('text','') for v in item.get('content',[]) if v.get('type')=='output_text']
       if texts:
        try:decode_completion(json.loads(''.join(texts)),audit['turn_id'])
        except (ValueError,TypeError,RuntimeError):pass
        else:raise RuntimeError('Valid saved raw reply found; reconcile it without another paid call')
     prefix=read_json(current/'retry-input-prefix.json') if (current/'retry-input-prefix.json').exists() else []
     prefix=prefix+audit['failed_turn_items']+[dict(type='message',role='user',content=[dict(type='input_text',text=FEEDBACK)])]
     destination=folder/'retries'/f'{ordinal:03d}'
     destination.mkdir(parents=True,exist_ok=False)
     old.write(destination/'retry-proof.json',dict(audit,additional_attempt=ordinal,authorization=self.retry_authorization,
              canonical_history_sha256=hashlib.sha256((self.history.root/'state.json').read_bytes()).hexdigest()))
     old.write(destination/'retry-input-prefix.json',prefix)
     delay=self.retry_authorization['backoff_seconds'][ordinal-1]
     if self.stop_event is not None:
      if self.stop_event.wait(delay):raise RuntimeError('Shared hold during retry backoff')
     else:time.sleep(delay)
     if not self.offline:self.check_quota()
     current=destination;attempts.append(current)
     attempted=True
     result=self._complete_attempt(payload,digest,current,index=index,continuation=audit,transport_prefix=prefix)
    if current!=folder:
     # Root mirrors are the one deliverable native decision, not extra usage.
     old.write(folder/'selected-attempt.json',dict(attempt_path=str(current.relative_to(folder)),additional_attempt=len(attempts)-1,
               request_sha256=digest,original_failed_receipts_preserved=True))
     old.write(folder/'response.json',result)
     old.write(folder/'context-committed.json',read_json(current/'context-committed.json'))
    self.hold_reason=None
    return result
   except BaseException:
    if (not attempted or not self.retry_authorization or (self.stop_event is not None and self.stop_event.is_set())
        or not (current/'paid-start.json').exists() or len(attempts)>2):
     if self.stop_event is not None:self.stop_event.set()
     raise
    # Retry qualification is evaluated on the next iteration; unknown external
    # information never becomes an accepted result by retrying.
    try:retryable_attempt(current,digest,expected_account=self.account)
    except BaseException:
     if self.stop_event is not None:self.stop_event.set()
     raise

 def _complete_attempt(self,payload,digest,folder,*,index=None,continuation=None,transport_prefix=None):
  folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);index=int(folder.name) if index is None else index
  if (folder/'response.json').exists():
   saved=json.loads((folder/'response.json').read_text())
   if saved['request_sha256']!=digest:raise RuntimeError('Saved paid receipt hash mismatch')
   if not (folder/'context-committed.json').exists():
    accounting=call_accounting(folder)
    reasons=read_json(folder/'raw-reasoning.json')
    prefix=read_json(folder/'retry-input-prefix.json') if (folder/'retry-input-prefix.json').exists() else None
    self.history.ingest(payload,index)
    self.history.record(index,saved['response'],reasons,saved['tokens'].get('reasoningOutputTokens'),transport_prefix=prefix)
    old.write(folder/'context-committed.json',dict(index=index,request_sha256=digest,reasoning_items=len(reasons),archive_next_index=self.history.next_index,accounting=accounting,reused_valid_paid_response=True))
   return saved
  if (folder/'paid-start.json').exists():raise RuntimeError('Prior paid turn unresolved; no automatic retry')
  if payload['model']!=old.MODEL or payload['reasoning_effort']!='medium':raise RuntimeError('Unexpected model/effort')
  if not self.offline:self.check_quota()
  view,items,audit=self.history.ingest(payload,index)
  base,_,_,_=old.pack(view,payload['tools'])
  developer=('Transport encoding only. Produce one assistant response using the JSON envelope: '
    'content is the assistant text (or null), tool_calls is the ordered list of function calls '
    '(possibly empty); each arguments field is the original JSON-encoded argument string. '
    'These are the same function definitions as the robot interface below. '
    'Do not invoke host tools or obtain information outside the supplied robot dialogue. '
    'The robot controller, not you, executes the returned calls and supplies subsequent feedback.\n'
    +json.dumps(payload['tools'],ensure_ascii=False))
  old.write(folder/'request.json',old.compact_images(payload));old.write(folder/'context-before.json',audit)
  if continuation:
   from .retry import journal_items,digest as item_digest
   t=self.transport.request('thread/resume',dict(threadId=continuation['thread_id'],cwd=str(self.agent),model=old.MODEL,
     modelProvider=self.provider,config=dict(model_reasoning_effort='medium'),excludeTurns=True,
     approvalPolicy='never',permissions='rollout_agent',runtimeWorkspaceRoots=[str(self.agent)]),60)
   if t['thread']['id']!=continuation['thread_id'] or t['thread'].get('status',{}).get('type')!='idle':raise RuntimeError('Original retry thread not idle; no new-thread fallback')
   _,preserved=journal_items(t['thread'].get('path') or continuation['journal_path'])
   if [item_digest(x) for x in preserved]!=continuation['journal_item_sha256']:raise RuntimeError('Original retry thread history changed')
  else:
   t=self.transport.request('thread/start',dict(cwd=str(self.agent),model=old.MODEL,modelProvider=self.provider,
     config=dict(model_reasoning_effort='medium'),baseInstructions=base,developerInstructions=developer,
     dynamicTools=[],experimentalRawEvents=True,ephemeral=False,allowProviderModelFallback=False,
     approvalPolicy='never',permissions='rollout_agent',runtimeWorkspaceRoots=[str(self.agent)]),60)
  if t.get('model')!=old.MODEL or t.get('reasoningEffort')!='medium':raise RuntimeError('Unexpected resolved model/effort')
  if t.get('instructionSources'):raise RuntimeError('Unexpected host instructions; no paid call started')
  tid=t['thread']['id'];old.write(folder/'thread.json',t)
  old.write(folder/'transport-context.json',dict(official_system_sha256=hashlib.sha256(base.encode()).hexdigest(),
    tool_definitions_sha256=hashlib.sha256(json.dumps(payload['tools'],sort_keys=True).encode()).hexdigest(),
    instruction_sources=t.get('instructionSources',[]),history=audit,encoding='JSON assistant content plus ordered calls; native tools simulated at wire boundary',
    context_continuity='Complete canonical history reinjected with opaque reasoning; fresh native thread per decision'))
  if not continuation:self.transport.request('thread/inject_items',dict(threadId=tid,items=items),60)
  if not self.offline:self.check_quota()
  started=time.time();old.write(folder/'paid-start.json',dict(thread_id=tid,request_sha256=digest,time=started,offline=self.offline,account_id=self.account))
  from .retry import FEEDBACK
  turn=self.transport.request('turn/start',dict(threadId=tid,model=old.MODEL,effort='medium',input=[dict(type='text',text=FEEDBACK)] if continuation else [],
    outputSchema=completion_schema(),approvalPolicy='never',permissions='rollout_agent',cwd=str(self.agent),runtimeWorkspaceRoots=[str(self.agent)]),60)['turn']['id']
  old.write(folder/'paid-turn.json',dict(turn_id=turn,thread_id=tid,request_sha256=digest))
  usage={};texts=[];raw=[];reasons=[];model_responses=[];fresh=False;deadline=time.monotonic()+600
  try:
   while True:
    event=self.transport.next_message(max(1,deadline-time.monotonic()));kind=event.get('method');p=event.get('params',{})
    if kind=='account/rateLimits/updated' and self.passive_quota is not None:
     try:
      observed=event.get('emittedAtMs',time.time()*1000)/1000;self.passive_quota.observe(p,observed,str(folder));fresh |= observed>=started
     except RuntimeError as error:self.hold_reason=repr(error);self.stop_event.set()
    if p.get('threadId')!=tid:continue
    if kind=='rawResponseItem/completed':
     # Injected historical items are echoed with a synthetic turn id. They are
     # prior context, not newly generated reasoning for this paid response.
     if p.get('turnId')!=turn:continue
     item=p['item'];raw.append(item)
     if item.get('type')=='reasoning':reasons.append(item)
     old.write(folder/'raw-output.json',raw);old.write(folder/'raw-reasoning.json',reasons)
     boundary=audit_host_items(raw)
     old.write(folder/'host-tool-audit.json',boundary)
    elif kind=='rawResponse/completed' and p.get('turnId')==turn:
     model_responses.append(p)
     old.write(folder/'raw-response-receipts.json',model_responses)
    elif kind=='thread/tokenUsage/updated':
     usage=p.get('tokenUsage',{}).get('total',{});old.write(folder/('native-cumulative-usage.json' if continuation else 'usage.json'),usage)
    elif kind=='item/completed':
     item=p.get('item',{})
     if item.get('type')=='agentMessage':texts.append(item.get('text',''))
     elif item.get('type') in ('commandExecution','fileChange','imageView','webSearch','mcpToolCall','collabAgentToolCall','dynamicToolCall','contextCompaction'):
      raise RuntimeError('Unexpected host tool or compaction; task information boundary violated')
    elif kind=='item/tool/call':raise RuntimeError('Host tool request forbidden; preserve without executing')
    elif kind=='error' and not p.get('willRetry'):raise RuntimeError('Paid transport error; preserve without retry: '+str(p.get('error',{})))
    elif kind=='turn/completed' and p.get('turn',{}).get('id')==turn:
     if p['turn'].get('status')!='completed' or not texts:raise RuntimeError('Paid completion incomplete')
     old.write(folder/'assistant-text.json',texts)
     if continuation:
      unique={e['responseId']:e for e in model_responses}
      if not unique:
       from .journal_receipts import restore_artifacts
       recovered=restore_artifacts(folder);raw=recovered['raw'];reasons=recovered['reasoning'];model_responses=recovered['responses']
       unique={e['responseId']:e for e in model_responses}
      usage={k:sum(e.get('usage',{}).get(k,0) for e in unique.values()) for k in ('inputTokens','cachedInputTokens','outputTokens','reasoningOutputTokens','totalTokens')}
      old.write(folder/'usage.json',usage)
     response=decode_completion(json.loads(texts[-1]),turn)
     response['usage']={'prompt_tokens':usage.get('inputTokens'),'completion_tokens':usage.get('outputTokens'),'total_tokens':usage.get('totalTokens'),
       'prompt_tokens_details':{'cached_tokens':usage.get('cachedInputTokens')},'completion_tokens_details':{'reasoning_tokens':usage.get('reasoningOutputTokens')}}
     saved=dict(request_sha256=digest,response=response,thread_id=tid,turn_id=turn,tokens=usage,completed_unix=time.time(),account_id=self.account)
     old.write(folder/'response.json',saved)
     if not usage.get('totalTokens'):raise RuntimeError('Paid response saved without usage; reconcile before new call')
     accounting=call_accounting(folder)
     old.write(folder/'accounting.json',accounting)
     self.history.record(index,response,reasons,usage.get('reasoningOutputTokens'),transport_prefix=transport_prefix)
     old.write(folder/'context-committed.json',dict(index=index,request_sha256=digest,reasoning_items=len(reasons),model_view_audit=audit,archive_next_index=self.history.next_index,accounting=accounting))
     if not self.offline and not fresh:self.hold_reason='No fresh passive quota notification';self.stop_event.set()
     return saved
    if time.monotonic()>deadline:raise TimeoutError('Paid turn deadline')
  except BaseException as error:
   self.hold_reason=repr(error)
   if self.stop_event is not None and not self.retry_authorization:self.stop_event.set()
   old.write(folder/'context-hold.json',dict(error=repr(error),paid_retry=False))
   try:self.transport.request('turn/interrupt',dict(threadId=tid,turnId=turn),15)
   except Exception:pass
   # The native interruption record proves no additional host output appeared.
   for _ in range(20):
    try:
     from .retry import retryable_attempt
     retryable_attempt(folder,digest,expected_account=self.account);break
    except (RuntimeError,FileNotFoundError):time.sleep(.1)
   raise


def read_json(path):return json.loads(Path(path).read_text())
