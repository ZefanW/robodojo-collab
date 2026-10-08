# Contributor agent instructions

Read README, docs/GETTING_STARTED_zh-CN.md, docs/ERRATA_zh-CN.md, docs/PROTOCOL.md, docs/ENVIRONMENT.md, docs/QUOTA.md, docs/RUNNING.md and the selected algorithm/source/scene locks before executing an experiment. Explain blockers plainly; never quietly substitute a model, API account, simulator, task layout or client version.

For a first-time contributor, begin with environment discovery and the offline sample/validate/import roundtrip. Identify controller and simulator hosts, exact interpreters and private config paths before showing launch commands. Detect what you can read safely rather than asking the owner to fill detectable fields. Distinguish the everyday setup assistant from the frozen experiment client. The runner does not bootstrap its first passive quota snapshot, and identity-less native notifications may block execution: report that real compatibility boundary rather than fabricating identity, timestamps or paid probes. An example accepted-assignment file is not an authoritative shared claim. Follow the onboarding document's expected outputs and final manifest/receipt registration steps.

## Before any paid inference

- Work only in this contributor's own checkout, output directory, account and assigned simulator. Do not touch someone else's experiment process, queue, heartbeat, config or storage. Diagnose read-only first. Do not connect to an unrelated cluster simply because it appears in an imported report.
- Run CPU checks and confirm source, prompt/tool, scene and dependency hashes. Use only real official seed0/1/2 plus independently recorded layout ordinal. Check the actual machine's driver, GPU rendering support, cgroup/available memory and disk needs before installing/downloading.
- Obtain a shared Git claim or reviewed assignment for one task package. A local lock is not distributed allocation. Stop on duplicate/expired/ambiguous claim state. A separate repeated trial needs its own attempt identity and purpose; never retry a low score to replace it.
- Ask the account owner to set and record the quota reserve and stop conditions. Unknown/stale passive allowance blocks calls. Do not assume a collaborator's reserve, consume credits by default, purchase credits, swap accounts, or use an API-key fallback. Do not send credentials to a simulator.
- The frozen execution target is GPT-6 Astra medium, Codex0.153.4, persistent history and the original native cap20 EEF policy. Preserve100 decision limit, recipes, images, tool contract, scoring and per-task simulator mapping. Account entitlement is proven only by actual authorized inference, not a catalog listing; do not make a paid probe merely to discover access.

## Continue safely

Treat native scene, persistent thread, paid receipt and ACK as distinct state. Before resuming, reconcile already-paid replies and executed prefixes; reuse exact saved receipts. Never reset/replay/rebuild history or start a replacement session at an ambiguous boundary. The portable runner currently makes no automatic paid retries. Pausing stops new calls and preserves native processes. GPU heartbeats and unrelated user processes must never be killed for capacity.

Use the errata by symptom before trying a repair. Historical client upgrades, dependency fixes and bounded retries apply only to their recorded conditions; they are not standing authorization for new experiments. Separate observed symptoms from proven causes, current state from old error snapshots, and byte-transfer failures from policy failures. Report the evidence needed to verify a repair and preserve the original failed attempt.

## Share and review

Export allowlisted native inputs/tool calls/public note/feedback/result copies, not raw model reasoning or auth/session internals. Public reason text must have been recorded in the original tool-visible output; do not invent it. Do not publish account IDs, personal contact details, internal absolute paths, IPs, API/SSO credentials or private keys. Review licenses before sharing code or assets.

A valid complete status requires agreement of native result, episode_complete, final action ACK/control count and no unresolved invalid initialization. A worker starting, a process exiting or a video existing is not terminal proof. Preserve every failure, attempt and cost. Cache is part of input, not an extra chargeable token category; unknown usage stays null. Immutable run IDs cannot be overwritten. Files must be SHA verified after upload and read back before registering verified storage. Landing URLs, playable video URLs and downloadable files are different capabilities; label unverified or login-dependent access honestly.

All fast checks use `python -m unittest discover -s tests -v`; the fixture needs no GPU or paid model. Never add paid tests to CI. Full artifact review precedes result PR merge. Keep original local archives intact. Build the site from sanitized manifests and separate storage overlays, not live private runtime folders. Do not send invitations, messages or notifications to other people unless the user explicitly requests them.
