# Contribute one scene without a central scheduler

Start with the CPU example contribution and validation commands in the main README. They require no Codex login, GPU, or quota. Real execution is a separate opt-in operation, and the portable runner has not yet been exercised on a fresh third-party GPU/account.

## 1. Allocate, identify, configure

Choose a task/seed/layout from `registry/scenes.json`. `seed` is an actual official directory (0,1,2); layout is the numeric-file ordinal within that task and directory. Create a **new** run ID for each explicitly intended attempt. Use a public contributor pseudonym. Request/accept the shared GitHub assignment or shared lease before a paid call; a local clone's lock cannot coordinate other clones.

```sh
mkdir -p .private
cp configs/contributor.example.json .private/contributor.json
python scripts/make_package.py --task stack_bowls --seed 0 --layout 1 --run-id example-stack-s0-l1-a1 --contributor example --output .private/task.json
```

Fill your own paths/SSH alias, driver/GPU environment and pinned binary SHA. Follow [ENVIRONMENT.md](ENVIRONMENT.md), then put the source lock from `prepare_native` into `simulator.native_source_sha256`. Use the `work_id` emitted in the task package for the Git claim command described in the README. A dedicated existing `work-claims` branch acts as the minimal shared ledger; contributors with its write permission claim via a normal compare-and-swap Git push, never force-push. Keep the returned private token at `claim.token_file`. The controller verifies ownership and the token hash, binds that shared claim permanently to the run ID, and rechecks at least every60seconds and before each turn's local expiry check. A duplicate run ID binding fails. A claim does not authorize a different scene or a new attempt. Shared POSIX ledgers are also supported with `claim.mode=shared` and `claim.ledger`; independent clones are not shared ledgers.

Set your **own** reserve percentage and credit policy explicitly. An example's null reserve deliberately blocks execution. `budget.snapshot_file` must contain a fresh normal passive native notification, never invented numbers:

```json
{"observed_unix":1791450000.0,"source":"native-passive-notification","snapshot":{"accountId":"LOCAL_ONLY_ACTUAL_ID","rateLimits":{"primary":{"usedPercent":25},"secondary":{"usedPercent":30}}}}
```

The timestamp above is illustrative and will expire. Obtain current native evidence from your own Codex account's normal usage notification. Hash its `accountId` locally into `account_identity_sha256`; neither account ID nor snapshot belongs in GitHub or the result artifact. Every new turn rechecks this file and any native notification updates it. No quota RPC, account switch, credential sharing, credit purchase, or API fallback is implemented. If passive evidence cannot be obtained, execution remains blocked. The account may be used by other tasks; this guard is not an exact per-run monetary budget.

## 2. Check, then start the native scene

```sh
python -m robodojo_collab.runner check --config .private/contributor.json --package .private/task.json
```

Set `execution_authorized=true` only after allocation and your budget decision. Set `license_accepted=true` only after accepting the applicable NVIDIA/upstream terms. On the **simulator host**, from its copy of this repository with its own local path configuration. This host needs its contributor's Git/shared claim access (a claim token is separate from Codex login); it never needs the Codex auth file. The first native launch binds the claim to a hash of the public machine pseudonym, resolved native output root and run ID, so a second machine/output root cannot silently reuse the claim. To prepare a maintainer-reviewed prebinding without printing private paths, use `runner binding-info` on the native host:

```sh
python -m robodojo_collab.runner binding-info --config .private/contributor.json --package .private/task.json
python -m robodojo_collab.runner native-start --config .private/contributor.json --package .private/task.json
```

This launches one policy server and one native simulator in their own process groups, records their exact commands/PIDs, and returns. The native source and selected asset SHA must match. It neither starts nor kills GPU heartbeats. Use an independently chosen free GPU/port; no busy process is displaced. Do not use another person's running experiment tree. If startup fails, preserve the directory/logs; the same run ID cannot be relaunched automatically. A timeout is not proof of a failed or free scene.

## 3. Run the controller on your own account

```sh
python -m robodojo_collab.runner start --config .private/contributor.json --package .private/task.json
python -m robodojo_collab.runner status --config .private/contributor.json --package .private/task.json
```

Each native request is immutable and hash bound. The controller uses the original system/tool hashes, exact Astra medium, and one persistent native session. Full images and original opaque reasoning stay in private local session files; they are not public rationale. The original action policy performs validation, native motion planning/retiming and at most the first 20 controls; no queued suffix executes later. It caps model decisions at100 independently of native episode control budgets. The runner currently handles one scene at a time; intentionally keeping it small avoids accidental paid concurrency across contributors.

To pause, create `controller.state_root/RUN_ID/pause.request`. It stops new calls at a boundary and leaves native processes waiting. Do not kill or reset the simulator. Ctrl-C also retains the native processes. Before resuming, verify the live scene and remove your own pause marker deliberately.

## 4. Recover a connection without repeating paid calls

```sh
python -m robodojo_collab.runner reconcile --config .private/contributor.json --package .private/task.json
python -m robodojo_collab.runner resume --config .private/contributor.json --package .private/task.json
```

Reconciliation compares each saved local receipt with the remote copy and delivers missing receipts unchanged. Delivery is idempotent and never overwrites a different response. Resume requires the original journal, preserved history, matching next boundary and an idle original native thread. It does not inject historical dialogue again, create a replacement thread, reset a scene or repeat completed controls. The native processes must still be alive. Shared native-instance ownership and the original controller identity are checked before even a saved receipt is delivered, because delivery can execute robot actions. An unresolved paid attempt, interrupted history commit, missing journal, usage uncertainty, or expired passive evidence stops progression for manual audit. This initial portable release implements **zero automatic paid retries**; the historical system's authorized maximum-two repair mechanism is retained as source evidence but not silently activated for another contributor.

The local lock prevents concurrent controller owners on one machine. The Git/shared claim prevents another run from binding to the same work item, and the native mailbox binds to the originating controller state. It cannot prevent a malicious contributor from ignoring the protocol. Expired shared leases need reconciliation; no automatic takeover occurs.

## 5. Validate/export/upload/index

A native result file only triggers collection; it does not certify completion. Compare `_result.json`, the native `episode_complete` event, action ACK counts, control steps, transcript end state, and `unstable_envs`. Preserve zero-score and failed attempts. Collect the immutable native archive first, then use the portable public exporter:

```sh
python -m robodojo_collab.runner collect --config .private/contributor.json --package .private/task.json --destination .private/collected
python -m robodojo_collab.export_new --controller .private/controller/RUN_ID --native .private/collected/RUN_ID --package .private/task.json --destination staging/my-contribution --tar
```

Collection supports a local simulator directory or SSH+rsync (rsync3 with `--protect-args`); it verifies the source file manifest both before and after copying and hashes every local file. Then use the repository's result-schema/import and artifact-upload workflow in the README. Public bundles should include the three native camera videos, three-view public-note demo when actually present, original images, action/feedback timeline, native evidence, per-file SHA, all-attempt cost and sanitized environment provenance. Unknown token usage is null with a reason, never zero; cached tokens are an input subset.

The runner does not upload raw sessions or its `.private` directory. Public audit copies include native inputs, tool calls, public assistant note/reason and feedback only. Private reasoning, auth paths, account IDs, credentials and host paths must be excluded by the exporter. Do not invent public rationale where none was emitted. A storage upload is finished only after readback SHA verification; a cloud landing page is not a video playback URL.

## Offline validation commands

```sh
python -m unittest discover -s tests -v
ROBODOJO_TEST_ROBOPROBE=vendor/RoboProbe python -m unittest tests.test_cap20_frozen_cpu -v
python scripts/test_offline_wire.py --codex /path/to/pinned/codex --roboprobe vendor/RoboProbe --output .private/offline-wire
```

The last test points the pinned client only at a localhost synthetic provider with no OpenAI authentication. It tests three incremental turns, a process restart and original-thread resume, retained images/history, and response accounting without paid inference. Use a new output folder each time; the helper refuses to overwrite evidence. This is transport verification, not a score or GPU task. Public release evidence is in `docs/PORTABLE_VALIDATION.json`.
