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

The archive stage is separate from upload. `--tar` generates a deterministic, uncompressed USTAR with stable file order, zero timestamps/ownership, relative paths, and no symlinks. Bundle files remain independently SHA-addressed. An existing identical bundle is reusable, but `--tar` refuses **any existing archive path**, even an identical TAR. After an interrupted upload, reuse and verify the already-created TAR; do not delete it or rerun `--tar`. A conflicting bundle is rejected. The initial real archives are only 12–16 MB each, so each is one independently retryable upload unit. Larger contributions may use the storage adapter's chunk/package workflow.

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

Run from the main code checkout, with your own configured `.private/contributor.json` and the exact accepted `.private/task.json`. The controller state path below is read from your configuration instead of assumed. Collection's `--destination` is required.

```sh
export RDC_RUN_ID="$(python -c 'import json; print(json.load(open(".private/task.json"))["run_id"])')"
export RDC_CONTROLLER_ROOT="$(python -c 'import json; from pathlib import Path; print(Path(json.load(open(".private/contributor.json"))["controller"]["state_root"]).expanduser().resolve())')"
export RDC_EXPORT_SUMMARY=".private/export-${RDC_RUN_ID}.json"
python -m robodojo_collab.runner collect \
  --config .private/contributor.json --package .private/task.json \
  --destination .private/collected
( set -C; python -m robodojo_collab.export_new \
  --controller "$RDC_CONTROLLER_ROOT/$RDC_RUN_ID" \
  --native ".private/collected/$RDC_RUN_ID" --package .private/task.json \
  --destination .private/public-exports --tar > "$RDC_EXPORT_SUMMARY" )
export RDC_BUNDLE="$(python -c 'import json,os; print(json.load(open(os.environ["RDC_EXPORT_SUMMARY"]))["bundle"])')"
python -m robodojo_collab validate "$RDC_BUNDLE"
python -m robodojo_collab import "$RDC_BUNDLE" --store .private/verified-results
```

Keep the export summary private: it names local files. If the TAR already exists, keep the previous successful summary and reuse its archive. The actual archive basename is `archive.file` in that summary; do not infer it from a run ID containing dots. A failed export or a run without a native terminal is not a completed contribution. Preserve its private evidence for review and do not manufacture missing videos, terminal fields or costs.

The fresh exporter verifies the collected file set, source/result/terminal identity, exact native layout, frozen prompt/tool hashes, launch-time policy/source hashes, all paid attempts, public original input images, three camera videos, and source stability during export. A generated HTML demo displays the original PUBLIC notes and feedback alongside all three original videos; absent notes stay absent. It works without a model call or video re-render and is a separate public artifact, not a raw native transcript. Current policy files are never substituted for the recorded launch-time policy identity.

This portable demo is HTML, whereas the four historical demos are MP4. For the portable HTML demo, download and safely extract the complete public TAR, preserving its `demo/` and `videos/` relative paths, then open the demo locally. Uploading that HTML as an isolated cloud object does not make its relative video links work. Leave its `playback_url` null and provide the bundle download fallback unless you separately verify a complete hosted demo.

After the [storage publication and receipt merge](STORAGE.md#index-receipts-separately), add **only** the verified manifest to the code checkout. This snippet refuses a changed existing run and preserves all other results:

```sh
python - <<'PY'
import os
from pathlib import Path
from robodojo_collab.schema import load_manifest
rdc_bundle = Path(os.environ['RDC_BUNDLE'])
rdc_manifest = load_manifest(rdc_bundle)
rdc_target = Path('results') / rdc_manifest['run_id'] / 'manifest.json'
rdc_bytes = (rdc_bundle / 'manifest.json').read_bytes()
rdc_target.parent.mkdir(parents=True, exist_ok=True)
if rdc_target.exists():
    if rdc_target.read_bytes() != rdc_bytes:
        raise SystemExit('Existing immutable run differs; keep it and request a reviewed new attempt.')
else:
    with rdc_target.open('xb') as rdc_output:
        rdc_output.write(rdc_bytes)
PY
python -m robodojo_collab index --store results --manifest-only \
  --storage registry/storage.json --output web/data/index.json
```

Do not run `import --store results`: import copies the entire bundle, including images and videos. `results/` in Git contains only manifests. Submit the result manifest, reviewed storage overlay and rebuilt index in a code pull request targeting **`main`**. Allocation/lease/completion records use a separate pull request targeting **`work-claims`**. The maintainer must download and fully validate the public bundle before merging; `--manifest-only` alone does not verify artifact bytes.

Both export adapters have CPU-only tests. The portable adapter's end-to-end shape fixture is explicitly synthetic and has no playable video, simulator execution, or leaderboard score; actual video playback is validated on the separately imported real archives. A new contributor's own simulator/client combination still needs its first live run verification.
