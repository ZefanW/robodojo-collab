"""Bounded same-step recovery; no provider calls or simulator mutations here."""
import hashlib
import json
import re
from pathlib import Path

FEEDBACK = ('Transport correction only: the previous attempt was interrupted before any robot action. '
            'The robot observation and pending decision are unchanged. Preserve the supplied history. '
            'Do not invoke host tools or ask the user. Return the requested assistant JSON envelope '
            'using only the already supplied move_eef/give_up definitions. No prior action should be regenerated.')


def read(path):return json.loads(Path(path).read_text())
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def validate_authorization(auth, account=None):
    if (auth.get('automatic_retry_authorized') is not True or
        auth.get('max_additional_attempts_per_pending_step')!=2 or
        auth.get('backoff_seconds')!=[10,30] or
        'GPT6 L3 context-v2 original Devset1' not in auth.get('scope',[]) or
        not auth.get('explicit_user_text') or auth.get('completed_cases_immutable') is not True):
        raise RuntimeError('Explicit bounded same-step retry authorization missing')
    return auth


def journal_items(path):
    rows=[json.loads(line) for line in Path(path).open()]
    items=[r['payload'] for r in rows if r.get('type')=='response_item']
    return rows,items


def retryable_attempt(folder, request_sha, *, expected_account=None):
    """Prove an interrupted paid turn returned no external information/action.

    Only the narrowly identified transport mistakes qualify. A provider refusal,
    unknown tool result, active turn or successful reply requires reconciliation.
    """
    folder=Path(folder);start=read(folder/'paid-start.json');thread=read(folder/'thread.json')
    if start['request_sha256']!=request_sha:raise RuntimeError('Retry pending request differs')
    if expected_account and start.get('account_id')!=expected_account:raise RuntimeError('Retry account changed')
    if thread.get('model')!='gpt-6-astra' or thread.get('reasoningEffort')!='medium' or thread.get('instructionSources'):
        raise RuntimeError('Retry model/information profile differs')
    if (folder/'response.json').exists():raise RuntimeError('A paid reply exists; reconcile and reuse instead of retry')
    hold=read(folder/'context-hold.json');error=hold.get('error','')
    if any(word in error.lower() for word in ('refusal','safety','policy_violation','compaction','quota','allowance','account')):
        raise RuntimeError('This hold is not an automatically retryable transport error')
    if not any(word in error for word in ('Unexpected raw response item','Unexpected raw host tool','Host tool request forbidden','Paid transport error','Paid completion incomplete','Invalid transport','JSONDecodeError','TimeoutError')):
        raise RuntimeError('Unclassified paid failure; retain hold')
    path=Path(thread['thread']['path']);rows,items=journal_items(path)
    if thread['thread']['id']!=start['thread_id']:raise RuntimeError('Retry original native identity differs')
    turn=read(folder/'paid-turn.json').get('turn_id') if (folder/'paid-turn.json').exists() else None
    if turn is None:
        candidates=[r['payload']['turn_id'] for r in rows if r.get('type')=='event_msg' and r.get('payload',{}).get('type')=='task_started']
        if len(candidates)!=1:raise RuntimeError('Original interrupted turn is ambiguous')
        turn=candidates[0]
    begin=next((i for i,r in enumerate(rows) if r.get('type')=='event_msg' and r.get('payload',{}).get('type')=='task_started' and r['payload'].get('turn_id')==turn),None)
    if begin is None:raise RuntimeError('Paid turn not present in native journal')
    terminal=[r['payload'] for r in rows[begin:] if r.get('type')=='event_msg' and r.get('payload',{}).get('turn_id')==turn and r['payload'].get('type') in ('turn_aborted','task_complete')]
    if not terminal:raise RuntimeError('Original paid turn may still be active')
    if any(r.get('type')=='compacted' for r in rows):raise RuntimeError('Cannot retry a compacted original thread')
    tail=[r['payload'] for r in rows[begin:] if r.get('type')=='response_item']
    calls={};outputs={}
    for item in tail:
        kind=item.get('type')
        if kind=='reasoning':
            if not item.get('encrypted_content'):raise RuntimeError('Failed-attempt reasoning is not replayable')
        elif kind=='function_call':
            if item.get('name') not in ('request_user_input','request_user_input_async','wait'):
                raise RuntimeError('Unknown host operation is not retryable')
            calls[item['call_id']]=item
        elif kind=='function_call_output':
            output=item.get('output')
            call=calls.get(item.get('call_id'))
            verified=(call is not None and isinstance(output,str) and
                ((call.get('name')=='wait' and output=='code-mode host is disabled') or
                 (call.get('name')=='request_user_input' and output=='request_user_input is unavailable in Default mode') or
                 (call.get('name') in ('request_user_input','request_user_input_async') and re.fullmatch(r'aborted by user after [0-9.]+s',output))))
            if not verified:
                raise RuntimeError('Unverified host output; preserve information-boundary hold')
            outputs[item['call_id']]=item
        elif kind=='custom_tool_call':
            if item.get('name')!='exec':raise RuntimeError('Unknown host operation is not retryable')
            calls[item['call_id']]=item
        elif kind=='custom_tool_call_output':
            if item.get('call_id') not in calls or item.get('output')!='code-mode host is disabled':raise RuntimeError('Non-disabled host execution')
            outputs[item['call_id']]=item
        elif kind=='message':
            if item.get('role')=='user':
                if item.get('content')!=[dict(type='input_text',text=FEEDBACK)]:raise RuntimeError('Unexpected external user message in failed turn')
            elif item.get('role')!='assistant':raise RuntimeError('Unexpected external message in failed turn')
            if item.get('refusal') or any(p.get('type')=='refusal' or p.get('refusal') for p in item.get('content',[]) if isinstance(p,dict)):
                raise RuntimeError('Provider refusal is not retryable')
        else:raise RuntimeError('Unknown failed-turn information item')
    if set(calls)!=set(outputs):raise RuntimeError('Unresolved host request; do not retry')
    raw=read(folder/'raw-output.json') if (folder/'raw-output.json').exists() else []
    # The on-disk raw stream can stop immediately at the forbidden request; the
    # native journal then adds its automatic interruption acknowledgement.
    pos=0
    for item in raw:
        while pos<len(tail) and digest(tail[pos])!=digest(item):pos+=1
        if pos==len(tail):raise RuntimeError('Failed raw output differs from preserved native journal')
        pos+=1
    tail=[x for x in tail if not (x.get('type')=='message' and x.get('role')=='user')]
    return dict(thread_id=start['thread_id'],turn_id=turn,journal_path=str(path),
                journal_item_sha256=[digest(x) for x in items],failed_turn_items=tail,
                failed_turn_reasoning_count=sum(x.get('type')=='reasoning' for x in tail),
                usage_status='reported' if (folder/'usage.json').exists() else 'unknown_not_zero',
                request_sha256=request_sha,no_robot_action=True,host_output_verified=True)


def attempt_folders(folder):
    folder=Path(folder)
    return [folder]+sorted((folder/'retries').glob('[0-9][0-9][0-9]'))


def selected_folder(folder):
    folder=Path(folder);marker=folder/'selected-attempt.json'
    if not marker.exists():return folder
    relative=read(marker)['attempt_path']
    if not re.fullmatch(r'retries/00[12]',relative):raise RuntimeError('Invalid selected retry receipt path')
    return folder/relative
