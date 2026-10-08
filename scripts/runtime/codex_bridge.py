"""Portable imports for frozen persistent bridge. Original pure wire helpers below."""
import hashlib, json, os
from pathlib import Path
from codex_transport import StdioAppServer
from XPolicyLab.utils.openai_responses import chat_messages_to_responses_input
CODEX = os.environ.get("ROBODOJO_CODEX", "codex")
MODEL = "gpt-6-astra"

def toml_value(value):
    if isinstance(value, dict):
        return '{'+', '.join(json.dumps(k)+' = '+toml_value(v) for k,v in value.items())+'}'
    return json.dumps(value)

def agent_config(output, agent):
    return {'model':MODEL, 'model_provider':'openai', 'model_reasoning_effort':'medium',
            'sqlite_home':str(output/'state/runtime_db'), 'log_dir':str(output/'state/runtime_logs'),
            'default_permissions':'rollout_agent', 'permissions.rollout_agent.extends':':workspace',
            'permissions.rollout_agent.filesystem':{str(output.parent):'read', str(agent):'write'},
            'project_doc_max_bytes':0, 'features.memories':False, 'features.chronicle':False,
            'features.apps':False, 'features.plugins':False, 'features.hooks':False,
            'features.codex_hooks':False, 'features.skip_host_skill_discovery':True,
            'features.fast_mode':False}

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)

def compact_images(value):
    if isinstance(value, dict):
        return {k: compact_images(v) for k, v in value.items()}
    if isinstance(value, list):
        return [compact_images(v) for v in value]
    if isinstance(value, str) and value.startswith('data:image/'):
        return {'image_data_url_sha256': hashlib.sha256(value.encode()).hexdigest(),
                'characters': len(value), 'full_input_retained': 'remote request.json'}
    return value

class CompactInputLog:
    """Log hashes for image bytes; the identical full request is stored remotely."""
    def __init__(self, stream):
        self.stream = stream

    def write(self, value):
        try:
            value = json.dumps(compact_images(json.loads(value)))+'\n'
        except (ValueError, TypeError):
            pass
        return self.stream.write(value)

    def __getattr__(self, name):
        return getattr(self.stream, name)

def pack(messages, tools):
    systems = [m['content'] for m in messages if m.get('role') == 'system']
    if not systems or not all(isinstance(x, str) for x in systems):
        raise ValueError('Official system instruction missing or malformed')
    history = chat_messages_to_responses_input([m for m in messages if m.get('role') != 'system'])
    # Codex expects the explicit ResponseItem variant, rather than the API's
    # shorthand input-message form. This preserves the same roles and bytes.
    for item in history:
        if 'role' in item:
            item['type'] = 'message'
            if isinstance(item.get('content'), str):
                kind = 'output_text' if item['role'] == 'assistant' else 'input_text'
                item['content'] = [{'type':kind, 'text':item['content']}]
    names = [t['function']['name'] for t in tools]
    if set(names) != {'move_eef', 'give_up'}:
        raise ValueError('Unexpected official L3 tool surface')
    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {'name': {'type': 'string', 'enum': names},
                             'arguments': {'type': 'string'}},
              'required': ['name', 'arguments']}
    developer = ('Transport formatting only: select exactly one function from the definitions below. '
                 'Return the requested JSON with its name and arguments; arguments is the JSON-encoded '
                 'argument object. Do not operate files, run commands, or use any other tools. '
                 'The supplied history contains the current robot observations and prior execution feedback.\n'
                 + json.dumps(tools, ensure_ascii=False))
    return '\n\n'.join(systems), history, developer, schema

class Bridge:
    def check_quota(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise RuntimeError("Paused; no additional model calls")
        return self.passive_quota.check()

    def close(self):
        self.transport.close()
