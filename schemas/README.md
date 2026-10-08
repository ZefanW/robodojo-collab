# Public result protocol, version 1.0

A contribution is a directory containing `manifest.json` and only public, shareable artifacts. The manifest is immutable after import; corrections produce a distinct run ID linked with `attempt.repeats_run_id`. Every repeated attempt stays visible. A transport retry of the same saved result is an idempotent import, not another run.

`run.schema.json` describes structure. The standard-library validator adds semantic checks, path containment, every listed artifact's size and SHA-256, a credentials/internal-path/private-reasoning scan, completion evidence requirements and cache-subset validation. It is not a substitute for human inspection or the exporter's native-result reconciliation. Use `python -m robodojo_collab validate BUNDLE` before upload.

## Required identity

- `algorithm` contains the algorithm ID/version, upstream source commit, prompt/tools/policy SHA, exact model and reasoning effort, and actual Codex client version. A historical unknown lock may be null only with an explicit audit limitation; new reproducible contributions should have every lock.
- `protocol` identifies the frozen experiment, permitted per-action control prefix (`action_limit`), actual episode control limit if any, and selection rule. A 100-model-decision limit is **not** a 100-control episode limit; record additional model-decision caps in an extension field when needed.
- `scene` separates actual official asset directory (`official_seed`, only 0/1/2), `layout_ordinal`, and reporting `round_index`. Record the original relative asset path and actual SHA, never a generated seed label. The actual asset inventory determines availability; seed 0/layout 0 and seed 0/layout 1 differ even if reporting calls them rounds 0 and 1. Equal asset SHAs are disclosed as shared geometry.
- `attempt.index` starts at zero. Deliberate repeated attempts have new run IDs, a positive index, an explicit reason and `repeats_run_id`. Attempt zero is the predefined primary statistical selection; later attempts never replace it based on outcome. Duplicate originals make the corresponding score missing until reviewed.
- `environment` uses public machine pseudonyms. Record simulator version, GPU, driver, OS and dependency versions. Do not put internal host names, account identifiers, full disk paths or private keys in public data.

## Evidence and costs

`outcome.score` is native normalized 0..1, with `score_scale: "0..1"`; the generated index adds `score_percent` for display. `complete` requires an independently matched native result and `episode_complete`, consistent control counts, no unstable environments and an explicit success boolean. Process exit, queue entries, model responses or videos alone are insufficient. A terminal score of zero is valid and retained.

Every complete bundle includes native result, episode-complete evidence, native ACK, trajectory, a sanitized public session, a public demo and three native camera videos with distinct `view` names. A single HTML public demo may combine all three views. Original images and public action timeline are indexed using their own kinds when available; historical missing originals must be disclosed, not reconstructed. Share native inputs, tool calls, observations, public notes and final output only. Never expose private analysis, encrypted model state or raw auth-bearing session files.

`costs.attempts` includes every paid attempt, including failed starts, retry requests and incomplete usage. Use `null` and `usage_known: false` when measurement is unavailable. Cached input tokens are a **subset** of input tokens: total = input + output, not input + cache + output. Stable attempt IDs deduplicate accounting within a run. No shared-account bill is invented from token totals.

## Storage

Each artifact has a bundle-relative `path`, size, SHA-256, kind, MIME type, and optional `storage`:

```json
{"provider":"tsinghua","landing_url":"https://cloud.tsinghua.edu.cn/verified-share-page","download_url":null,"playback_url":null,"remote_relative_path":"run-id/video.mp4","verification":"local_sha256","verified_at":null}
```

This is a shape example, **not an operational link**. Populate URLs only after verifying the actual share. A landing page is not a direct video URL. Leave playback/download URLs null until tested; offer the cloud folder and named file as a download fallback. `remote_sha256` requires actual read-back of uploaded bytes, not merely a browser success toast. Local manifests remain immutable; separate storage receipts can be used to add verified locations to a generated public index.

## Statistics

`registry/tasks.json` preserves the actual 54-task roster. Fullset total uses five equal capability weights. Generalization averages its standard and random subgroups with one-half weight each. Partial, metadata-mismatched or duplicated task panels have null total, never zero. Structural absence must be recorded separately from failed or unfinished work. Across scenes, task means receive official capability weights; each task reports n, sample variance/SD (null for n<2), range, unique asset-SHA geometry count and simulator differences. Grouping locks exact algorithm/protocol metadata, including model/client versions. Compare environment differences explicitly; do not claim a model-only controlled comparison when environments differ.

## Claims and recovery

Use one agreed POSIX shared-directory claim ledger or let one maintainer allocate disjoint work packages. Two independent clones do **not** share locks. Git is a record of allocation, not a live distributed lease service. Atomic directory creation prevents simultaneous local/shared-disk claims. A lease expiring cannot transfer authority or launch a replacement paid session.

The original owner must reconcile the original native scene/session, complete paid receipts, delivery state, actual allowance and next boundary, then call `claim reconcile`. The token stays in a private 0600 file. No automatic reset, new native thread, old-prefix replay, account fallback, or paid retry is part of these tools. Preserve stopped/failed evidence. Cross-contributor reassignment needs maintainer review and a new explicit attempt, rather than overwriting a lease.

### Git compare-and-swap ledger for independent machines

`git-claim` coordinates unrelated clones without a scheduler. Maintainers initialize a dedicated `work-claims` branch once. The branch should have an empty `claims/` directory and a short README. Protect its history against force pushes and deletion; grant branch write access only through the repository's existing collaboration permissions. Do not share another person's GitHub or Codex credentials.

```sh
python -m robodojo_collab git-claim acquire \
  --remote "$ROBOCOLLAB_CLAIM_REMOTE" --branch work-claims \
  --work-id "$REGISTERED_WORK_ID" --owner "$PUBLIC_CONTRIBUTOR_ID" \
  --token-file "$PRIVATE_CLAIM_TOKEN_FILE" --lease-seconds 3600
```

The private token file must be outside the repository. The public ledger stores only its SHA-256. A normal non-force Git push serves as compare-and-swap: if two clones race from the same parent, one push fails. A successful command confirms remote read-back and returns `remote_readback_verified: true`; only that outcome authorizes using the reserved package after the separate environment/quota gates. The work ID must incorporate the registered algorithm/protocol and exact seed/task/layout identity, not a contributor-chosen alias for the same scene.

A rejected or timed-out push is **not** permission to run. Keep the token file, run the read-only check below, and reconcile its owner and token hash. Do not repeatedly create tokens or claim aliases after a network interruption.

```sh
python -m robodojo_collab git-claim inspect \
  --remote "$ROBOCOLLAB_CLAIM_REMOTE" --work-id "$REGISTERED_WORK_ID"
```

Use `git-claim renew`, `reconcile`, and `complete` with the original owner/token. Expiration remains a hold, never automatic takeover. The same reconciliation JSON contract as the shared-directory ledger applies. No command launches a model or simulator. The CAS test uses two simultaneous clones against a local bare repository and verifies exactly one successful owner.

Contributors without branch write permission submit an allocation PR before spending quota. The maintainer must check the authoritative ledger and accept exactly one owner for each package; wait for the merged allocation, then inspect it. A fork's independent claim ledger does not reserve work in the authoritative project. No collaborator invitations are automatically sent. GitHub is only the small reservation/index ledger; videos and archives remain in Tsinghua Cloud.

### Registry and storage overlays

Official CLI validation/import/index commands verify the scene path and SHA against `registry/scenes.json`; pass `--scenes PATH` for another reviewed inventory. Missing layout ordinals in this inventory become `structural_missing_tasks`, distinct from unfinished work. The first three official seed directories are the only accepted directories.

After publishing artifacts, preserve imported manifests and pass a separate storage receipt file to `index --storage receipts.json`:

```json
{"artifacts":{"ACTUAL_ARTIFACT_SHA256":{"provider":"tsinghua","landing_url":null,"download_url":null,"playback_url":null,"verification":"local_sha256","verified_at":null}}}
```

The generator adds these locations to the public index only; it does not rewrite the immutable contribution. The storage CLI serializes publishers on the same local user/library with a POSIX lock. Separate contributors publishing to the same cloud library still need agreed ownership; a cloud rename conflict is reported and never disguised as a successful idempotent upload. Chunk files and their manifest use atomic immutable publication so interruption cannot expose half-written final files.
