"""Offline projection of SHA-verified original VLA evidence; never runs a policy."""
from __future__ import annotations
import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from .export_legacy import public
from .publication import MANIFEST_NAME, _publication, validate_publication, validate_panel_registry
from .schema import (HEX, IDENT, ValidationError, canonical_bytes, file_sha256,
    native_event_payload, privacy_findings, validate_manifest, validate_registered_scene,
    native_standard42_media, NATIVE_STANDARD42_PROTOCOL, NATIVE_STANDARD42_DEMO_POLICY, STANDARD42_SOURCE_SHA256)

VIEWS = {'head', 'left_wrist', 'right_wrist'}
EVENT_FIELDS = {
    'reset_start': ('args', 'kwargs'), 'reset_complete': ('step_limit',),
    'episode_start': (), 'episode_complete': ('native_results', 'unstable_envs'),
    'action_submit': ('actions', 'kwargs'),
    'action_complete': ('elapsed_s', 'native_end', 'native_success'),
    'policy_rpc': ('method', 'elapsed_s', 'result'),
}
COMMON_FIELDS = ('kind', 'time_unix', 'layout_by_env', 'control_steps')


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _record(value):
    if isinstance(value, (str, Path)):
        path = Path(value)
        if path.is_symlink():
            raise ValidationError('Native source record symlinks are prohibited')
        return _read(path), file_sha256(path)
    return deepcopy(value), hashlib.sha256(canonical_bytes(value)).hexdigest()


def _verified(path, sha, size=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValidationError('Native source is missing or is a symlink: ' + path.name)
    if not isinstance(sha, str) or not HEX.fullmatch(sha) or file_sha256(path) != sha:
        raise ValidationError('Native source SHA256 mismatch: ' + path.name)
    if size is not None and path.stat().st_size != size:
        raise ValidationError('Native source byte count mismatch: ' + path.name)
    return path


def _terminal_line(item):
    path = _verified(item['original_line_path'], item['source_line_sha256'])
    data = json.loads(path.read_bytes())
    if data != item['event']:
        raise ValidationError('Native terminal event differs from its original line')
    return data


def _source_metadata(record):
    path = _verified(record['source_metadata_path'], record['source_metadata_sha256'])
    data = _read(path)
    if data.get('run_id') != record['run_id']:
        raise ValidationError('Original source metadata belongs to another run')
    return data


def _configuration(value):
    # Older native audits stored a Python-literal repr rather than a JSON object.
    # Parse data only; never eval or execute historical configuration content.
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError) as exc:
            raise ValidationError('Original policy configuration is not a safe literal mapping') from exc
    if not isinstance(value, dict):
        raise ValidationError('Original policy configuration must be a mapping')
    return value


def native_vla_metadata(record_or_path, scene_registry, *, profile="full54", task_registry=None):
    """Derive reviewable public metadata without promoting current files to old locks.

    The common algorithm identifies the recorded model family. Per-run launch
    aliases, simulator configuration and original evidence stay in source_lock.
    Unknown historical checkpoint/source hashes stay null.
    """
    record, source_sha = _record(record_or_path)
    if profile not in ('full54', 'standard42'):
        raise ValidationError('Native metadata profile must be full54 or explicit standard42')
    if profile == 'standard42':
        if task_registry is None:
            raise ValidationError('Standard42 native metadata requires its explicit pinned task registry')
        _, universe = validate_panel_registry(task_registry, 'standard42')
        task = record.get('task')
        scene = record.get('scene', {})
        if task not in universe or any(scene.get(k) != universe[task][k] for k in ('capability', 'variant')):
            raise ValidationError('Native record does not match the fixed original Standard42 roster')
    source = _source_metadata(record)
    model = record['model']
    if model not in {'dm05', 'openwam', 'spatial_forcing', 'g05', 'pi05'}:
        raise ValidationError('Unreviewed native VLA model family')
    seed, layout, task = record['evaluation_seed'], record['layout_ordinal'], record['task']
    entries = scene_registry.get(str(seed), {}).get(task, [])
    matches = [entry for entry in entries if entry['layout_ordinal'] == layout]
    if len(matches) != 1 or matches[0]['layout_sha256'] != record['scene']['layout_sha256']:
        raise ValidationError('Original native scene SHA differs from official inventory')
    entry = matches[0]
    launches = []
    for row in source.get('audit_source_metadata', []):
        event = row.get('event', {})
        if event.get('kind') != 'audit_installed':
            continue
        config = _configuration(event.get('configuration', {}))
        policy_config = _configuration(event.get('policy_configuration', {}))
        if policy_config.get('evaluation_id') not in (None, record['run_id']):
            raise ValidationError('Original policy configuration belongs to another native run')
        launches.append({'source_line_sha256': row['source_line_sha256'],
            'task': event.get('task'), 'evaluation_seed': event.get('evaluation_seed'),
            'configuration': public({key: config[key] for key in ('config_name', 'config', 'observation',
                'task_name', 'num_envs', 'eval_batch', 'policy_name', 'additional_info', 'seed') if key in config}),
            'policy_configuration': public({key: policy_config[key]
                for key in ('policy_name', 'evaluation_id', 'trial_id', 'action_case_id', 'repeat_index')
                if key in policy_config})})
    if not launches or any(x['task'] != task or x['evaluation_seed'] != seed for x in launches):
        raise ValidationError('Original audit launch task/seed evidence missing or inconsistent')
    historical = source.get('historical_source_record', {})
    limitations = [
        'Historical checkpoint weight hash and adapter source commit/hash were not recorded; current files are not historical locks.',
        'The algorithm/checkpoint name identifies the recorded model family, not a verified byte-identical checkpoint across historical environments.',
        'Original per-run launch aliases and simulator differences are retained in source_lock and environment; this is not a model-only causal comparison.',
        'Policy action requests count original get_action/get_action_batch RPC boundaries; internal neural forward count is unmeasured.',
        'LLM tokens and paid LLM requests are not applicable. GPU hours and billing are unknown.',
        'Collected infrastructure attempts are retained; unrecorded earlier attempts cannot be assumed absent.',
        'No natural-language reasoning or public note was generated for native policy actions.',
    ]
    # The native episode cap is a configuration, not the observed terminal count.
    reset_limit = None
    events = _read_events(record)
    limits = {e['step_limit'] for e in events if e['kind'] == 'reset_complete' and type(e.get('step_limit')) is int}
    if len(limits) == 1:
        reset_limit = next(iter(limits))
    metadata = {'algorithm': {'algorithm_id': 'native_vla_' + model, 'version': 'historical-native-vla-v1',
        'model': model, 'source_commit': None, 'prompt_sha256': None, 'tools_sha256': None,
        'policy_sha256': None, 'reasoning_effort': None, 'codex_client_version': None,
        'checkpoint': {'name': model, 'sha256': None, 'revision': None,
                       'identity_basis': 'recorded model family; exact historical weight identity unavailable'}},
        'protocol': {'id': 'native-vla-original-full54-v1', 'version': '1', 'scope': 'historical-native-vla-import',
            'action_limit': None, 'episode_control_limit': reset_limit,
            'selection_policy': 'Original frozen Full54 inventory selection, independent of outcome; no rerun, replacement or missing-task zero fill.'},
        'scene': {'task': task, 'capability': record['scene']['capability'], 'variant': record['scene']['variant'],
            'official_seed': seed, 'layout_ordinal': layout, 'round_index': layout,
            'asset_path': entry['original_asset_path'], 'asset_sha256': entry['layout_sha256']},
        'environment': {'simulator_version': record['scene'].get('simulator'), 'machine_id': None,
            'gpu': None, 'driver': None, 'os': None, 'dependencies': {}},
        'source_lock': {'execution_kind': 'native_vla', 'source_record_sha256': source_sha,
            'source_metadata_sha256': record['source_metadata_sha256'], 'original_audit_sha256': record['audit']['sha256'],
            'original_native_result_sha256': record['native_result']['sha256'],
            'selected_original_events_sha256': record['selected_events_original_sha256'],
            'historical_checkpoint_sha256': None, 'historical_adapter_source_sha256': None,
            'original_launches': launches,
            'original_selection': {'model': historical.get('model'), 'panel_id': historical.get('panel_id'),
                'physical_identity': historical.get('physical_identity'),
                'reported_score_percent': historical.get('score_0_to_100'), 'reported_success': historical.get('success'),
                'reported_control_steps': historical.get('control_steps_reported'),
                'reported_policy_decisions': historical.get('vla_decisions_reported')},
            'limitations': limitations},
        'limitations': limitations, 'contributor_id': 'maintainer-native-archive'}
    if profile == 'standard42':
        metadata['protocol'].update(id=NATIVE_STANDARD42_PROTOCOL, metric_profile='standard42',
            roster_id='standard42-v1', roster_source_sha256=STANDARD42_SOURCE_SHA256,
            demo_policy=NATIVE_STANDARD42_DEMO_POLICY,
            selection_policy='Original fixed 42 standard task configurations; no random results, rerun, replacement or missing-task zero fill.')
        metadata['source_lock']['original_selection'].update(metric_profile='standard42',
            roster_id='standard42-v1', roster_source_sha256=STANDARD42_SOURCE_SHA256)
        limitations.append('Standard42 is the fixed original standard-task subset, not Full54; each capability has 20% weight.')
        if record.get('demo') is None:
            if record.get('demo_available') is not False:
                raise ValidationError('Absent original Standard42 demo must be explicitly recorded as unavailable')
            limitations.append('No original demo was indexed; the three original native camera videos are retained without a generated or borrowed replacement.')
    return metadata


def _read_events(record):
    original = _verified(record['selected_events_original_path'], record['selected_events_original_sha256'])
    projected = _verified(record['native_events_path'], record['native_events_sha256'], record.get('native_events_bytes'))
    raw_lines = original.read_bytes().splitlines(keepends=True)
    events = [json.loads(line) for line in projected.read_text().splitlines() if line.strip()]
    if len(raw_lines) != len(events) or not events:
        raise ValidationError('Selected original event lines are missing or incomplete')
    last_line = 0
    for raw, event in zip(raw_lines, events):
        if hashlib.sha256(raw).hexdigest() != event.get('source_line_sha256'):
            raise ValidationError('Original native event line SHA mismatch')
        data = json.loads(raw)
        if native_event_payload(event) != data:
            raise ValidationError('Native event projection changed original numeric actions or feedback')
        line = event.get('source_line_number')
        if type(line) is not int or line <= last_line:
            raise ValidationError('Original native event line order is ambiguous')
        last_line = line
        if event.get('kind') not in EVENT_FIELDS:
            raise ValidationError('Non-allowlisted native event kind')
    return events


def export_native_vla(record_or_path, destination, *, metadata, scene_registry, provenance=None):
    """Write immutable lean source + publication manifests from existing local bytes.

    No HTTP, model, simulator, checkpoint loading, trajectory synthesis or retries.
    destination is the exact new run bundle directory, never the collector input.
    """
    record, source_sha = _record(record_or_path)
    if not isinstance(record.get('run_id'), str) or not IDENT.fullmatch(record['run_id']):
        raise ValidationError('Unsafe original native run identity')
    for field in ('collection_complete', 'selected_episode_complete', 'event_boundary_complete'):
        if record.get(field) is not True:
            raise ValidationError('Native source evidence gate not complete: ' + field)
    if record.get('env_index') != 0 or type(record.get('episode_id')) is not int:
        raise ValidationError('Original single-env native episode identity required')
    source = _source_metadata(record)
    original_result = _verified(record['native_result']['local_path'], record['native_result']['sha256'], record['native_result'].get('bytes'))
    nr = _read(original_result)
    ep, final = _terminal_line(record['episode_complete']), _terminal_line(record['final_action_complete'])
    events = _read_events(record)
    expected_counts = record['audit'].get('selected_event_counts')
    if expected_counts is None and len(nr.get('details', {})) == 1:
        expected_counts = record['audit'].get('event_counts')
    if expected_counts is not None:
        actual_counts = Counter(e['kind'] for e in events)
        if any(actual_counts[kind] != expected_counts.get(kind, 0) for kind in EVENT_FIELDS):
            raise ValidationError('Selected native event counts omit original actions, RPCs or boundary events')
    actual_end = [e for e in events if e['kind'] == 'episode_complete']
    if len(actual_end) != 1 or native_event_payload(actual_end[-1]) != ep:
        raise ValidationError('Selected boundary must contain exactly the original terminal event')
    if native_event_payload(events[-1]) != ep:
        raise ValidationError('Selected episode trajectory must end at original episode_complete')
    if record['final_action_complete']['source_line_number'] >= record['episode_complete']['source_line_number']:
        raise ValidationError('Final native action ACK does not precede episode_complete')
    meta = deepcopy(metadata)
    if meta['scene']['task'] != record['task'] or meta['scene']['official_seed'] != record['evaluation_seed'] or meta['scene']['layout_ordinal'] != record['layout_ordinal'] or meta['scene']['asset_sha256'] != record['scene']['layout_sha256']:
        raise ValidationError('Public scene metadata differs from original collected identity')
    locks = record.get('algorithm_source_lock', {})
    algorithm = meta['algorithm']
    if algorithm.get('algorithm_id') != 'native_vla_' + record['model'] or algorithm.get('model') != record['model']:
        raise ValidationError('Native model identity differs from the original inventory')
    if (algorithm.get('source_commit') != locks.get('historical_source_commit') or
            algorithm.get('policy_sha256') != locks.get('historical_adapter_source_sha256') or
            algorithm.get('checkpoint', {}).get('sha256') != locks.get('historical_checkpoint_sha256')):
        raise ValidationError('Historical policy/checkpoint lock mismatch; current source hashes cannot substitute')
    if meta['protocol'].get('action_limit') is not None:
        raise ValidationError('Native VLA action_limit is unrecorded; prediction horizon cannot substitute')
    eid = record['episode_id']; item = nr.get('details', {}).get(str(eid))
    if not isinstance(item, dict):
        raise ValidationError('Selected original episode is absent from native result')
    historical = source.get('historical_source_record', {})
    if historical.get('score_0_to_100') != item['score'] * 100 or historical.get('success') is not item['success']:
        raise ValidationError('Original inventory outcome differs from native result; no result selection allowed')
    reported_controls = record.get('recorded_report_control_steps')
    if reported_controls is None:
        if (meta['protocol'].get('metric_profile') != 'standard42' or
                historical.get('source_kind') != 'historical_multi_episode' or
                'control_steps_reported' not in historical or historical['control_steps_reported'] is not None or
                type(record.get('observed_native_control_steps')) is not int or
                record['observed_native_control_steps'] != ep['control_steps'][0] or
                expected_counts is None):
            raise ValidationError('Unreported historical controls require explicit selected native observation and event coverage')
        # Keep the old report null. This observation is a separate measurement.
        meta['source_lock']['original_selection'].update(
            observed_native_control_steps=record['observed_native_control_steps'],
            observed_controls_basis='Original selected episode_complete and complete original action/ACK prefix; the historical report did not record controls.')
    elif reported_controls != ep['control_steps'][0]:
        raise ValidationError('Original recorded controls differ from native terminal')
    # Public event projection excludes unreviewed extra keys while keeping full numeric commands/results.
    safe_events = []
    for event in events:
        allowed = COMMON_FIELDS + EVENT_FIELDS[event['kind']] + ('source_line_number', 'source_line_sha256')
        safe_events.append({key: deepcopy(event[key]) for key in allowed if key in event})
    submits = [e for e in safe_events if e['kind'] == 'action_submit']
    completes = [e for e in safe_events if e['kind'] == 'action_complete']
    if len(submits) != len(completes):
        raise ValidationError('Missing original numeric action or native action ACK')
    turns = [{'kind': 'native_action', 'step': i + 1, 'control_start': a['control_steps'][0],
        'control_end': b['control_steps'][0], 'tool_call': {'name': 'native_action', 'arguments': {'actions': a['actions']}},
        'feedback': native_event_payload(b), 'source_line_sha256': a['source_line_sha256']}
        for i, (a, b) in enumerate(zip(submits, completes))]
    rpc = [e for e in safe_events if e['kind'] == 'policy_rpc']
    requests = sum(e.get('method') in ('get_action', 'get_action_batch') for e in rpc)
    trajectory = {'run_id': record['run_id'], 'execution_kind': 'native_vla', 'native_episode_id': eid,
        'turns': turns, 'native_events': safe_events,
        'limitations': ['Observations containing images are excluded; original numeric actions, policy RPC results and native feedback are retained.']}
    prior = record.get('cost_evidence', {}).get('prior_infrastructure_attempts_preserved_from_source', [])
    attempts = [{'attempt_id': record['run_id'] + '.episode-' + str(eid), 'scope': 'selected_episode',
        'source_sha256': record['audit']['sha256'], 'control_steps': ep['control_steps'][0],
        'policy_action_requests': requests, 'policy_rpc_calls': len(rpc),
        'vla_inference_calls': None, 'gpu_hours': None, 'gpu_dollar_cost': None}]
    for i, attempt in enumerate(prior):
        if not isinstance(attempt, dict):
            raise ValidationError('Original infrastructure attempt evidence must be an object')
        attempts.append({'attempt_id': str(attempt.get('attempt_id') or attempt.get('run_id') or 'recorded-infrastructure-' + str(i)),
            'scope': 'infrastructure_attempt', 'source_sha256': record['source_metadata_sha256'],
            'control_steps': attempt.get('control_steps'), 'policy_action_requests': attempt.get('policy_action_requests'),
            'policy_rpc_calls': attempt.get('policy_rpc_calls'), 'vla_inference_calls': None,
            'gpu_hours': None, 'gpu_dollar_cost': None,
            'recorded_failure': public({k:attempt[k] for k in ('status','error_type','failure_reason','stage') if k in attempt})})
    costs = {'execution_kind': 'native_vla', 'llm_cost_applicability': 'not_applicable',
        'attempts_complete': record.get('cost_evidence', {}).get('attempts_complete') is True,
        'gpu_hours': None, 'gpu_dollar_cost': None, 'vla_inference_calls': None,
        'policy_action_requests': requests, 'policy_rpc_calls': len(rpc), 'attempts': attempts,
        'limitations': ['Policy action requests are recorded RPC boundaries, not internal neural forward count.',
                        'Historical GPU usage/billing and completeness of earlier infrastructure attempts are not inferred.']}
    controls = ep['control_steps'][0]
    stamp = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat() if isinstance(t,(int,float)) else None
    m = {'schema_version': '1.0', 'execution_kind': 'native_vla', 'run_id': record['run_id'],
        'native_episode': {'episode_id': eid, 'env_index': 0, 'source_run_id': record['run_id']},
        **{key: meta[key] for key in ('algorithm', 'protocol', 'scene', 'environment')},
        'attempt': {'index': 0, 'contributor_id': meta.get('contributor_id', 'maintainer-native-archive'),
            'reason': 'Original frozen inventory native VLA episode; no new execution.', 'repeats_run_id': None},
        'status': 'complete', 'timestamps': {'started_at': stamp(events[0].get('time_unix')), 'finished_at': stamp(ep.get('time_unix'))},
        'outcome': {'native_result': True, 'episode_complete': True, 'score': item['score'], 'score_scale': '0..1',
            'success': item['success'], 'control_steps': controls, 'model_decisions': None, 'actual_responses': None,
            'policy_action_requests': requests, 'policy_rpc_calls': len(rpc), 'vla_inference_calls': None,
            'unstable_envs': [], 'evidence_consistent': True},
        'costs': costs, 'artifacts': [],
        'audit': {'session_public_id': None, 'export_policy': 'native-vla-allowlisted-v1', 'redactions': ['image observations and private transport/host/source paths'],
            'limitations': meta.get('limitations', [])}}
    source_lock = deepcopy(meta['source_lock'])
    source_lock.update(source_record_sha256=source_sha, original_native_result_sha256=record['native_result']['sha256'],
        original_audit_sha256=record['audit']['sha256'], original_source_metadata_sha256=record['source_metadata_sha256'],
        selected_original_events_sha256=record['selected_events_original_sha256'],
        terminal_original_line_sha256=record['episode_complete']['source_line_sha256'],
        final_action_original_line_sha256=record['final_action_complete']['source_line_sha256'])
    objects = {'evidence/episode-complete.json': ('episode_complete', ep),
        'evidence/native-acks.json': ('native_ack', [final, ep]),
        'evidence/trajectory.json': ('trajectory', trajectory), 'evidence/public-timeline.json': ('public_timeline', turns),
        'evidence/costs.json': ('costs', costs), 'evidence/source-lock.json': ('source_lock', source_lock),
        'evidence/environment.json': ('environment', m['environment'])}
    files = [('evidence/native-result.json', 'native_result', original_result, record['native_result']['sha256'], None)]
    if {v.get('view') for v in record['videos']} != VIEWS or len(record['videos']) != 3:
        raise ValidationError('Exactly three original native camera files required')
    for video in record['videos']:
        path = _verified(video['local_path'], video['sha256'], video.get('bytes'))
        if video.get('historically_recorded_sha256') not in (None, video['sha256']):
            raise ValidationError('Original camera SHA differs from historical recorded SHA')
        files.append(('videos/' + video['view'] + '.mp4', 'native_video', path, video['sha256'], video['view']))
    demo = record.get('demo')
    if demo is None:
        if not native_standard42_media(m) or record.get('demo_available') is not False:
            raise ValidationError('Original demo required outside explicit historical Standard42 native VLA')
    else:
        path = _verified(demo['local_path'], demo['sha256'], demo.get('bytes'))
        files.append(('videos/demo.mp4', 'public_demo', path, demo['sha256'], None))
    errors = validate_registered_scene(m, scene_registry)
    for value in [m] + [value for _, value in objects.values()]: errors.extend(privacy_findings(value))
    if errors: raise ValidationError('\n'.join(errors))
    target = Path(destination).resolve()
    if any(target == path.resolve().parent or target in path.resolve().parents for _,_,path,_,_ in files):
        raise ValidationError('Native export destination must not overlap original source files')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + target.name + '-', dir=target.parent))
    try:
        for rel, (kind, data) in objects.items():
            path=staging/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(canonical_bytes(data))
            m['artifacts'].append({'path':rel,'kind':kind,'sha256':file_sha256(path),'bytes':path.stat().st_size,'media_type':'application/json'})
        for rel,kind,original,sha,view in files:
            path=staging/rel;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,path)
            artifact={'path':rel,'kind':kind,'sha256':sha,'bytes':path.stat().st_size,'media_type':'video/mp4' if kind in ('native_video','public_demo') else 'application/json'}
            if view: artifact['view']=view
            m['artifacts'].append(artifact)
        errors=validate_manifest(m,staging,True)
        if errors:raise ValidationError('\n'.join(errors))
        raw=canonical_bytes(m);(staging/'manifest.json').write_bytes(raw)
        publication=_publication(m,hashlib.sha256(raw).hexdigest(),provenance)
        errors=validate_publication(publication,staging,True)
        if errors:raise ValidationError('\n'.join(errors))
        (staging/MANIFEST_NAME).write_bytes(canonical_bytes(publication))
        if target.exists():
            expected={str(p.relative_to(staging)) for p in staging.rglob('*') if p.is_file()}
            actual={str(p.relative_to(target)) for p in target.rglob('*') if p.is_file()}
            if expected!=actual or any((target/rel).is_symlink() or file_sha256(target/rel)!=file_sha256(staging/rel) for rel in expected):
                raise ValidationError('Immutable native VLA export collision')
            status='already_present'
        else:
            staging.rename(target);status='exported'
    finally:
        if staging.exists():shutil.rmtree(staging)
    return {'status':status,'run_id':m['run_id'],'bundle':str(target),'manifest':m,
            'publication_manifest':publication,'manifest_sha256':hashlib.sha256(raw).hexdigest()}
