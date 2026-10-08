# Portable adaptation: optional comparison root comes from contributor environment.
"""Fail closed on environment drift before a policy receives its first observation.

Reference choice depends only on the declared baseline phase/case, never outcomes.
This checks reproducibility; it does not change physics, layouts, or success rules.
"""
import hashlib
import json
import math
import os
from pathlib import Path

P = Path(os.environ.get('ROBODOJO_COMPARABILITY_ROOT', '.'))
R = P/'RoboDojo'
CONTRACT = P/'protocol/comparability-v1/environment.json'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize_limits(value):
    """PhysX uses +inf to denote an unbounded speed limit, not a bad state.

    Only this named configuration property is normalized. NaN/Inf in measured
    poses, velocities or robot state must still fail the finite-state check.
    """
    if isinstance(value, dict):
        return {k: ({'numeric_sentinel': 'positive_infinity'}
                    if k.endswith('/physxRigidBody:maxLinearVelocity')
                    and type(v) is float and v == math.inf else normalize_limits(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_limits(v) for v in value]
    return value


def numeric_diff(a, b, tolerance=1e-5, path='root'):
    """Exact keys/strings/discrete values; absolute tolerance for finite floats."""
    errors = []
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            errors.append(path+': different keys')
        for key in sorted(set(a) & set(b)):
            errors += numeric_diff(a[key], b[key], tolerance, path+'.'+key)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            errors.append(path+': different length')
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                errors += numeric_diff(x, y, tolerance, f'{path}[{i}]')
    elif (type(a) in (int, float) and type(b) in (int, float)
          and (type(a) is float or type(b) is float)):
        if not math.isfinite(a) or not math.isfinite(b) or abs(a-b) > tolerance:
            errors.append(f'{path}: {a} != {b}')
    elif type(a) != type(b) or a != b:
        errors.append(path+': different value')
    return errors


def validate_environment(task, seed, layouts):
    spec = json.loads(CONTRACT.read_text())
    for name, expected in spec['source_sha256'].items():
        if digest(R/name) != expected:
            raise RuntimeError('Environment source drift: '+name)
    if digest(P/'protocol/official54-v1/suite.json') != spec['suite_sha256']:
        raise RuntimeError('Frozen suite changed')
    suite = json.loads((P/'protocol/official54-v1/suite.json').read_text())
    cases = {c['layout_ordinal']: c for c in suite['cases']
             if c['task'] == task and c['evaluation_seed'] == seed}
    for layout in layouts:
        case = cases[layout]
        for file in (P/'protocol/official54-v1'/case['layout_file'], R/case['original_asset_path']):
            if digest(file) != case['layout_sha256']:
                raise RuntimeError('Frozen layout drift: '+str(file))
    return spec


def comparison_payload(initial, observation, layout):
    realized = [v for v in initial['realized_state'].values() if v['layout_id'] == layout]
    if len(realized) != 1:
        raise ValueError('Ambiguous initial layout state')
    realized = json.loads(json.dumps(realized))
    # Preserve source artifacts. Early v2 captures also tried dynamic-state APIs
    # for static fixtures; their complete transforms/materials are in scene config.
    if 'realized_scene_configuration' in realized[0]:
        redundant = {f"ValueError('Unimplemented initial-state capture for {kind}')"
                     for kind in ['room', 'table', 'ground', 'light']}
        realized[0]['objects'] = {k: v for k, v in realized[0]['objects'].items()
                                 if v.get('snapshot_error') not in redundant}
    obs = dict(observation['observation'])
    obs.pop('env_idx', None)
    return normalize_limits({'task': initial['task'], 'evaluation_seed': initial['evaluation_seed'],
            'step_limit': initial['step_limit'], 'realized_state': realized[0], 'observation': obs})


def check(audit, task, seed, layout, run_id):
    mode = os.environ.get('ROBODOJO_COMPARABILITY_MODE', 'off')
    if mode == 'off':
        return
    phase = os.environ['ROBODOJO_COMPARABILITY_PHASE']
    if phase not in ('paired', 'official') or mode not in ('record', 'verify'):
        raise ValueError('Invalid comparability mode/phase')
    case = f'{task}__arx_x5__eval{seed}__layout{layout}'
    catalog = P/'protocol/comparability-v1'/phase
    catalog.mkdir(parents=True, exist_ok=True)
    reference = catalog/(case+'.json')
    initial_path = audit/f'layout_{layout:04d}_initial_state.json'
    obs_path = audit/f'layout_{layout:04d}_initial_observation.json'
    initial, obs = json.loads(initial_path.read_text()), json.loads(obs_path.read_text())
    payload = comparison_payload(initial, obs, layout)
    spec = json.loads(CONTRACT.read_text())
    diagnostic_only = spec.get('comparison_enforcement') == 'diagnostic_only'
    report = {'case_id': case, 'phase': phase, 'run_id': run_id,
              'contract_sha256': digest(CONTRACT), 'reference_path': str(reference),
              'state_absolute_tolerance': spec['state_absolute_tolerance']}
    output = audit/f'layout_{layout:04d}_comparability.json'
    def finish(status, **details):
        report.update(status=status, comparison_is_diagnostic=diagnostic_only, **details)
        output.write_text(json.dumps(report, indent=2)+'\n')
    if 'snapshot_error' in json.dumps(payload):
        finish('initial_state_capture_error')
        if diagnostic_only:
            return
        raise RuntimeError('COMPARABILITY: initial state capture incomplete')
    nonfinite = numeric_diff(payload, payload)
    if nonfinite:
        finish('nonfinite_initial_state', differences=nonfinite[:100])
        if diagnostic_only:
            return
        raise RuntimeError('COMPARABILITY: measured initial state contains nonfinite values')
    if mode == 'record':
        record = {'case_id': case, 'run_id': run_id, 'audit_dir': str(audit),
                  'contract_sha256': digest(CONTRACT), 'payload': payload,
                  'images': obs['images'], 'capture_schema': initial.get('capture_schema', 'legacy-v1'),
                  'source_files': {str(initial_path): digest(initial_path), str(obs_path): digest(obs_path)}}
        # Create once. No replacement of reference after seeing another outcome.
        try:
            with reference.open('x') as f:
                json.dump(record, f, indent=2)
        except FileExistsError:
            existing = json.loads(reference.read_text())
            if existing['run_id'] != run_id:
                finish('reference_already_exists')
                raise RuntimeError('COMPARABILITY: refusing reference overwrite')
        finish('baseline_recorded', capture_schema=record['capture_schema'])
        return
    if not reference.exists():
        finish('missing_reference')
        if diagnostic_only:
            return
        raise RuntimeError('COMPARABILITY: no baseline state for '+case)
    ref = json.loads(reference.read_text())
    for name, expected in ref['source_files'].items():
        if digest(name) != expected:
            finish('reference_artifact_changed')
            raise RuntimeError('COMPARABILITY: reference artifact changed')
    expected = normalize_limits(ref['payload'])
    if ref['capture_schema'] == 'legacy-v1':
        # Historic paired data did not include velocities/realized configuration.
        # Compare only captured evidence; always label this weaker audit coverage.
        expected_objects = expected['realized_state']['objects']
        actual_objects = payload['realized_state']['objects']
        # Legacy audit omitted DynamicObject wrappers. Their frozen layout hashes
        # are still checked, but unavailable historical poses cannot be claimed
        # as measured equivalence. Preserve this explicit coverage limitation.
        uncaptured_dynamic = [k for k, v in actual_objects.items()
                              if k not in expected_objects and v.get('type') == 'dynamic']
        report['legacy_uncaptured_dynamic_objects'] = uncaptured_dynamic
        report['coverage_limitation'] = 'Legacy baseline has no object velocities or realized configuration; compare all recorded poses, robot observation and RGB.'
        payload['realized_state'] = {
            'layout_id': layout,
            'objects': {k: {q: v[q] for q in ('type', 'pose') if q in v}
                        for k, v in actual_objects.items() if k not in uncaptured_dynamic}}
    differences = numeric_diff(expected, payload, spec['state_absolute_tolerance'])
    import numpy as np
    from PIL import Image
    image_differences = {}
    if set(ref['images']) != set(obs['images']):
        differences.append('camera set changed')
    for camera in set(ref['images']) & set(obs['images']):
        a = np.asarray(Image.open(Path(ref['audit_dir'])/f'layout_{layout:04d}_{camera}_initial.png'))
        b = np.asarray(Image.open(audit/f'layout_{layout:04d}_{camera}_initial.png'))
        if a.shape != b.shape:
            differences.append(camera+': image shape changed')
            continue
        delta = np.abs(a.astype(np.int16)-b.astype(np.int16))
        mae, p99 = float(delta.mean()), float(np.quantile(delta, .99))
        image_differences[camera] = {'mean_abs_8bit': mae, 'p99_abs_8bit': p99,
                                    'exact_hash_match': ref['images'][camera]['sha256'] == obs['images'][camera]['sha256']}
        if mae > spec['image_mean_abs_8bit_limit'] or p99 > spec['image_p99_abs_8bit_limit']:
            differences.append(camera+': initial image mismatch')
    finish('mismatch' if differences else 'matched', differences=differences[:100],
           image_differences=image_differences, capture_schema=ref['capture_schema'],
           baseline_run_id=ref['run_id'])
    if differences and not diagnostic_only:
        raise RuntimeError('COMPARABILITY: initial conditions differ; refusing policy action: '+str(differences[:4]))
