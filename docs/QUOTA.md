# Own-account allowance: supported evidence and current limits

The portable runner requires fresh, account-bound **passive** allowance evidence before it opens its model app-server. Login, `doctor`, a model catalog, and an ordinary ChatGPT subscription do not supply that evidence. There is no bundled first-login quota collector, no quota RPC fallback, and no paid probe in this release.

This is a practical first-run limitation. If your own environment cannot supply the evidence below, stop **before native startup**. You can still run the CPU tests, inspect/export historical evidence, and prepare the simulator environment. Do not manufacture percentages, attach an assumed account ID to an unidentified event, replace an old timestamp with the current time, or send a model request solely to obtain a usage notification.

## 1. Record your budget decision

In the controller's private config:

| Field | Meaning |
|---|---|
| `reserve_percent` | Percentage to retain for your own use; `20` means stop at 80% used. `null` blocks. Choose it yourself. |
| `allow_existing_credits` | Explicit permission to use already available credits; default `false`. No purchase is performed. |
| `credit_reserve` | Existing credit balance to retain when credits are explicitly allowed. |
| `account_identity_sha256` | SHA-256 of the same ChatGPT `tokens.account_id` used by the pinned controller login. |
| `snapshot_file` | Absolute private output path for the runner's normalized passive snapshot. |
| `max_age_seconds` | Default 300 seconds. Increasing it does not make an old observation current. |

The implementation uses the highest observed used percentage across available quota windows. Credits only permit progression at subscription exhaustion when `allow_existing_credits=true`, `reserve_percent=0`, and a current snapshot actually reports a positive usable balance above `credit_reserve`. Unknown balance is not zero or unlimited. Shared account consumption from other work still counts; this is not an exact dollar or per-experiment token budget.

Generate the identity hash with the credential-safe command in [ENVIRONMENT.md](ENVIRONMENT.md#own-account-login-with-the-file-store). Keep the raw identity, auth file, quota events and normalized snapshot private.

## 2. Which existing evidence is supported?

Use an existing, trusted event from **your own account** and preserve its actual observation time. The source's collection method must have established which login emitted it; a filename, current login, or personal assertion alone does not prove that an older anonymous event came from that login.

The export example below accepts either:

1. A trusted existing collector's JSON envelope containing `snapshot.accountId`, the complete `rateLimits`/`rateLimitsByLimitId` payload, and numeric `observed_unix`; or
2. One native `account/rateLimits/updated` JSON notification that already contains `params.accountId` and a numeric `emittedAtMs`.

Neither format is guaranteed to be emitted by a stock installation. The [current official app-server example](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt) has no `accountId` in its rate-limit notification. A raw notification without account identity, or an ordinary journal `token_count` event whose rate-limit data lacks independently established account binding, is **not accepted by this procedure**. Do not fill that field from `auth.json` just to pass validation. The historical experiment used a separately bound collector; that account/session-specific collector is not distributed as a generic portable solution.

A trusted collector envelope's minimal shape is:

```text
{
  "observed_unix": ORIGINAL_NUMERIC_OBSERVATION_TIME,
  "snapshot": {
    "accountId": ORIGINAL_BOUND_ACCOUNT_ID,
    "rateLimits": ORIGINAL_NATIVE_BUCKET,
    "rateLimitsByLimitId": ORIGINAL_NATIVE_BUCKET_MAP_IF_PRESENT
  }
}
```

This is a shape description, not an input template. Keep all real windows, spend-control indicators, reset times and credit fields supplied by the source. Do not transcribe a UI percentage or copy somebody else's event.

## 3. Export one already trusted event without contacting a service

Save one existing event/envelope to an owner-only JSON file outside Git. For a JSONL source, extract the exact record into that file and retain its original log plus line location privately; do not copy the complete raw session into a public artifact. Set the actual paths below and run from the collaboration checkout. This snippet reads files, validates the original time and identity, saves private evidence, and writes the snapshot expected by the existing runner. It makes no network request and changes no frozen runtime code.

```sh
export ROBOCOLLAB_CONFIG='/absolute/path/to/.private/contributor.json'
export ROBOCOLLAB_PASSIVE_EVENT='/absolute/private/path/to/existing-bound-event.json'
python - <<'PY'
import hashlib, json, os, tempfile, time
from pathlib import Path
from robodojo_collab.runner import BudgetGuard
from robodojo_collab.transport import atomic

cfg = json.loads(Path(os.environ['ROBOCOLLAB_CONFIG']).read_text())
source = Path(os.environ['ROBOCOLLAB_PASSIVE_EVENT'])
raw = source.read_bytes()
record = json.loads(raw)
if record.get('method') == 'account/rateLimits/updated':
    snapshot = record['params']
    emitted = record.get('emittedAtMs')
    if type(emitted) not in (int, float):
        raise SystemExit('Original native observation time missing; stop')
    observed = emitted / 1000
elif isinstance(record.get('snapshot'), dict):
    snapshot = record['snapshot']
    observed = record.get('observed_unix')
else:
    raise SystemExit('Unsupported evidence format; do not invent an adapter')
if type(observed) not in (int, float):
    raise SystemExit('Original observation time missing; stop')
account = snapshot.get('accountId')
if not isinstance(account, str) or not account:
    raise SystemExit('Source account binding missing; do not add an assumed ID')
auth = json.loads((Path(cfg['controller']['auth_home']) / 'auth.json').read_text())
if account != (auth.get('tokens') or {}).get('account_id'):
    raise SystemExit('Source account differs from controller login; stop')
identity = hashlib.sha256(account.encode()).hexdigest()
if identity != cfg['budget']['account_identity_sha256']:
    raise SystemExit('Configured account hash differs; stop')
value = {'observed_unix': observed, 'source': 'native-passive-notification',
         'snapshot': snapshot}
destination = Path(cfg['budget']['snapshot_file']).expanduser()
destination.parent.mkdir(parents=True, exist_ok=True)
# Validate through the real guard before replacing a previous snapshot.
with tempfile.TemporaryDirectory(dir=destination.parent) as td:
    probe = Path(td) / 'snapshot.json'
    atomic(probe, value)
    BudgetGuard(dict(cfg['budget'], snapshot_file=str(probe))).check()
evidence = destination.parent / ('passive-source-' + hashlib.sha256(raw).hexdigest() + '.json')
if evidence.exists():
    if evidence.read_bytes() != raw:
        raise SystemExit('Private evidence collision; stop')
else:
    with evidence.open('xb') as f:
        f.write(raw)
    evidence.chmod(0o600)
atomic(destination, value)
destination.chmod(0o600)
print('Validated existing account-bound passive evidence; age_seconds=%.1f; no network call' % (time.time()-observed))
PY
```

Success means the original observation is fresh, matches the logged-in account and chosen reserve, and passes the current runner's guard. It does not establish the truth of an untrusted collector, future allowance, model entitlement, or ongoing notification compatibility. An expired result must be replaced by newer **real** evidence, never by editing its timestamp. Recheck immediately before the controller's first boundary because simulator setup may exceed five minutes.

## 4. Ongoing notifications are a separate compatibility boundary

The frozen bridge forwards the native event's `params` directly to `BudgetGuard.observe`. This guard requires `accountId`; it cannot infer identity from the transport. A missing identity causes a hold, even if a manually exported bootstrap snapshot passed. The bridge also holds if a paid turn completes without a fresh passive notification. Therefore a stock client/account combination has **not** been proven to run unattended by the offline wire tests.

Do not patch a running session, fill missing identity, ignore the stop condition, continuously retimestamp a snapshot, or switch to an API key. Preserve the exact event, original controller/native state, paid receipt and model journal for compatibility review. Documenting this limit is not a claim that the integration has already been fixed.

For the first authorized scene use [the bounded boundary procedure](RUNNING.md#3-run-the-controller-on-your-own-account). Inspect the saved original event and hold evidence before permitting another boundary. No paid inference should be launched merely as a quota test. If compatibility is already known to be missing, stay blocked instead of spending on a test that will predictably hold.
