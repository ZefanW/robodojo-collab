"""Recover completed-turn evidence from Codex's native append-only journal.

thread/resume has no experimentalRawEvents option in the pinned schema. After
an app-server restart, its journal remains the authoritative source of opaque
items and per-response token_usage_record IDs. These are not fabricated API
notifications and never include cumulative usage from another paid turn.
"""
import hashlib
import json
from pathlib import Path

FIELDS={'inputTokens':'input_tokens','cachedInputTokens':'cached_input_tokens',
        'outputTokens':'output_tokens','reasoningOutputTokens':'reasoning_output_tokens',
        'totalTokens':'total_tokens'}


def completed_turn(path,thread_id,turn_id):
    raw=Path(path).read_bytes();rows=[json.loads(line) for line in raw.splitlines()]
    starts=[i for i,e in enumerate(rows) if e.get('type')=='event_msg' and e.get('payload',{}).get('type')=='task_started' and e['payload'].get('turn_id')==turn_id]
    if len(starts)!=1:raise RuntimeError('Native completed turn start is ambiguous')
    start=starts[0];tail=[];complete=False
    for e in rows[start+1:]:
        p=e.get('payload',{})
        if e.get('type')=='event_msg' and p.get('type')=='task_started':break
        tail.append(e)
        if e.get('type')=='event_msg' and p.get('type')=='task_complete' and p.get('turn_id')==turn_id:complete=True;break
        if e.get('type') in ('compacted','context_compaction'):raise RuntimeError('Native history compacted during recovery')
    if not complete:raise RuntimeError('Native turn did not complete; never reuse partial output')
    generated=[];host_inputs=[];events={}
    for e in tail:
        p=e.get('payload',{})
        if e.get('type')=='response_item':
            if p.get('type')=='message' and p.get('role')=='user':
                from context_v2.retry import FEEDBACK
                neutral=p.get('content')==[dict(type='input_text',text=FEEDBACK)]
                meta=p.get('internal_chat_message_metadata_passthrough',{})
                env=(meta.get('content_item_kinds')==['environments.environment_context'] and
                     len(p.get('content',[]))==1 and p['content'][0].get('text','').startswith('<environment_context>') and
                     p['content'][0].get('text','').endswith('</environment_context>'))
                if not (neutral or env):raise RuntimeError('Unexpected user input during saved paid turn')
                host_inputs.append(p);continue
            if p.get('type')=='reasoning' and not p.get('encrypted_content'):raise RuntimeError('Opaque reasoning missing')
            if p.get('type')=='message' and (p.get('refusal') or any(v.get('type')=='refusal' or v.get('refusal') for v in p.get('content',[]))):raise RuntimeError('Explicit refusal cannot be repaired')
            generated.append(p)
        if e.get('type')=='token_usage_record':
            if p.get('thread_id')!=thread_id or p.get('turn_id')!=turn_id:raise RuntimeError('Native response usage belongs to another turn')
            rid=p.get('response_id');usage=p.get('usage')
            if not rid or not isinstance(usage,dict):raise RuntimeError('Native response usage lacks exact ID')
            counts={k:usage.get(v,0) for k,v in FIELDS.items()}
            if any(type(v) is not int or v<0 for v in counts.values()) or counts['totalTokens']!=counts['inputTokens']+counts['outputTokens']:raise RuntimeError('Invalid native per-response token counts')
            value=dict(threadId=thread_id,turnId=turn_id,responseId=rid,usage=counts,
                       provenance='native journal token_usage_record; not rawResponse/completed')
            if rid in events and events[rid]!=value:raise RuntimeError('Conflicting native response ID')
            events[rid]=value
    if not events:raise RuntimeError('Native completed turn lacks per-response usage records')
    messages=[x for x in generated if x.get('type')=='message' and x.get('role')=='assistant']
    texts=[''.join(v.get('text','') for v in x.get('content',[]) if v.get('type')=='output_text') for x in messages]
    if not texts or not texts[-1]:raise RuntimeError('Native completed turn has no final assistant response')
    counts={k:sum(v['usage'][k] for v in events.values()) for k in FIELDS}
    return dict(raw=generated,reasoning=[x for x in generated if x.get('type')=='reasoning'],
                responses=list(events.values()),usage=counts,texts=texts,
                evidence=dict(journal_path=str(path),journal_sha256=hashlib.sha256(raw).hexdigest(),
                  thread_id=thread_id,turn_id=turn_id,source='native journal response_item and token_usage_record',
                  provider_response_ids=list(events),turn_host_inputs=host_inputs,paid_calls_for_recovery=0))


def restore_artifacts(folder):
    """Write only missing evidence for an already completed paid turn."""
    folder=Path(folder);t=json.loads((folder/'thread.json').read_text());turn=json.loads((folder/'paid-turn.json').read_text())
    data=completed_turn(t['thread']['path'],turn['thread_id'],turn['turn_id'])
    from context_v2.bridge import audit_host_items,decode_completion
    audit_host_items(data['raw'],final=True);decode_completion(json.loads(data['texts'][-1]),turn['turn_id'])
    if (folder/'assistant-text.json').exists() and json.loads((folder/'assistant-text.json').read_text())!=data['texts']:raise RuntimeError('Native assistant text differs from saved paid output')
    values={'raw-output.json':data['raw'],'raw-reasoning.json':data['reasoning'],
            'journal-response-receipts.json':data['responses'],'usage.json':data['usage'],
            'journal-recovery.json':data['evidence'],'assistant-text.json':data['texts']}
    for name,value in values.items():
        target=folder/name
        if target.exists():
            if json.loads(target.read_text())!=value:raise RuntimeError('Refusing to overwrite original receipt: '+name)
        else:target.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return data
