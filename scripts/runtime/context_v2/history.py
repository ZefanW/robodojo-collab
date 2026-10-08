"""Lossless episode archive; official image-window projection, opaque reasoning replay.

No model calls. Images are removed only from a derived model-input view.
"""
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'l3_runtime'))
import codex_bridge
from XPolicyLab.utils.openai_responses import ReasoningReplayStore,chat_messages_to_responses_input
from XPolicyLab.policy.RoboDojo_Agent_L3_Inspect.policy import _compact_message_history_in_place

STUB='[earlier camera image omitted to save context]'

def digest(value):
 return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def without_images(messages):
 result=copy.deepcopy(messages)
 for message in result:
  parts=message.get('content')
  if isinstance(parts,list):
   message['content']=[dict(type='text',text=STUB) if p.get('type')=='image_url' else p for p in parts]
 return result

def image_count(messages):
 return sum(p.get('type')=='image_url' for m in messages if isinstance(m.get('content'),list) for p in m['content'])

def native_items(messages,store,prefixes=None):
 result=[]
 for index,message in enumerate(messages):
  extra=(prefixes or {}).get(str(index))
  if extra:
   if digest(message)!=extra['following_message_sha256']:raise RuntimeError('Retry context anchor changed')
   result.extend(copy.deepcopy(extra['items']))
  result.extend(chat_messages_to_responses_input([message],reasoning_store=store))
 for item in result:
  if 'role' in item:
   item['type']='message'
   if isinstance(item.get('content'),str):
    item['content']=[dict(type='output_text' if item['role']=='assistant' else 'input_text',text=item['content'])]
 return result

class History:
 def __init__(self,root):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
  self.messages=[];self.tools=None;self.next_index=0;self.store=ReasoningReplayStore();self.reasoning={};self.unanchored_reasoning={};self.transport_prefixes={}
  p=self.root/'state.json'
  if p.exists():
   d=json.loads(p.read_text());self.messages=d['messages'];self.tools=d['tools'];self.next_index=d['next_index'];self.reasoning=d['reasoning'];self.unanchored_reasoning=d.get('unanchored_reasoning',{});self.transport_prefixes=d.get('transport_prefixes',{})
   for call,items in self.reasoning.items():self.store.record(call,items)

 def save(self):
  codex_bridge.write(self.root/'state.json',dict(messages=self.messages,tools=self.tools,next_index=self.next_index,reasoning=self.reasoning,unanchored_reasoning=self.unanchored_reasoning,transport_prefixes=self.transport_prefixes))

 def ingest(self,payload,index):
  if index!=self.next_index:raise RuntimeError('Context index differs; reconcile existing request/response before continuing')
  path=self.root/f'input-{index:04d}.json'
  if path.exists():
   previous=json.loads(path.read_text())
   if previous['incoming_request_sha256']!=digest(payload):raise RuntimeError('Refusing to replace immutable archived input')
   current=digest(self.messages)
   if current==previous['full_archive_sha256']:
    # Ingest can finish before quota/preflight holds an unpaid dispatch. Reuse
    # its exact receipt rather than treating the same observations as new.
    if self.tools!=payload['tools']:raise RuntimeError('Tool contract changed within episode')
    return self.project()
   if current!=previous['prior_full_archive_sha256']:raise RuntimeError('Archived input and context state disagree; reconcile before continuing')
   # The immutable input landed before state.json in a process interruption.
   # Reconstruct only this already-authorized input; this makes no model call.
  messages=copy.deepcopy(payload['messages'])
  if len(messages)<len(self.messages):raise RuntimeError('Prior message history was truncated')
  if self.tools is not None and self.tools!=payload['tools']:raise RuntimeError('Tool contract changed within episode')
  if not self.messages and any(m.get('role')=='assistant' for m in messages):raise RuntimeError('Cannot start mid-episode without its archived reasoning and images')
  n=len(self.messages)
  if without_images(messages[:n])!=without_images(self.messages):raise RuntimeError('Prior text/action/feedback history changed')
  # Existing images may be replaced by the official omission marker, but cannot
  # be replaced by different pixels or different scene observations.
  for old,new in zip(self.messages,messages[:n]):
   if isinstance(old.get('content'),list):
    for a,b in zip(old['content'],new['content']):
     if a.get('type')=='image_url' and b.get('type')=='image_url' and a!=b:raise RuntimeError('A historical image changed')
  for message in messages:
   if message.get('role')=='assistant':
    for call in message.get('tool_calls',[]):
     if call['id'] not in self.reasoning:raise RuntimeError('Missing archived reasoning receipt for prior action '+call['id'])
  full=self.messages+messages[n:]
  record=dict(index=index,new_messages=messages[n:],incoming_request_sha256=digest(payload),prior_full_archive_sha256=digest(self.messages),full_archive_sha256=digest(full))
  if path.exists() and json.loads(path.read_text())!=record:raise RuntimeError('Refusing to replace immutable archived input')
  codex_bridge.write(path,record)
  self.messages=full;self.tools=copy.deepcopy(payload['tools']);self.save()
  return self.project()

 def project(self):
  view=copy.deepcopy(self.messages)
  _compact_message_history_in_place(view,image_horizon=2)
  if without_images(view)!=without_images(self.messages):raise RuntimeError('Projection changed non-image content')
  history=native_items([m for m in view if m.get('role')!='system'],self.store,self.transport_prefixes)
  reasons=[x for x in history if x.get('type')=='reasoning']
  expected=sum(len(self.store.items_for(m['tool_calls'][0]['id'])) for m in view if m.get('role')=='assistant' and m.get('tool_calls'))
  expected+=sum(x.get('type')=='reasoning' for k,v in self.transport_prefixes.items() if int(k)<len([m for m in view if m.get('role')!='system']) for x in v['items'])
  assert len(reasons)==expected
  audit=dict(index=self.next_index,archived_images=image_count(self.messages),active_images=image_count(view),reasoning_items=len(reasons),text_actions_feedback_sha256=digest(without_images(view)),full_history_sha256=digest(self.messages),model_history_sha256=digest(history),reasoning_item_sha256=[digest(x) for x in reasons],image_horizon=2,protected_official_demonstration_watch_turns_preserved=True)
  audit['no_tool_reasoning_archived_not_replayed']=dict(response_indices=sorted(self.unanchored_reasoning,key=int),item_count=sum(len(items) for items in self.unanchored_reasoning.values()),reason='Official ReasoningReplayStore anchors reasoning to the first tool call; text-only or empty responses have no anchor.')
  codex_bridge.write(self.root/f'projection-{self.next_index:04d}.json',audit)
  return view,history,audit

 def record(self,index,response,reasoning_items,reasoning_tokens=None,*,transport_prefix=None):
  if index!=self.next_index:raise RuntimeError('Duplicate or out-of-order model receipt')
  calls=response['choices'][0]['message'].get('tool_calls') or []
  if reasoning_tokens is not None and reasoning_tokens>0 and not reasoning_items:raise RuntimeError('Billed reasoning is missing from raw model receipt')
  if any(not x.get('encrypted_content') for x in reasoning_items):raise RuntimeError('Reasoning lacks replayable encrypted content')
  call_ids=[call.get('id') for call in calls]
  if any(not isinstance(call,str) or not call for call in call_ids) or len(set(call_ids))!=len(call_ids):raise RuntimeError('Missing or duplicate tool call IDs; cannot anchor reasoning safely')
  if any(call in self.reasoning for call in call_ids):raise RuntimeError('Tool call ID was reused; refusing to overwrite earlier reasoning')
  anchor=call_ids[0] if call_ids else None
  receipt=dict(index=index,response=response,reasoning_items=reasoning_items,reasoning_anchor_call_id=anchor,no_tool_reasoning_archived_not_replayed=bool(reasoning_items and not calls))
  if transport_prefix:
   position=str(len([m for m in self.messages if m.get('role')!='system']))
   if position in self.transport_prefixes:raise RuntimeError('Retry context anchor already occupied')
   extra=dict(items=copy.deepcopy(transport_prefix),following_message_sha256=digest(response['choices'][0]['message']),logical_index=index)
   self.transport_prefixes[position]=extra;receipt['transport_prefix']=extra
  path=self.root/f'output-{index:04d}.json'
  if path.exists():raise RuntimeError('Completed receipt already exists; never generate it twice')
  codex_bridge.write(path,receipt)
  # Match the official converter: one reasoning batch belongs to the first
  # call, including when the native EEF policy later merges disjoint calls.
  # Keep empty entries for the other call IDs as provenance, without replaying
  # the same reasoning repeatedly. Native policy owns repairs/normalization.
  for call in call_ids:self.reasoning[call]=copy.deepcopy(reasoning_items) if call==anchor else []
  self.store.record(anchor,reasoning_items)
  if not calls and reasoning_items:self.unanchored_reasoning[str(index)]=copy.deepcopy(reasoning_items)
  self.next_index+=1;self.save()
