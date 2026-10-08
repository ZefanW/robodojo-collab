"""Official capability weighting without treating missing/duplicate results as zero."""
from __future__ import annotations
from collections import Counter, defaultdict
from hashlib import sha256
import statistics as st
from .schema import CAPABILITIES, canonical_bytes


def moments(values):
    return {'n':len(values),'mean':st.mean(values) if values else None,
            'sample_variance':st.variance(values) if len(values)>1 else None,
            'sample_sd':st.stdev(values) if len(values)>1 else None,
            'min':min(values) if values else None,'max':max(values) if values else None}


def signature(run):
    # Exact protocol/client/prompt/tool locks avoid a causal model-only comparison claim.
    return {'algorithm':run['algorithm'],'protocol':run['protocol']}


def cost_summary(runs):
    fields=('input_tokens','cached_input_tokens','output_tokens','paid_requests','model_responses')
    total={k:0 for k in fields};unknown=0;missing={k:0 for k in fields};seen=set()
    for r in runs:
        for a in r['costs']['attempts']:
            key=(r['run_id'],a['attempt_id'])
            if key in seen:continue
            seen.add(key)
            if not a['usage_known']:unknown+=1
            for k in fields:
                if a[k] is None:missing[k]+=1
                else:total[k]+=a[k]
    return {'known_input_tokens':total['input_tokens'],'known_cached_input_tokens':total['cached_input_tokens'],
            'known_uncached_input_tokens':total['input_tokens']-total['cached_input_tokens'] if not missing['input_tokens'] and not missing['cached_input_tokens'] else None,
            'known_output_tokens':total['output_tokens'],'known_total_tokens':total['input_tokens']+total['output_tokens'],
            'paid_requests':total['paid_requests'] if not missing['paid_requests'] else None,
            'paid_requests_lower_bound':total['paid_requests'],'model_responses_lower_bound':total['model_responses'],
            'unknown_attempts':unknown,'unknown_by_field':missing,'complete':not any(missing.values()) and unknown==0,
            'cache_is_input_subset':True,'attempt_records':len(seen)}


def valid(r):
    o=r['outcome']
    return r['status']=='complete' and o['evidence_consistent'] is True and o['native_result'] is True and o['episode_complete'] is True and not o['unstable_envs'] and o['score'] is not None and o['success'] is not None


def weighted(task_values,universe):
    caps={}
    for cap in CAPABILITIES:
        tasks=[t for t,m in universe.items() if m['capability']==cap]
        groups=[[t for t in tasks if universe[t]['variant']==v] for v in ('standard','random')] if cap=='Generalization' else [tasks]
        complete=all(groups) and all(t in task_values for t in tasks)
        caps[cap]={'complete':bool(complete),'planned':len(tasks),'valid':sum(t in task_values for t in tasks),
                   'score':st.mean(st.mean(task_values[t]['score'] for t in g) for g in groups) if complete else None,
                   'success_rate':st.mean(st.mean(task_values[t]['success_rate'] for t in g) for g in groups) if complete else None}
    complete=len(universe)==54 and all(c['complete'] for c in caps.values())
    return {'complete':complete,'score':st.mean(c['score'] for c in caps.values()) if complete else None,
            'success_rate':st.mean(c['success_rate'] for c in caps.values()) if complete else None,'capabilities':caps}


def official_summary(runs,universe,structural_missing=()):
    expected=set(universe)-set(structural_missing)
    counts=Counter(r['scene']['task'] for r in runs if r['attempt']['index']==0)
    repeated=[r['run_id'] for r in runs if r['attempt']['index']!=0]
    metadata_bad=[]; chosen={}
    for r in runs:
        s=r['scene'];task=s['task']
        if task not in expected or r['attempt']['index']!=0 or counts[task]!=1:continue
        if (s['capability'],s['variant'])!=(universe[task]['capability'],universe[task]['variant']):metadata_bad.append(task);continue
        if valid(r):chosen[task]={'score':r['outcome']['score']*100,'success_rate':100*float(r['outcome']['success'])}
    out=weighted(chosen,universe)
    duplicates=sorted(t for t,n in counts.items() if n>1)
    unknown=sorted(set(counts)-expected)
    complete=out['complete'] and not duplicates and not unknown and not metadata_bad and not structural_missing
    if not complete:out.update(complete=False,score=None,success_rate=None)
    out.update(round_complete=bool(expected) and expected==set(chosen) and not duplicates and not unknown,
               valid=len(chosen),planned=len(expected),missing_or_incomplete=sorted(expected-set(chosen)),
               structural_missing_tasks=sorted(structural_missing),duplicate_tasks=duplicates,
               unexpected_tasks=unknown,metadata_mismatches=metadata_bad,excluded_repeat_attempts=repeated,
               selection_policy='attempt index 0 only; duplicate originals invalidate the task; repeats remain visible',
               aggregation='Five equal capability weights; Generalization standard/random half each; incomplete overall null')
    return out


def cumulative_summary(runs,universe):
    identities=Counter((r['scene']['task'],r['scene']['official_seed'],r['scene']['layout_ordinal']) for r in runs if r['attempt']['index']==0)
    values=defaultdict(list);hash_identity=defaultdict(set);excluded=[]
    for r in runs:
        s=r['scene'];task=s['task'];ident=(task,s['official_seed'],s['layout_ordinal'])
        if r['attempt']['index']!=0 or identities[ident]!=1 or not valid(r) or task not in universe:
            excluded.append(r['run_id']);continue
        if (s['capability'],s['variant'])!=(universe[task]['capability'],universe[task]['variant']):
            excluded.append(r['run_id']);continue
        values[task].append(r);hash_identity[(task,s['asset_sha256'])].add((s['official_seed'],s['layout_ordinal']))
    by_task={};task_means={}
    for t in universe:
        rr=values[t];vv=[r['outcome']['score']*100 for r in rr]
        by_task[t]={**moments(vv),'unique_geometry_count':len({r['scene']['asset_sha256'] for r in rr}),
                    'success_rate':100*st.mean(float(r['outcome']['success']) for r in rr) if rr else None,
                    'environments':sorted({r['environment']['simulator_version'] or 'unknown' for r in rr})}
        if rr:task_means[t]={'score':by_task[t]['mean'],'success_rate':by_task[t]['success_rate']}
    out=weighted(task_means,universe)
    out.update(tasks=by_task,task_coverage=len(task_means),planned_tasks=len(universe),valid_unique_runs=sum(len(v) for v in values.values()),
               duplicate_scene_identities=[list(k) for k,v in identities.items() if v>1],excluded_runs=excluded,
               shared_geometry=[{'task':k[0],'asset_sha256':k[1],'identities':[list(x) for x in sorted(v)]} for k,v in hash_identity.items() if len(v)>1],
               aggregation='Task means across unique declared official scene identities, then official capability weights. Shared asset SHA is explicitly disclosed; n is not independent geometry count.')
    return out


def summarize(runs,task_registry,scene_registry=None):
    universe={r['task']:r for r in task_registry['tasks']};groups=defaultdict(list);result=[]
    for r in runs:groups[canonical_bytes(signature(r))].append(r)
    for sig,rr in sorted(groups.items()):
        panels=defaultdict(list)
        for r in rr:
            s=r['scene'];panels[(s['official_seed'],s['layout_ordinal'],s['round_index'])].append(r)
        result.append({'group_id':sha256(sig).hexdigest()[:16],'algorithm_id':rr[0]['algorithm']['algorithm_id'],
                       'protocol_id':rr[0]['protocol']['id'],'signature':signature(rr[0]),
                       'panels':[{'official_seed':k[0],'layout_ordinal':k[1],'round_index':k[2],**official_summary(v,universe,
                           structural_missing=[task for task in universe if not any(entry['layout_ordinal']==k[1] for entry in scene_registry.get(str(k[0]),{}).get(task,[]))] if scene_registry is not None else ())} for k,v in sorted(panels.items())],
                       'cumulative':cumulative_summary(rr,universe),'costs':cost_summary(rr),
                       'run_count':len(rr),'environment_variants':sorted({r['environment']['simulator_version'] or 'unknown' for r in rr})})
    return {'groups':result}
