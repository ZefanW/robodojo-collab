"""Observational audit hooks. Do not alter actions, rewards, or physics steps."""
import functools
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import numpy as np


def clean(value):
    from omegaconf import OmegaConf
    if OmegaConf.is_config(value):
        value = OmegaConf.to_container(value, resolve=True)
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items() if k != 'vision'}
    if isinstance(value, (list, tuple)):
        return [clean(x) for x in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, 'detach'):
        return clean(value.detach().cpu().numpy())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def install(env):
    root = Path(env.save_dir)/'audit'
    root.mkdir(parents=True, exist_ok=True)
    journal = root/'events.jsonl'
    initial_seen = set()
    from src.eval_client import case_comparability
    if os.environ.get('ROBODOJO_COMPARABILITY_MODE', 'off') != 'off':
        case_comparability.validate_environment(env.task_name, env.eval_seed,
            [int(x) for x in os.environ['ROBODOJO_LAYOUT_IDS'].split(',')])

    def event(kind, **data):
        record = {'kind': kind, 'time_unix': time.time(),
                  'layout_by_env': clean(getattr(env, 'current_env_seed_map', {})),
                  'control_steps': clean(getattr(env, 'take_action_cnt', [])), **clean(data)}
        with journal.open('a') as f:
            f.write(json.dumps(record, separators=(',', ':'))+'\n')

    def snapshot():
        lm = env.scene_manager.layout_manager
        result = {}
        for idx, layout in env.current_env_seed_map.items():
            objects = {}
            for name, kind in lm.instance_type_by_env[idx].items():
                if kind in ['room', 'table', 'ground', 'light']:
                    # Static fixtures are fully represented by realized scene config.
                    continue
                try:
                    obj = lm.get_scene_object(idx, name)
                    state = {'type': kind}
                    if kind == 'fluid':
                        state['particle_positions'] = clean(obj.get_particle_positions()[0])
                        state['particle_velocities'] = clean(np.asarray(obj.point_instancer.GetVelocitiesAttr().Get()))
                    elif kind == 'dynamic':
                        # Dynamic assets (e.g. conveyors) wrap an XForm rather than
                        # a rigid body. Read their pose and authored motion without
                        # changing the stage or stepping simulation.
                        from pxr import Usd
                        state['pose'] = clean(obj.get_world_pose())
                        motion = {}
                        for prim in Usd.PrimRange(obj.stage.GetPrimAtPath(obj._prim_path)):
                            for attr in prim.GetAttributes():
                                if 'velocity' in attr.GetName().lower():
                                    value = attr.Get()
                                    if value is not None:
                                        try:
                                            value = np.asarray(value).tolist()
                                        except (TypeError, ValueError):
                                            pass
                                        motion[str(prim.GetPath()).removeprefix(obj._prim_path)+'/'+attr.GetName()] = clean(value)
                        state['authored_motion'] = motion
                    elif kind in ['rigid', 'articulation', 'geometry', 'garment']:
                        state['pose'] = clean(lm.get_instance_pose(idx, inst_name=name, relative=False))
                    else:
                        raise ValueError('Unimplemented initial-state capture for '+kind)
                    for getter in ['get_linear_velocity', 'get_angular_velocity', 'get_joint_positions',
                                   'get_joint_velocities', 'get_mass', 'get_local_scale']:
                        if callable(getattr(obj, getter, None)):
                            state[getter.removeprefix('get_')] = clean(getattr(obj, getter)())
                    state['instance_configuration'] = clean(getattr(obj, 'instance_config', {}))
                    objects[name] = state
                except Exception as exc:
                    objects[name] = {'snapshot_error': repr(exc)}
            result[str(idx)] = {'layout_id': layout, 'objects': objects,
                               'realized_scene_configuration': clean(env.scene_manager.config.get(f'env{idx}')),
                               'background_configuration': clean(env.scene_manager.background_config)}
        return result

    original_reset = env.reset
    @functools.wraps(original_reset)
    def reset(*args, **kwargs):
        event('reset_start', args=args, kwargs=kwargs)
        try:
            result = original_reset(*args, **kwargs)
        except Exception as exc:
            event('reset_error', exception=repr(exc))
            raise
        initial = {'task': env.task_name, 'evaluation_seed': env.eval_seed,
                   'capture_schema': 'v2-state-config-velocity',
                   'run_id': env.run_id, 'step_limit': env.step_lim,
                   'realized_state': snapshot()}
        for idx, layout in env.current_env_seed_map.items():
            (root/f'layout_{layout:04d}_initial_state.json').write_text(json.dumps(initial, indent=2))
        event('reset_complete', step_limit=env.step_lim)
        return result
    env.reset = reset

    original_obs = env.get_obs_batch
    @functools.wraps(original_obs)
    def get_obs(*args, **kwargs):
        result = original_obs(*args, **kwargs)
        for obs in result:
            idx = obs['env_idx']
            layout = env.current_env_seed_map.get(idx)
            if layout is None:
                continue
            if layout not in initial_seen:
                from PIL import Image
                hashes = {}
                ranges = []
                for cam, frame in obs.get('vision', {}).items():
                    color = frame.get('color') if isinstance(frame, dict) else None
                    if color is None:
                        continue
                    arr = np.asarray(color)
                    hashes[cam] = {'sha256': hashlib.sha256(arr.tobytes()).hexdigest(),
                                   'shape': list(arr.shape), 'dtype': str(arr.dtype)}
                    rgb = arr[..., :3]
                    ranges.append(int(rgb.max())-int(rgb.min()))
                    Image.fromarray(rgb.astype(np.uint8)).save(root/f'layout_{layout:04d}_{cam}_initial.png')
                if not hashes or not any(ranges):
                    raise RuntimeError('Initial RGB observations absent or all constant; refusing to score invalid renderer.')
                (root/f'layout_{layout:04d}_initial_observation.json').write_text(
                    json.dumps({'observation': clean(obs), 'images': hashes}, indent=2))
                case_comparability.check(root, env.task_name, env.eval_seed, layout, env.run_id)
                initial_seen.add(layout)
            event('observation', observation=obs)
        return result
    env.get_obs_batch = get_obs

    original_action = env.take_action_batch
    @functools.wraps(original_action)
    def action(*args, **kwargs):
        event('action_submit', actions=args, kwargs=kwargs)
        t = time.monotonic()
        try:
            result = original_action(*args, **kwargs)
        except Exception as exc:
            event('action_error', elapsed_s=time.monotonic()-t, exception=repr(exc))
            raise
        event('action_complete', elapsed_s=time.monotonic()-t,
              native_end=env.end_flag, native_success=env.success)
        return result
    env.take_action_batch = action

    original_call = env.model_client.call
    @functools.wraps(original_call)
    def call(func_name=None, obs=None, **kwargs):
        t = time.monotonic()
        try:
            result = original_call(func_name=func_name, obs=obs, **kwargs)
        except Exception as exc:
            event('policy_rpc_error', method=func_name, elapsed_s=time.monotonic()-t, exception=repr(exc))
            raise
        event('policy_rpc', method=func_name, elapsed_s=time.monotonic()-t,
              result=result if func_name in ['get_action', 'get_action_batch'] else None)
        return result
    env.model_client.call = call

    # Native abort discards streams even on infrastructure errors. Finalize and
    # preserve those streams with a separate label instead.
    def preserve_partial(env_idx_list=None):
        for idx in list(env.video_writers if env_idx_list is None else env_idx_list):
            for cam, writer in env.video_writers.pop(idx, {}).items():
                path = Path(writer.out_path)
                target = root/f'layout_{env.current_env_seed_map.get(idx, "unknown")}_{cam}_partial_{uuid.uuid4().hex[:8]}.mp4'
                try:
                    writer.close(announce=False)
                except Exception as exc:
                    event('video_finalize_error', camera=cam, exception=repr(exc))
                if path.exists():
                    path.rename(target)
                    event('partial_video', path=str(target), frames=writer.n_frames)
    env._abort_video_writers = preserve_partial

    original_run = env.run_eval
    @functools.wraps(original_run)
    def run(*args, **kwargs):
        event('episode_start')
        try:
            result = original_run(*args, **kwargs)
        except Exception as exc:
            event('episode_error', exception=repr(exc))
            preserve_partial()
            raise
        event('episode_complete', native_results=env.eval_result,
              unstable_envs=list(env.unstable_envs))
        return result
    env.run_eval = run
    event('audit_installed', task=env.task_name, evaluation_seed=env.eval_seed,
          configuration=clean(env.eval_cfg), policy_configuration=clean(env.deploy_cfg))
