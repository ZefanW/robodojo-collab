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
  --config .private/simulator.json --package .private/package.json
```

The command performs no paid or GPU operation and prints only public identity fields. The runner requires the same instance at controller startup. A different output root/machine is a migration requiring explicit reconciliation, not a transparent restart.

## One-time maintainer setup

Do this once, in a new temporary checkout, after the repository exists. These commands are instructions; the toolkit does not automatically create remote branches or change permissions.

```sh
export ROBOCOLLAB_CLAIM_REMOTE='YOUR_ACTUAL_REPOSITORY_REMOTE'
export CLAIM_SETUP_DIR="$(mktemp -d)"
git clone --no-checkout "$ROBOCOLLAB_CLAIM_REMOTE" "$CLAIM_SETUP_DIR/repo"
git -C "$CLAIM_SETUP_DIR/repo" switch --orphan work-claims
printf '%s\n' '# Authoritative RoboDojo work reservations' > "$CLAIM_SETUP_DIR/repo/README.md"
git -C "$CLAIM_SETUP_DIR/repo" add README.md
git -C "$CLAIM_SETUP_DIR/repo" commit -m 'Initialize work reservation ledger'
git -C "$CLAIM_SETUP_DIR/repo" push origin HEAD:refs/heads/work-claims
```

Keep branch history: prohibit force pushes and deletion. Direct CAS writers need ordinary non-force push permission on this branch. If branch protection requires pull requests for every update, use the PR flow below instead; the CLI does not bypass protection. Keep the code and Pages branch separate from this ledger.

## Contributors with direct ledger write permission

Create the task package and record your quota decision first. Use a private claim token file outside every repository; this token is only an ownership nonce and is not a Codex credential.

```sh
export PUBLIC_CONTRIBUTOR_ID='your-public-pseudonym'
export REGISTERED_WORK_ID='COPY_THE_PACKAGE_WORK_ID'
export PRIVATE_CLAIM_TOKEN_FILE="$HOME/.config/robodojo-collab/one-scene-claim"
mkdir -p "$(dirname "$PRIVATE_CLAIM_TOKEN_FILE")"
python -m robodojo_collab git-claim acquire \
  --remote "$ROBOCOLLAB_CLAIM_REMOTE" --branch work-claims \
  --work-id "$REGISTERED_WORK_ID" --owner "$PUBLIC_CONTRIBUTOR_ID" \
  --token-file "$PRIVATE_CLAIM_TOKEN_FILE" --lease-seconds 86400
```

The token file is created once with mode 0600; only its SHA-256 goes into Git. Do not delete or replace it after a network error. The command clones the latest ledger, commits the reservation and uses a normal **non-force push**. Two simultaneous clones cannot both win: the stale push is rejected. Success includes `remote_readback_verified: true`; anything else is a hold, not permission to use the GPU or make paid calls.

The runner binds the reservation to the exact run/instance before native startup. You may prebind it explicitly using the `run_id` and `execution_instance_id` returned above:

```sh
python -m robodojo_collab git-claim bind \
  --remote "$ROBOCOLLAB_CLAIM_REMOTE" --branch work-claims \
  --work-id "$REGISTERED_WORK_ID" --owner "$PUBLIC_CONTRIBUTOR_ID" \
  --token-file "$PRIVATE_CLAIM_TOKEN_FILE" \
  --run-id "$REGISTERED_RUN_ID" --execution-instance-id "$EXECUTION_INSTANCE_ID"
```

An exact already-accepted binding is verified read-only; it does not generate another commit or require write access. A different or omitted instance after binding is rejected. The native scene separately keeps an immutable controller identity, so another controller state cannot take it over just by knowing the run ID.

## Contributors without ledger write permission

A fork is a place to prepare a reservation PR. Its independent ledger **does not allocate authoritative work**. Do not start native or paid work until the accepted upstream record exists.

1. On the simulator host, run `binding-info` and keep the exact run/instance values. Choose a new private token-file path; the acquire command will create it once.
2. In a separate checkout, clone the current authoritative `work-claims` branch. Add your own fork as a remote and push that current commit to a new branch in the fork, such as `reserve-ONE_SCENE`. This preserves the existing ledger and avoids mixing code changes into allocation.
3. Run the `git-claim acquire` and `git-claim bind` commands above against **your fork and reservation branch**. Both operations must use the exact package work ID, contributor, run and execution instance. The CLI creates the token file; do not prefill or commit it.
4. Open a pull request from your fork's reservation branch to the authoritative **`work-claims`** branch. Include the package's public identity, intended simulator family, your chosen quota boundary and an explicit statement that no native scene or paid call has started. Do not include account IDs, auth files or internal paths.
5. The maintainer reviews the current upstream work ID, all prior attempts, the owner and token SHA, run/instance binding and lease. Accept exactly one owner. If the same work was claimed while the PR waited, resolve allocation before merging; do not choose a new alias or rerun a completed attempt.
6. After merge, configure the runner's claim remote/branch as the **authoritative repository**, not your fork. `git-claim inspect` must show the accepted owner, original token SHA, run, instance and an unexpired lease. The runner's identical bind is read-only, so this works without upstream push permission.

For an active lease, prepare renewal on your fork using the original token and submit the resulting ledger update as a PR before expiration. If it expires, stop new paid calls and preserve the scene. The maintainer must reconcile the actual original scene, session and paid receipts before accepting a continuation. If the lease expired **before any scene or paid turn existed**, state that explicitly and provide the zero-start evidence for a reviewed extension; do not fabricate an original session or claim a successful reconciliation. Unknown delivery always remains a hold.

On completion, submit the immutable public result manifest, verified cloud receipts and the ledger's completed state for review. Failed attempts remain recorded. The maintainer does not need your private token to review and merge the public record; they must not ask for Codex authentication.

## Inspect, renew and recover

Inspection is always read-only:

```sh
python -m robodojo_collab git-claim inspect \
  --remote "$ROBOCOLLAB_CLAIM_REMOTE" --work-id "$REGISTERED_WORK_ID"
```

For direct writers, `git-claim renew` takes the original `--owner`, `--token-file`, `--work-id` and `--lease-seconds`. An expired claim cannot be renewed or acquired by someone else automatically. `git-claim reconcile --evidence PRIVATE_JSON` requires the original owner/token and a reviewed record containing:

```json
{
  "work_id": "EXACT_REGISTERED_WORK_ID",
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
