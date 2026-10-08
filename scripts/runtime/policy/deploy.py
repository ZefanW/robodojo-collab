"""Official L3 EEF loop with a durable local-Codex request mailbox.

Native physics, goals, recipes, tool parsing and EEF planning are original.
Only a successfully retimed move_eef path longer than 20 controls is truncated;
its original suffix is discarded, and the next actual observation closes the loop.
"""
import hashlib
import json
import os
import time
from dataclasses import replace
from pathlib import Path

from XPolicyLab.policy.RoboDojo_Agent_L3_Inspect import deploy as shared
from XPolicyLab.policy.RoboDojo_Agent_L3_Inspect_EEF.deploy import _planner
from XPolicyLab.policy.RoboDojo_Agent_L3_Inspect_EEF.docs import eef_docs_from_joint_docs
from .cap20_policy import make_cap20_policy
import importlib


def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
    tmp.replace(path)


class MailboxClient:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = 0

    def complete(self, messages, tools):
        index = self.index
        folder = self.root / f'{index:04d}'
        folder.mkdir(exist_ok=False)
        payload = {'run_id': os.environ['ROBODOJO_RUN_ID'], 'index': index,
                   'messages': messages, 'tools': tools, 'model': 'gpt-6-astra',
                   'reasoning_effort': 'medium'}
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (folder/'request.json').write_bytes(raw)
        atomic(self.root/'pending.json', {'index': index, 'request_sha256': digest,
                                        'run_id': payload['run_id']})
        # No model/transport retry, physics tick, or scene reset while waiting.
        while not (folder/'response.json').is_file():
            time.sleep(0.5)
        receipt = json.loads((folder/'response.json').read_text())
        if receipt['request_sha256'] != digest:
            raise RuntimeError('Saved response does not match pending L3 request')
        self.index += 1
        atomic(self.root/'acknowledged.json', {'index': index, 'request_sha256': digest})
        (self.root/'pending.json').unlink()
        return receipt['response']


def factory(*, action_spec, env, task_env):
    kind = env['L3_CAP20_SOURCE_POLICY_KIND']
    if kind == 'eef':
        module = 'XPolicyLab.policy.RoboDojo_Agent_L3_Inspect_EEF.policy'
        name = 'EefAgentPolicy'
    elif kind == 'coor':
        module = env.get('L3_CAP20_COOR_POLICY_MODULE', 'XPolicyLab.policy.L3_Coor_Codex.policy')
        if module not in ('XPolicyLab.policy.L3_Persistent_Coor.policy',
                          'XPolicyLab.policy.L3_Coor_Codex.policy'):
            raise RuntimeError('Unknown coor source policy module')
        name = 'CoorPolicy'
    else:
        raise RuntimeError('Cap20 source policy must be eef or coor')
    cls = make_cap20_policy(getattr(importlib.import_module(module), name))
    kwargs = dict(
        action_spec=replace(action_spec, docs=eef_docs_from_joint_docs(action_spec.docs)),
        env={**env, 'OPENAI_API_KEY': 'CODEX-TRANSPORT-NOT-AN-API-KEY',
             'L3_INSPECT_API_KEY_ENV': 'OPENAI_API_KEY',
             'L3_INSPECT_BASE_URL': 'http://127.0.0.1:9/unused-codex-transport',
             'L3_INSPECT_MAX_RETRIES': '0'},
        planner=_planner(task_env), client=MailboxClient(env['L3_CODEX_MAILBOX']))
    if kind == 'coor':
        kwargs['task_env'] = task_env
    policy = cls(**kwargs)
    policy.configure_cap20(env['L3_CAP20_AUDIT_DIR'])
    return policy


def eval_one_episode(TASK_ENV, model_client):
    shared.eval_one_episode(TASK_ENV, model_client, policy_factory=factory)


eval_one_episode_batch = eval_one_episode
