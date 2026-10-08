# RoboDojo Collab

Run reproducible robot-manipulation experiments on independent machines and Codex accounts. Share **small immutable manifests in GitHub**, **artifact bytes in Tsinghua Cloud**, and a static evidence dashboard. There is no shared model account or central paid-inference scheduler.

This is an independent collaboration harness, not the official RoboDojo leaderboard. The initial implementation preserves the Astra L3 persistent-history cap20 protocol and imports a small, explicitly labeled historical batch. CPU/offline checks and historical native evidence are available; a fresh contributor's GPU installation and paid inference have **not** been validated by this release.

[Explore results](https://zefanw.github.io/robodojo-collab/) · [Cloud evidence](https://cloud.tsinghua.edu.cn/d/5aa7d2260f914aebb1b7/)

## Quick start

Use Python 3.10+ for the offline tools (3.12 recommended for the controller):

```sh
git clone https://github.com/ZefanW/robodojo-collab.git
cd robodojo-collab
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python -m robodojo_collab sample .private/example
python -m robodojo_collab validate .private/example
python -m robodojo_collab import .private/example --store .private/example-store
# Repeating this command returns already_present, without replacing anything.
python -m robodojo_collab import .private/example --store .private/example-store
python -m http.server 8080 --directory web
```

Open `http://localhost:8080`. The synthetic example is a failed/offline fixture with no score or real scene; it is kept out of the published historical index. The dashboard's committed data contains real exported runs.

## From clone to a real contribution

1. **Configure your own environment.** Follow [ENVIRONMENT.md](docs/ENVIRONMENT.md), the frozen source/asset locks and simulator mapping. Run the CPU-only doctor. The controller supports local or SSH-connected simulators; no maintainer host paths or credentials are required. Obtain upstream assets directly after checking their terms.
2. **Reserve one exact task package.** `scripts/make_package.py` selects a real official seed directory and layout, bound to its SHA. Use the [Git-backed claim protocol](docs/CLAIMS.md) or a reviewed assignment before starting. Expired leases never silently transfer live scenes. Each contributor explicitly chooses their own quota reserve; example configurations deliberately cannot start paid calls.
3. **Run or resume the frozen algorithm.** Follow [RUNNING.md](docs/RUNNING.md). The runner preserves a persistent native session, reuses saved paid replies, checks every new request boundary, and stops on unknown delivery, missing history or stale quota. No automatic account/model/API fallback or scene reset.
4. **Export public evidence.** Follow [EXPORT.md](docs/EXPORT.md). Native input, tool actions, public note/reason, feedback, trajectory, final result and videos are shareable audit copies. Private reasoning, account identifiers, credentials and internal machine paths remain private. A terminal must agree across native result, episode-complete and control ACKs.
5. **Upload with the CLI.** Follow [STORAGE.md](docs/STORAGE.md). Upload immutable hash-addressed objects to your Tsinghua Cloud library, download them back, and verify SHA-256. Keep all failed attempts and unknown fees. Public share links are tested separately from account-authenticated downloads.
6. **Submit the manifest and verified locations.** Add `results/RUN_ID/manifest.json` and artifact receipts under `registry/storage.json` in a pull request. Do not commit videos or raw sessions. A maintainer verifies the downloaded bundle before merging. Rebuild the index; GitHub Pages serves the static dashboard.

```sh
python -m robodojo_collab validate .private/PUBLIC_RUN
python -m robodojo_collab import .private/PUBLIC_RUN --store .private/verified-results
python -m robodojo_collab index --store results --manifest-only \
  --storage registry/storage.json --output web/data/index.json
```

`--manifest-only` validates registered metadata and scene identity; it is **not** a replacement for full artifact download/hash/native-evidence validation. The first historical batch was imported with full artifact checks.

## What the dashboard shows

- Algorithm/protocol, official seed/layout, task/run/attempt and state filters; old unlimited-action settings are hidden by default.
- Native terminal scores, control steps, decisions, actual model responses, cached/uncached/output token accounting and unknown usage.
- Complete-panel capability weighting, per-task cross-scene mean/count/sample variance/SD/range and explicit missingness. Partial panels never become an overall zero.
- Three native camera videos and recorded PUBLIC rationale demos, cloud playback or truthful download fallback, action timelines, trajectories and audit links.
- Client/simulator/hardware differences, original attempt lineage, immutable SHA proofs and storage verification status.

The current small import is `solve_equation`, official seed0/layout0, in four historical algorithms. It is a pipeline validation sample, **not** a full benchmark comparison. The baseline scores100; the other three attempts score0. They have material client/simulator/protocol differences. No result was rerun or selected from multiple attempts to improve its score.

## Reproducibility rules

The official directories are **0,1,2**. Seed and layout are separate fields. The scene catalog binds each actual layout to its asset path and SHA; repeated SHA values are not new geometry. Fullset totals require all54 tasks in comparable scope: five capabilities get equal weight; Generalization gives standard/random equal half weights. Missing structural layouts and unfinished runs stay missing. Costs retain **all** attempts; cached input is already included in input; unknown is null.

See [protocol](docs/PROTOCOL.md), [schema](schemas/README.md), [agent instructions](AGENTS.md), [licenses](licenses/) and [verification record](docs/VALIDATION.md). The minimal runner is single-scene/single-contributor; contributors parallelize independently only after safe allocation and their own budget decision.

## Repository layout

| Path | Purpose |
|---|---|
| `robodojo_collab/` | validation, import, statistics, claims, environment diagnosis, execution, export and storage |
| `registry/` | frozen algorithms, sources, actual scenes, task categories and public storage receipts |
| `results/` | immutable lightweight public manifests |
| `scripts/runtime/` | source-locked original bridge/policy/audit components with upstream notices |
| `web/` | static dashboard and generated index |
| `tests/` | CPU-only protocol, claim, accounting, export and upload tests |
| `.private/`, `staging/`, `.local/` | ignored local state; never publish |

## License

New collaboration tooling is MIT licensed. Preserved third-party source keeps its own MIT/Apache-2.0 notices in `licenses/` and source provenance in `registry/source-lock.json`. NVIDIA software, datasets and checkpoints are separate dependencies; this repository does not redistribute them. The license at a pinned historical commit must not be assumed to apply to a newer upstream revision.
