# Reserve exact work before spending quota

The authoritative ledger is the repository's `work-claims` branch. It stores small public reservation records; it does not store Codex accounts, prompts, paid responses or videos. Each contributor signs in with their own GitHub and Codex accounts. No invitations or permission changes are sent by these tools.

A work ID is deterministic:

```text
algorithm_id:algorithm_version:task:sOFFICIAL_SEED:lLAYOUT_ORDINAL:ASSET_SHA256:aATTEMPT_INDEX
```

It deliberately excludes the contributor and run ID, so choosing another name cannot make the same attempt appear unclaimed. Use the `work_id` written by `scripts/make_package.py`. A deliberate additional attempt needs a positive attempt index, its reason and original run lineage; it is not a retry shortcut for a claimed scene.

A current claim grants one owner and one immutable run. Before native startup, it is additionally bound to one `execution_instance_id`: a SHA-256 over the public machine pseudonym, resolved native output root and run ID. The public ledger contains only this hash, never the internal path. Compute this binding on the **simulator host** using the same configuration that will run native startup:

```sh
python -m robodojo_collab.runner binding-info \
  --config .private/simulator.json --package .private/task.json > .private/binding.json
```

The command performs no paid or GPU operation and prints only public identity fields. For a remote simulator, use its `.private/simulator.json`; the controller uses `.private/contributor.json`, and `.private/task.json` must have identical bytes on both hosts. A single-host setup may use its one `.private/contributor.json` instead. The runner requires the same instance at controller startup. A different output root/machine is a migration requiring explicit reconciliation, not a transparent restart.

## One-time maintainer setup

Maintainers only: ordinary contributors should skip this section because this project's ledger already exists. Do this once for a new deployment, in a new temporary checkout, after the repository exists. These commands are instructions; the toolkit does not automatically create remote branches or change permissions.

```sh
export RDC_UPSTREAM_REMOTE='YOUR_ACTUAL_REPOSITORY_REMOTE'
export RDC_SETUP_DIR="$(mktemp -d)"
git clone --no-checkout "$RDC_UPSTREAM_REMOTE" "$RDC_SETUP_DIR/repo"
git -C "$RDC_SETUP_DIR/repo" switch --orphan work-claims
printf '%s\n' '# Authoritative RoboDojo work reservations' > "$RDC_SETUP_DIR/repo/README.md"
git -C "$RDC_SETUP_DIR/repo" add README.md
git -C "$RDC_SETUP_DIR/repo" commit -m 'Initialize work reservation ledger'
git -C "$RDC_SETUP_DIR/repo" push origin HEAD:refs/heads/work-claims
```

Keep branch history: prohibit force pushes and deletion. Direct CAS writers need ordinary non-force push permission on this branch. If branch protection requires pull requests for every update, use the PR flow below instead; the CLI does not bypass protection. Keep the code and Pages branch separate from this ledger.

## Contributors with direct ledger write permission

Create the task package and record your quota decision first. Use a private claim token file outside every repository; this token is only an ownership nonce and is not a Codex credential.

```sh
export RDC_UPSTREAM_REMOTE='https://github.com/ZefanW/robodojo-collab.git'
export RDC_RUN_ID="$(python -c 'import json; print(json.load(open(".private/task.json"))["run_id"])')"
export RDC_WORK_ID="$(python -c 'import json; print(json.load(open(".private/task.json"))["work_id"])')"
export RDC_CONTRIBUTOR_ID="$(python -c 'import json; print(json.load(open(".private/task.json"))["attempt"]["contributor_id"])')"
export RDC_EXECUTION_ID="$(python -c 'import json; print(json.load(open(".private/binding.json"))["execution_instance_id"])')"
export RDC_TOKEN_FILE="$HOME/.config/robodojo-collab/${RDC_RUN_ID}-claim"
mkdir -p "$(dirname "$RDC_TOKEN_FILE")"
python -m robodojo_collab git-claim acquire \
  --remote "$RDC_UPSTREAM_REMOTE" --branch work-claims \
  --work-id "$RDC_WORK_ID" --owner "$RDC_CONTRIBUTOR_ID" \
  --token-file "$RDC_TOKEN_FILE" --lease-seconds 86400
```

The token file is created once with mode 0600; only its SHA-256 goes into Git. Do not delete or replace it after a network error. The command clones the latest ledger, commits the reservation and uses a normal **non-force push**. Two simultaneous clones cannot both win: the stale push is rejected. Success includes `remote_readback_verified: true`; anything else is a hold, not permission to use the GPU or make paid calls.

The runner binds the reservation to the exact run/instance before native startup. You may prebind it explicitly using the `run_id` and `execution_instance_id` returned above:

```sh
python -m robodojo_collab git-claim bind \
  --remote "$RDC_UPSTREAM_REMOTE" --branch work-claims \
  --work-id "$RDC_WORK_ID" --owner "$RDC_CONTRIBUTOR_ID" \
  --token-file "$RDC_TOKEN_FILE" \
  --run-id "$RDC_RUN_ID" --execution-instance-id "$RDC_EXECUTION_ID"
```

An exact already-accepted binding is verified read-only; it does not generate another commit or require write access. A different or omitted instance after binding is rejected. The native scene separately keeps an immutable controller identity, so another controller state cannot take it over just by knowing the run ID.

## Contributors without ledger write permission

A fork is a place to prepare a reservation PR. Its independent ledger **does not allocate authoritative work**. Do not start native or paid work until the accepted upstream record exists.

First create your GitHub fork using the repository's Fork button, and sign in to your own Git client. On the simulator host, generate `.private/binding.json` with the command above; transfer that **public hash-only file** and the exact same proposed task package to your controller's code checkout. All Python commands below run from that main checkout with its virtual environment active. The temporary ledger checkout contains no Python package and is used only through `git -C`.

The following prepares a fresh fork branch from the current authoritative ledger. Replace only your public GitHub login; the package supplies the run, contributor and work IDs. A fork's branch must exist before `git-claim` can clone it.

```sh
export RDC_UPSTREAM_REMOTE='https://github.com/ZefanW/robodojo-collab.git'
export RDC_FORK_OWNER='YOUR_PUBLIC_GITHUB_LOGIN'
export RDC_FORK_REMOTE="https://github.com/${RDC_FORK_OWNER}/robodojo-collab.git"
export RDC_RUN_ID="$(python -c 'import json; print(json.load(open(".private/task.json"))["run_id"])')"
export RDC_WORK_ID="$(python -c 'import json; print(json.load(open(".private/task.json"))["work_id"])')"
export RDC_CONTRIBUTOR_ID="$(python -c 'import json; print(json.load(open(".private/task.json"))["attempt"]["contributor_id"])')"
export RDC_EXECUTION_ID="$(python -c 'import json; print(json.load(open(".private/binding.json"))["execution_instance_id"])')"
export RDC_CLAIM_BRANCH="reserve-${RDC_RUN_ID}"
export RDC_TOKEN_FILE="$HOME/.config/robodojo-collab/${RDC_RUN_ID}-claim"
export RDC_CLAIM_CHECKOUT="$(mktemp -d)"
mkdir -p "$(dirname "$RDC_TOKEN_FILE")"
git clone --single-branch --branch work-claims "$RDC_UPSTREAM_REMOTE" "$RDC_CLAIM_CHECKOUT/ledger"
git -C "$RDC_CLAIM_CHECKOUT/ledger" remote add fork "$RDC_FORK_REMOTE"
git -C "$RDC_CLAIM_CHECKOUT/ledger" push fork "HEAD:refs/heads/$RDC_CLAIM_BRANCH"
python -m robodojo_collab git-claim acquire \
  --remote "$RDC_FORK_REMOTE" --branch "$RDC_CLAIM_BRANCH" \
  --work-id "$RDC_WORK_ID" --owner "$RDC_CONTRIBUTOR_ID" \
  --token-file "$RDC_TOKEN_FILE" --lease-seconds 86400
python -m robodojo_collab git-claim bind \
  --remote "$RDC_FORK_REMOTE" --branch "$RDC_CLAIM_BRANCH" \
  --work-id "$RDC_WORK_ID" --owner "$RDC_CONTRIBUTOR_ID" \
  --token-file "$RDC_TOKEN_FILE" --run-id "$RDC_RUN_ID" \
  --execution-instance-id "$RDC_EXECUTION_ID"
```

Stop on any error; do not change branch names or run IDs to bypass an existing claim. `acquire` creates the token file once, so do not prefill it or rerun acquisition with a new token after an uncertain push. An existing fork reservation branch is resumed by inspecting its original record, not by force-pushing this setup again.

Open a pull request targeting **`work-claims`**, not `main`. With the optional GitHub CLI installed and authenticated:

```sh
gh pr create --repo ZefanW/robodojo-collab --base work-claims \
  --head "$RDC_FORK_OWNER:$RDC_CLAIM_BRANCH" \
  --title "Reserve $RDC_RUN_ID" \
  --body 'Please review the exact work ID, public owner, token hash, run and execution-instance binding. No native scene or paid call has started. My proposed quota boundary is documented in the accompanying review.'
```

You can instead use GitHub's Compare and pull request UI with the same base/head branches. Add your actual quota reserve/credit policy and simulator family to the PR; do not paste account IDs, internal paths, the token file or Codex/cloud authentication. The maintainer must review the latest upstream ledger and accept exactly one owner. If another claim arrived while this PR waited, resolve that conflict before merge; a different alias is not new work.

After merge, confirm the authoritative record. The following prints no token or account data:

```sh
python -m robodojo_collab git-claim inspect \
  --remote "$RDC_UPSTREAM_REMOTE" --branch work-claims \
  --work-id "$RDC_WORK_ID" > .private/accepted-claim.json
python - <<'PYVERIFY'
import hashlib, json, os, time
from pathlib import Path
rdc_claim = json.loads(Path('.private/accepted-claim.json').read_text())
rdc_token_sha = hashlib.sha256(Path(os.environ['RDC_TOKEN_FILE']).read_text().strip().encode()).hexdigest()
rdc_expected = {'work_id': os.environ['RDC_WORK_ID'], 'owner': os.environ['RDC_CONTRIBUTOR_ID'],
                'run_id': os.environ['RDC_RUN_ID'], 'execution_instance_id': os.environ['RDC_EXECUTION_ID'],
                'token_sha256': rdc_token_sha, 'status': 'claimed'}
if any(rdc_claim.get(k) != v for k, v in rdc_expected.items()) or rdc_claim.get('expires_unix', 0) <= time.time():
    raise SystemExit('Upstream reservation is missing, different, or expired. Do not start execution.')
print('Accepted upstream reservation matches the original private nonce and native instance.')
PYVERIFY
```

Set **both hosts' private runner configurations** to `claim.mode="git"`, `claim.remote="https://github.com/ZefanW/robodojo-collab.git"`, and `claim.branch="work-claims"`. Set `claim.token_file` to the original external token's absolute path on that host, never `.private/claim-token` inside a repository. Securely copy this reservation nonce to your own simulator if it is on another machine, retain mode 0600, and do not put it in Git. It is distinct from Codex or cloud authentication, which stays on the controller. The already-merged exact binding is checked read-only at native/controller startup, so the simulator need not have GitHub push credentials. Do not point runtime checks at your fork.

For an active lease, prepare renewal on your fork using the original token and submit the resulting ledger update as a PR before expiration. If it expires, stop new paid calls and preserve the scene. The maintainer must reconcile the actual original scene, session and paid receipts before accepting a continuation. If the lease expired **before any scene or paid turn existed**, state that explicitly and provide the zero-start evidence for a reviewed extension; do not fabricate an original session or claim a successful reconciliation. Unknown delivery always remains a hold.

On completion, submit the immutable public result manifest, verified cloud receipts and the ledger's completed state for review. Failed attempts remain recorded. The maintainer does not need your private token to review and merge the public record; they must not ask for Codex authentication.

## Inspect, renew and recover

Inspection is always read-only:

```sh
python -m robodojo_collab git-claim inspect \
  --remote "$RDC_UPSTREAM_REMOTE" --work-id "$RDC_WORK_ID"
```

For direct writers, `git-claim renew` takes the original `--owner`, `--token-file`, `--work-id` and `--lease-seconds`. An expired claim cannot be renewed or acquired by someone else automatically. `git-claim reconcile --evidence PRIVATE_JSON` requires the original owner/token and a reviewed record containing:

```json
{
  "work_id": "EXACT_PACKAGE_WORK_ID",
  "original_session_preserved": true,
  "native_state_verified": true,
  "paid_receipts_reconciled": true,
  "no_unknown_delivery": true,
  "account_allowance_verified": true,
  "next_boundary": 7,
  "reviewed_at": "ACTUAL_TIME_WITH_TIMEZONE"
}
```

These example values are a contract, not evidence. Save actual findings. Only these public allowlisted fields are copied to ledger history; raw private evidence remains local. Reconciliation does not transfer execution to a different machine or permit a fresh native thread. The runner checks the actual native package/process identities and controller ownership **before** delivering saved replies. It then reuses unchanged paid receipts and continues only at the clean original boundary.

A lost Git acknowledgement is handled by inspection, not blind repeat acquisition. The original token file is retained even if a push times out. If the remote record matches it, reconcile the existing reservation. If no record exists, a maintainer can approve the next allocation attempt after checking the branch; no command treats uncertainty as free work.

## Shared-directory alternative

A genuinely shared POSIX directory can use `claim acquire/renew/bind/reconcile/complete` instead. Atomic lock directories serialize operations, and the ledger stores only token hashes. All participants must use the same mounted directory; two local paths in different clones are not shared authority. A stale filesystem lock requires inspection before removal. There is no automatic stale-lock deletion or paid takeover.

## Publication checks

`python scripts/check_public.py` inspects Git-tracked files only. It rejects credential-shaped text, private field names in public JSON, internal paths/IPs, private/local directories, symlinks, and binary artifacts that belong in cloud storage. Narrow known scanner/test fixtures are allowed; tests are not broadly exempt. Findings contain locations and categories, never credential values. This scan complements review; it cannot prove that arbitrary natural-language text contains no private information.

`python scripts/check_public.py --base BASE_COMMIT` also rejects any changed, deleted or renamed `results/*/manifest.json` that existed at the base. New run IDs are allowed. On GitHub pull requests the checker automatically uses the event's base SHA. Storage locations may evolve through separate reviewed receipts; published native evidence manifests remain immutable.
