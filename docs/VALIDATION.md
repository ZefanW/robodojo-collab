# Release verification — 2026-10-08

This release proves the collaboration pipeline with four existing native runs and CPU checks. It does not claim a fresh contributor has installed the GPU environment or completed paid inference.

## Code and execution boundaries

- The full local CPU suite with frozen RoboProbe source available passed **59 tests, zero skipped**, including 16 cap20 policy tests. The dependency-free default invocation passed 43 checks with the frozen-source test module explicitly skipped (44 unittest entries).
- The source lock verifies 31 portable files and 44 frozen upstream files. Both Sim5.1 and Sim6 patches apply to the specified historical upstream commit.
- The real pinned Codex 0.153.4 client completed three synthetic localhost turns, preserving the original thread across process restart. Input images accumulated 3→6→9; synthetic reasoning items accumulated 0→1→2. This used no model service, account quota or GPU. Details: [PORTABLE_VALIDATION.json](PORTABLE_VALIDATION.json).
- Claim tests cover simultaneous allocation, immutable owner/run/instance binding, expired-lease holds and read-only verification of accepted prebound work. Storage tests cover redirect credential protection, restricted external token paths, malformed filenames, immutable reuse and conflicts.

## Historical evidence

Four immutable `solve_equation`, seed0/layout0 runs were exported and imported with full byte/native-evidence checks. Their actual scene bytes share the recorded asset SHA. All native terminal results agree with episode completion and control ACKs.

| Algorithm | Native score /100 | Controls | Decisions / actual responses |
|---|---:|---:|---:|
| Astra persistent cap20 | 100 | 264 | 40 / 40 |
| Sol61 persistent cap20 | 0 | 300 | 37 / 37 |
| Astra coor cap20 | 0 | 300 | 43 / 43 |
| Astra full Codex cap20 | 0 | 300 | 34 / 34 |

The batch preserves 154 paid attempts and 5,804,177 known input+output tokens; cached input is a subset of input. It includes **452 artifacts**: 396 original images, 12 native camera videos, four public-note demos and native/action/source/cost evidence. Historical missing GPU, driver and exact environment commit fields remain unknown. Simulator, client and protocol differences are disclosed, so these four runs are not a controlled model-only comparison or a complete benchmark score.

## Cloud and dashboard

All four audit TARs, 16 MP4s and four timeline JSON files were uploaded using the Seafile CLI adapter, read back with account authentication, then downloaded anonymously and checked byte-for-byte with SHA-256. The four TARs total 55,695,360 bytes. Their verified public receipts are in [storage.json](../registry/storage.json); image/evidence links identify their member path inside the audit TAR.

All 16 MP4s were decoded and played in the browser with nonzero playback time, positive dimensions and no media error. See [media-verification.json](../registry/media-verification.json). Public timeline JSON is also mirrored by content hash as small dashboard metadata to avoid relying on cross-origin redirect behavior; the mirrored bytes match the cloud artifact SHA.

The dashboard exposes filters, native outcomes, all-attempt costs, videos, public actions and full manifests. Partial scope has no overall score, and sample standard deviation is undefined for n<2. Public notes are tool-visible statements; private reasoning and authentication are excluded.

## Remaining validation boundary

A fresh contributor's complete GPU dependency installation, physics/rendering rollout and paid Codex entitlement remain unverified. The runner intentionally requires that contributor's explicit allowance reserve, fresh passive quota evidence, exact accepted claim and environment checks before paid work. No new model calls or GPU jobs were started for this release, and no original experiment files or processes were changed.
