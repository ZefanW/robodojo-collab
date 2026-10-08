"""Original L3 motion planning, with at most 20 controls per move_eef call.

The original planner and retimer run unchanged. No angle threshold, preflight
refusal, resampling, automatic suffix execution, model call, or replay is added.
"""
from __future__ import annotations
import copy
import json
from dataclasses import replace
from pathlib import Path
import numpy as np

MAX_CONTROLS = 20


def _write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def make_cap20_policy(base_policy):
    class Cap20Policy(base_policy):
        def configure_cap20(self, audit_dir):
            self._cap20_dir = Path(audit_dir)
            self._cap20_dir.mkdir(parents=True, exist_ok=True)
            self._cap20_count = 0
            self._cap20_pending = None
            self._cap20_feedback = None

        def _handle_motion(self, name, arguments, observation):
            if name != 'move_eef':
                # In coor, move_link6 is already independently restricted to
                # 1..5 measured-state IK controls and must remain lazy.
                return super()._handle_motion(name, arguments, observation)
            if not hasattr(self, '_cap20_dir'):
                raise RuntimeError('Cap20 policy was not configured')
            if self._cap20_pending is not None:
                raise RuntimeError('Previous chunk lacks native execution confirmation')
            old_goals = copy.deepcopy(self._gripper_goals)
            outcome = super()._handle_motion(name, arguments, observation)
            if outcome.chunk is None:
                return outcome  # Preserve original planner/schema failure exactly.
            chunk = outcome.chunk
            if not isinstance(chunk.actions, (list, tuple)):
                raise RuntimeError('Original move_eef did not produce a materialized path')
            planned = len(chunk.actions)
            executable = min(planned, MAX_CONTROLS)
            self._cap20_count += 1
            audit = dict(policy_cap20=True, max20=MAX_CONTROLS,
                         planned_controls=planned, executable_controls=executable,
                         executed_controls=None, truncated=planned > executable,
                         policy_step=observation.step, tool=name,
                         discarded_suffix_controls=planned - executable,
                         native_terminal_priority=True, suffix_auto_execution=False)
            path = self._cap20_dir / f'action-{self._cap20_count:04d}.json'
            if path.exists():
                raise RuntimeError('Refusing to overwrite an existing cap20 action')
            _write(path, audit)
            if planned > MAX_CONTROLS:
                # Slicing copies the container only. Every executed joint and
                # gripper command is exactly the corresponding original prefix.
                prefix = chunk.actions[:MAX_CONTROLS]
                trace = copy.deepcopy(chunk.meta.get('trace', {}))
                trace['cap20'] = audit
                meta = {**chunk.meta, 'trace': trace}
                limited = replace(chunk, actions=prefix, meta=meta)
                result = replace(outcome, chunk=limited, tool_result=(
                    f'Accepted: the original plan contains {planned} control steps; '
                    f'only its first {MAX_CONTROLS} will execute before the next observation. '
                    'The remaining steps will not execute automatically. '
                    'This prefix may end before the target or before a scheduled gripper change; '
                    'the next observation reports actual execution and target error.'))
            else:
                limited = chunk
                result = outcome  # Same object and same feedback for short paths.
            self._cap20_pending = dict(audit=audit, path=path, chunk=limited,
                                       old_goals=old_goals)
            return result

        def confirm_executed(self, played):
            super().confirm_executed(played)
            pending = getattr(self, '_cap20_pending', None)
            if pending is None:
                return
            actions = pending['chunk'].actions
            if type(played) is not int or not 0 <= played <= len(actions):
                raise RuntimeError('Native executed count is outside the offered prefix')
            audit = pending['audit']
            audit['executed_controls'] = played
            audit['unexecuted_controls'] = audit['planned_controls'] - played
            audit['native_ended_before_prefix_complete'] = played < len(actions)
            if audit['truncated']:
                # EEF planning eagerly latches the requested gripper endpoint.
                # If its jaw phase is outside the executed prefix, carrying that
                # endpoint into the next call would release/close prematurely.
                # Retain precisely the last command that physics actually saw.
                self._gripper_goals = copy.deepcopy(pending['old_goals'])
                if played:
                    for arm in ('left', 'right'):
                        values = np.asarray(actions[played - 1].data[f'{arm}_ee_joint_state']).reshape(-1)
                        if values.size != 1 or not np.isfinite(values[0]):
                            raise RuntimeError('Invalid executed gripper command')
                        self._gripper_goals[arm] = float(values[0])
                self._cap20_feedback = copy.deepcopy(audit)
                # _last_targets deliberately remains the ORIGINAL requested
                # pose. The original arrival check then reports measured error
                # to that request, never error to the truncated commanded pose.
            audit['latched_gripper_commands'] = copy.deepcopy(self._gripper_goals)
            _write(pending['path'], audit)
            self._cap20_pending = None

        def _observation_message(self, observation, **kwargs):
            message = super()._observation_message(observation, **kwargs)
            audit = getattr(self, '_cap20_feedback', None)
            if audit is not None:
                message['content'][0]['text'] += (
                    f'\nPrevious move_eef: executed {audit["executed_controls"]} of '
                    f'{audit["planned_controls"]} originally planned control steps '
                    f'(per-action limit {MAX_CONTROLS}). '
                    f'{audit["unexecuted_controls"]} unexecuted steps were discarded, '
                    'including any gripper commands in that suffix. '
                    'No suffix is queued; choose the next action from this measured observation. '
                    'The arrival check remains relative to your original target.')
                self._cap20_feedback = None
            return message

        def audit_config(self):
            config = super().audit_config()
            config['action_cap20'] = dict(max_controls=MAX_CONTROLS,
                scope='move_eef original retimed control prefix', angle_threshold=None,
                planning_and_retiming_unchanged=True, suffix_auto_execution=False,
                short_paths_unchanged=True, actual_gripper_command_latch=True)
            return config

    Cap20Policy.__name__ = 'Cap20' + base_policy.__name__
    return Cap20Policy
