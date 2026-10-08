# Export completed legacy experiments safely

The legacy exporter reads an existing immutable archive without importing its Python modules or contacting a model, simulator, or network service. It writes only to an explicitly different destination. It never resumes, resets, retries, or repairs an experiment.

Use the normal contribution schema for new runs. This adapter exists for earlier archives whose original source tree combines private runtime records and public results.

## Required source evidence

Supply a completed `native-source.json`, the original public transcript, three native camera MP4 files, the original PUBLIC-note demo, and a successful archive marker. The native result must exactly match the saved `episode_complete.native_results`, layout outcome, terminal controls, and empty `unstable_envs`. An exited process, completed dashboard row, or video filename is insufficient.

The archive's local receipt manifest must match its remote verification SHA. Every consumed original public-input and cost receipt is checked against that manifest. Video and demo bytes are checked against their archived checksums. The original official scene filename, seed directory, layout ordinal, and asset SHA stay separate. An optional independent scene-hash receipt strengthens the frozen manifest evidence without distributing scene assets.

```sh
python -m robodojo_collab.export_legacy \
  --source "$LEGACY_WORKSPACE" \
  --destination "$PUBLIC_EXPORTS" \
  --run-id "$RUN_ID" \
  --runtime "$RELATIVE_RUNTIME" \
  --video-root "$RELATIVE_VIDEO_ROOT" \
  --protocol "$PROTOCOL_ID" \
  --algorithm-id "$ALGORITHM_ID" \
  --evidence "$IMMUTABLE_NATIVE_EVIDENCE_JSON" \
  --client-version "$RECORDED_CODEX_VERSION" \
  --contributor-id "$PUBLIC_CONTRIBUTOR_NAME" \
  --scene-verification "$SCENE_SHA_RECEIPT_JSON" \
  --tar
python -m robodojo_collab validate "$PUBLIC_EXPORTS/$RUN_ID"
```

The evidence input accepts either `{native_result, events:[...]}` with one actual native episode terminal, or an existing audit document containing per-run `rows`/`results` with the original `native_result` and `terminal`/`episode_complete`. Full immutable native events are preferred. Scene verification is an array of `{run_id, asset_sha256, manifest_asset_sha256}`; both hashes must agree with the frozen source manifest.

The archive stage is separate from upload. `--tar` generates a deterministic, uncompressed USTAR with stable file order, zero timestamps/ownership, relative paths, and no symlinks. Bundle files remain independently SHA-addressed. An existing identical export is reusable; a conflicting export or TAR is rejected. The initial real archives are only 12–16 MB each, so each is one independently retryable upload unit. Larger contributions may use the storage adapter's chunk/package workflow.

## Exactly what is public

The export contains original robot observations and camera images, visible task/system/tool definitions, accepted and rejected robot tool calls, original PUBLIC `note`/`reason`, tool feedback, requested and executed motion, full native action acknowledgments, final native results, source hashes, and each paid attempt's token counts. The public session is a projection with public identifiers, not a raw native-session journal.

Private reasoning, encrypted items, assistant free text, authentication files, account identifiers, native session/response identifiers, and private filesystem/network locations are excluded. Native raw session files are never opened by this exporter. The existing `permanent-history/input-*` files are read only for explicitly allowed system, user, and tool fields. Every exported text artifact is scanned again by the independent schema validator.

The demo is the already archived public-note render, verified byte-for-byte; the exporter does not invent rationales or rewrite their meaning. Original rendered observations and experiment outputs are exported, while simulator asset files and checkpoints are not bundled. Their licenses and download instructions remain separate from the collaboration repository's own license.

## Costs and missing values

Each `paid-start.json` is an attempt. Nested startup/retry attempts are retained. A byte-identical identity mirrored into another folder is counted once using its original session, request SHA, and paid-start timestamp; an incomplete identity is never assumed to be a duplicate. Cached tokens are a subset of input tokens. Missing usage or response counts stay `null`; the exporter never converts an unknown failed call to zero or adds a cumulative session snapshot to per-attempt costs.

Historical records sometimes lack a per-run source commit, GPU model, driver, or exact dependency versions. Those fields stay null with a visible limitation. A current hardware probe would not establish the historical environment. The original simulator family and Codex client version are retained, and differences must be shown when comparing algorithms.

## Initial real sample

Four archived `solve_equation`, official seed directory **0**, layout ordinal **0** runs are selected by task across four algorithms, independently of score. This is an ingestion sample, not a complete benchmark round or a best-of ranking.

| Algorithm | Native score | Controls | Paid attempts | Client | Simulator |
| --- | ---: | ---: | ---: | --- | --- |
| Astra L3 persistent cap20 | 100 | 264 | 40 | 0.153.4 | Sim6 |
| Sol61 L3 persistent cap20 | 0 | 300 | 37 | 0.159.2 | Sim6 |
| Astra L3 coor cap20 | 0 | 300 | 43 | 0.153.4 | Sim6 |
| Astra L3 full Codex cap20 | 0 | 300 | 34 | 0.153.4 | Sim5.1 |

The four source scene files were independently hashed and match `df2d8ee1b5e6b3d984174bd03555a2f512addb671a4bf830e9eecbd9e7f7d48b`. They represent the **same geometry**, not four new layouts. The initial sample includes 396 original images, 12 native camera videos, four public demos, and the full native per-control acknowledgment records. All original source records are preserved.

Uploading a TAR does not prove public playback or download. Storage receipts must distinguish a cloud-disk landing page, authenticated download, verified readback SHA, and a separately tested direct playback URL. No direct-video capability should be inferred from a share link.

## New portable-run exports

After a portable run reaches an actual native terminal, use the runner's `collect` command to copy only the completed native output and verify pre/post source hashes. Collection creates a private `collection-proof.json`; it does not publish the private mailbox, raw sessions, or launch command paths.

```sh
python -m robodojo_collab.runner collect \
  --config configs/my-private-config.json --package my-package.json
python -m robodojo_collab.export_new \
  --controller .private/controller/MY_RUN_ID \
  --native .private/collected/MY_RUN_ID \
  --destination .private/public-exports --tar
python -m robodojo_collab validate .private/public-exports/MY_RUN_ID
```

The fresh exporter verifies the collected file set, source/result/terminal identity, exact native layout, frozen prompt/tool hashes, launch-time policy/source hashes, all paid attempts, public original input images, three camera videos, and source stability during export. A generated HTML demo displays the original PUBLIC notes and feedback alongside all three original videos; absent notes stay absent. It works without a model call or video re-render and is a separate public artifact, not a raw native transcript. Current policy files are never substituted for the recorded launch-time policy identity.

Both export adapters have CPU-only tests. The portable adapter's end-to-end shape fixture is explicitly synthetic and has no playable video, simulator execution, or leaderboard score; actual video playback is validated on the separately imported real archives. A new contributor's own simulator/client combination still needs its first live run verification.
