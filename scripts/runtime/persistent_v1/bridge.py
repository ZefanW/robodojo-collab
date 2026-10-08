# Portable adaptation: authentication home is explicitly configured; all model/action/history logic retained.
"""L3 persistent variant. Derived from frozen ContextBridge with only context lifetime changed."""
import copy,hashlib,json,os,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import codex_bridge as old
from context_v2.bridge import completion_schema,decode_completion,audit_host_items,call_accounting,read_json
from context_v2.history import History,native_items,image_count,digest as history_digest,without_images

class FullHistory(History):
 def project(self):
  view=copy.deepcopy(self.messages)
  items=native_items([m for m in view if m.get('role')!='system'],self.store,self.transport_prefixes)
  audit=dict(index=self.next_index,archived_images=image_count(view),active_images=image_count(view),
    image_horizon=None,manual_image_pruning=False,native_persistent_session=True,
    text_actions_feedback_sha256=history_digest(without_images(view)),full_history_sha256=history_digest(view))
  old.write(self.root/f'projection-{self.next_index:04d}.json',audit)
  return view,items,audit

def incremental_items(messages):
 # Previous decisions already exist as native JSON assistant outputs. Only add
 # their function-call aliases (required to attach native tool feedback), never
 # duplicate assistant prose or re-inject prior encrypted reasoning.
 value=copy.deepcopy([m for m in messages if m.get('role')!='system'])
 for m in value:
  if m.get('role')=='assistant':m['content']=None
 return native_items(value,None)

class PersistentBridge(old.Bridge):
 """Full task information + opaque reasoning, with an explicit JSON wire adapter.

 A fresh native request context is projected from the immutable episode archive.
 This removes only old unprotected images; no summary substitutes for history.
 Official EEF policy handles all parsing, merges, repair feedback and controls.
 """
 def __init__(self,output,account,stop_event=None,passive_quota=None,*,provider='openai',provider_config=None,offline=False,retry_authorization=None):
  if passive_quota is None and not offline:raise ValueError('Passive quota guard required; no polling fallback')
  self.output=Path(output).resolve();self.output.mkdir(parents=True,exist_ok=True)
  self.agent=self.output/'agent';self.agent.mkdir(exist_ok=True)
  self.history=FullHistory(self.output/'permanent-history');self.episode_thread=None;self.episode_contract=None
  self.account=account;self.stop_event=stop_event;self.passive_quota=passive_quota
  self.hold_reason=None;self.provider=provider;self.offline=offline
  self.retry_authorization=retry_authorization
  if retry_authorization:
   from context_v2.retry import validate_authorization
   validate_authorization(retry_authorization,account)
  # Isolate experiment context without changing the user's Codex configuration.
  self.codex_home=self.output/'codex-home';self.codex_home.mkdir(exist_ok=True)
  if not offline:
   auth=Path(os.environ['ROBODOJO_AUTH_HOME'])/'auth.json';target=self.codex_home/'auth.json'
   if not target.exists():target.symlink_to(auth)
   if target.resolve()!=auth.resolve():raise RuntimeError('Unexpected experiment auth identity path')
  cfg=old.agent_config(self.output,self.agent)
  cfg.update({'model_provider':provider,'agents.enabled':False,'agents.interrupt_message':False,
   'features.shell_tool':False,'features.unified_exec':False,'features.view_image':False,
   'features.multi_agent':False,'features.image_generation':False,'features.sleep_tool':False,
   'features.code_mode.enabled':False,'features.code_mode_host':False,'features.code_mode_only':False,
   'features.responses_websockets':False,'features.responses_websockets_v2':False,
   'web_search':'disabled'})
  if provider_config is not None:cfg['model_providers.'+provider]=provider_config
  argv=[old.CODEX,'app-server','--stdio','--strict-config']
  for k,v in cfg.items():argv+=['-c',k+'='+old.toml_value(v)]
  env=dict(os.environ,CODEX_HOME=str(self.codex_home),ROLLOUT_ISOLATE_HOST_CONTEXT='1',ROLLOUT_CODEX_STATE_DIR=str(self.output/'state'))
  old.write(self.output/'launch.json',dict(argv=argv,account_id=account,codex_home=str(self.codex_home),
    method='L3 persistent; original policy with one native session and all historical images',paid_retry=False,offline=offline))
  self.transport=old.StdioAppServer(argv,self.output,popen=lambda *a,**k:subprocess.Popen(*a,**k,env=env))
  self.transport._in_log=old.CompactInputLog(self.transport._in_log)
  self.transport.request('initialize',dict(clientInfo=dict(name='robodojo-l3-context-v2',version='2'),capabilities=dict(experimentalApi=True)),60)
  self.transport.notify('initialized',{})

 def complete(self,payload,digest,folder):
  """One native decision, with at most two separately counted repair attempts."""
  from context_v2.retry import attempt_folders,selected_folder,retryable_attempt,FEEDBACK
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
  previous_count=len(self.history.messages)
  view,all_items,audit=self.history.ingest(payload,index)
  items=incremental_items(view[previous_count:])
  audit['new_items_sha256']=history_digest(items)
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
   from context_v2.retry import journal_items,digest as item_digest
   t=self.transport.request('thread/resume',dict(threadId=continuation['thread_id'],cwd=str(self.agent),model=old.MODEL,
     modelProvider=self.provider,config=dict(model_reasoning_effort='medium'),excludeTurns=True,
     approvalPolicy='never',permissions='rollout_agent',runtimeWorkspaceRoots=[str(self.agent)]),60)
   if t['thread']['id']!=continuation['thread_id'] or t['thread'].get('status',{}).get('type')!='idle':raise RuntimeError('Original retry thread not idle; no new-thread fallback')
   _,preserved=journal_items(t['thread'].get('path') or continuation['journal_path'])
   if [item_digest(x) for x in preserved]!=continuation['journal_item_sha256']:raise RuntimeError('Original retry thread history changed')
  elif self.episode_thread is None:
   t=self.transport.request('thread/start',dict(cwd=str(self.agent),model=old.MODEL,modelProvider=self.provider,
     config=dict(model_reasoning_effort='medium'),baseInstructions=base,developerInstructions=developer,
     dynamicTools=[],experimentalRawEvents=True,ephemeral=False,allowProviderModelFallback=False,
     approvalPolicy='never',permissions='rollout_agent',runtimeWorkspaceRoots=[str(self.agent)]),60)
   self.episode_thread=t;self.episode_contract=(base,payload['tools'])
  else:
   t=self.episode_thread
   if self.episode_contract!=(base,payload['tools']):raise RuntimeError('Original L3 system/tool contract changed')
  if t.get('model')!=old.MODEL or t.get('reasoningEffort')!='medium':raise RuntimeError('Unexpected resolved model/effort')
  if t.get('instructionSources'):raise RuntimeError('Unexpected host instructions; no paid call started')
  tid=t['thread']['id'];old.write(folder/'thread.json',t)
  old.write(folder/'transport-context.json',dict(official_system_sha256=hashlib.sha256(base.encode()).hexdigest(),
    tool_definitions_sha256=hashlib.sha256(json.dumps(payload['tools'],sort_keys=True).encode()).hexdigest(),
    instruction_sources=t.get('instructionSources',[]),history=audit,encoding='JSON assistant content plus ordered calls; native tools simulated at wire boundary',
    context_continuity='One native session; incremental observations/function aliases/feedback only; no image pruning. Native JSON assistant and reasoning retained. Native compaction allowed, full disk archive retained.'))
  if not continuation:self.transport.request('thread/inject_items',dict(threadId=tid,items=items),60)
  if not self.offline:self.check_quota()
  started=time.time();old.write(folder/'paid-start.json',dict(thread_id=tid,request_sha256=digest,time=started,offline=self.offline,account_id=self.account))
  from context_v2.retry import FEEDBACK
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
     usage=p.get('tokenUsage',{}).get('total',{});old.write(folder/'native-cumulative-usage.json',usage)
    elif kind=='item/completed':
     item=p.get('item',{})
     if item.get('type')=='agentMessage':texts.append(item.get('text',''))
     elif item.get('type')=='contextCompaction':
      old.write(folder/'native-compaction.json',dict(observed=True,item=item,old_disk_history_retained=True))
     elif item.get('type') in ('commandExecution','fileChange','imageView','webSearch','mcpToolCall','collabAgentToolCall','dynamicToolCall'):
      raise RuntimeError('Unexpected host tool or compaction; task information boundary violated')
    elif kind=='item/tool/call':raise RuntimeError('Host tool request forbidden; preserve without executing')
    elif kind=='error' and not p.get('willRetry'):raise RuntimeError('Paid transport error; preserve without retry: '+str(p.get('error',{})))
    elif kind=='turn/completed' and p.get('turn',{}).get('id')==turn:
     if p['turn'].get('status')!='completed' or not texts:raise RuntimeError('Paid completion incomplete')
     old.write(folder/'assistant-text.json',texts)
     if True: # Native session totals are cumulative: bill unique responses only.
      unique={e['responseId']:e for e in model_responses}
      if not unique:
       from context_v2.journal_receipts import restore_artifacts
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
     from context_v2.retry import retryable_attempt
     retryable_attempt(folder,digest,expected_account=self.account);break
    except (RuntimeError,FileNotFoundError):time.sleep(.1)
   raise


def read_json(path):return json.loads(Path(path).read_text())
