"""Image-free public sidecars for already exported, immutable native runs.

This module is offline. It neither runs experiments nor alters legacy manifests.
The original algorithm, protocol, scene, outcome and complete cost ledger remain
attached to the original run identity, including explicitly disclosed reuse.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
from statistics import mean
import tempfile

from .export_legacy import INTERNAL, public
from .schema import (HEX, IDENT, ValidationError, canonical_bytes, file_sha256,
                     privacy_findings, validate_manifest, native_standard42_media,
                     STANDARD42_SOURCE_SHA256, STANDARD42_CAPABILITY_TASKS, STANDARD42_TASKS)
from .statistics import cost_summary, official_summary

VERSION = "leaderboard-lite-v1"
MANIFEST_NAME = "publication-manifest.json"
ARTIFACT_KINDS = frozenset({"native_result", "episode_complete", "native_ack",
    "trajectory", "public_timeline", "costs", "source_lock", "environment",
    "native_video", "public_demo"})
REQUIRED_KINDS = ARTIFACT_KINDS - {"environment"}
FIELDS = ("run_id", "algorithm", "protocol", "scene", "attempt", "environment",
          "status", "timestamps", "outcome", "costs", "audit")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff"}
PRIVATE_FIELDS = {"threadid", "turnid", "responseid", "sessionid", "rawreasoning",
                  "auth", "rawsession", "rawsessions", "rawsessionjournal"}
IMAGE_DATA = re.compile(r"data:image/|\"image_url\"\s*:", re.I)
# Original ten configurations in protocol/l3-action-cap20-20261005/jobs.json.
# Selection is fixed independently of outcomes; arbitrary ten-row subsets are
# never accepted merely because their registry is labelled Devset10.
DEVSET10_SOURCE_SHA256 = "0397d6cf8c1a9ab68bd5f12441d6dd957c0b6c7fbe45438e256d881565fbf397"
DEVSET10_TASKS = {
    "stack_bowls": ("Generalization", "standard"),
    "push_T_random": ("Generalization", "random"),
    "cover_blocks": ("Memory", "standard"),
    "imitate_sorting_sequence": ("Memory", "standard"),
    "insert_tubes": ("Precision", "standard"),
    "build_tower": ("Precision", "standard"),
    "put_bottles_into_dustbin": ("Long-Horizon", "standard"),
    "organize_table": ("Long-Horizon", "standard"),
    "classify_objects_by_language": ("Open", "standard"),
    "solve_equation": ("Open", "standard"),
}



def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _extra_privacy(value, prefix="$"):
    errors = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower().replace("_", "").replace("-", "") in PRIVATE_FIELDS:
                errors.append(f"{prefix}.{key}: private session field prohibited")
            errors.extend(_extra_privacy(item, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            errors.extend(_extra_privacy(item, f"{prefix}[{i}]"))
    elif isinstance(value, str):
        if INTERNAL.search(value):
            errors.append(f"{prefix}: private infrastructure reference")
        if IMAGE_DATA.search(value):
            errors.append(f"{prefix}: embedded image payload/reference prohibited")
    return errors


def validate_publication(manifest, bundle_dir=None, check_files=True):
    """Return validation errors, including SHA/privacy/native checks when local.

    The legacy validator still checks shared fields and native evidence. Only
    its legacy requirement for a public_session artifact is removed; this
    profile instead requires a public timeline, source lock and full cost file.
    Metadata-only validation does not establish local or cloud file integrity.
    """
    if not isinstance(manifest, dict):
        return ["publication: expected object"]
    errors = []
    if manifest.get("publication_manifest_version") != VERSION:
        errors.append("publication_manifest_version: expected " + VERSION)
    if manifest.get("status") != "complete":
        errors.append("publication: only valid complete native runs may be published")
    legacy = {key: deepcopy(manifest.get(key)) for key in FIELDS}
    legacy.update({key: deepcopy(manifest[key]) for key in ("execution_kind", "native_episode") if key in manifest})
    legacy.update(schema_version="1.0", artifacts=deepcopy(manifest.get("artifacts", [])))
    try:
        shared_errors = validate_manifest(legacy, bundle_dir, check_files)
    except (TypeError, AttributeError, KeyError, ValueError) as exc:
        return [f"publication: malformed shared manifest fields ({type(exc).__name__})"]
    for error in shared_errors:
        if error.startswith("complete: missing artifacts "):
            missing = set(error.removeprefix("complete: missing artifacts ").split(", ")) - {"public_session"}
            if missing:
                errors.append("complete: missing artifacts " + ", ".join(sorted(missing)))
        else:
            errors.append(error)
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance: object required")
    else:
        sha = provenance.get("source_manifest_sha256")
        if not isinstance(sha, str) or not HEX.fullmatch(sha):
            errors.append("provenance.source_manifest_sha256: original file SHA256 required")
        reused = provenance.get("reused_original")
        if type(reused) is not bool:
            errors.append("provenance.reused_original: explicit boolean required")
        reason = provenance.get("reuse_reason")
        if reused is True and (not isinstance(reason, str) or not reason.strip()):
            errors.append("provenance.reuse_reason: required for an original reused run")
        if reused is False and reason is not None:
            errors.append("provenance.reuse_reason: null required when not reused")
    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        return sorted(set(errors + ["artifacts: array required"]))
    kinds = Counter(a.get("kind") for a in artifacts if isinstance(a, dict))
    required = REQUIRED_KINDS - ({"public_demo"} if native_standard42_media(manifest) else set())
    missing = required - set(kinds)
    if missing:
        errors.append("publication: missing artifacts " + ", ".join(sorted(missing)))
    for kind in REQUIRED_KINDS - {"native_video"}:
        if kinds[kind] > 1:
            errors.append(f"publication: exactly one {kind} artifact required")
    evidence = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append("publication: artifact must be an object")
            continue
        kind, path = artifact.get("kind"), artifact.get("path", "")
        if kind not in ARTIFACT_KINDS:
            errors.append(f"publication: prohibited artifact kind {kind}")
        if not isinstance(path, str):
            continue
        lower = path.lower()
        if (Path(path).suffix.lower() in IMAGE_SUFFIXES or
                artifact.get("media_type", "").lower().startswith("image/") or
                any(part in {"images", "rawsessions", "raw-sessions", "sessions"}
                    for part in Path(lower).parts) or "public-session" in lower):
            errors.append(f"{path}: image/session artifact prohibited")
        if kind in {"native_video", "public_demo"} and not artifact.get("media_type", "").startswith("video/"):
            errors.append(f"{path}: video media type required")
        if bundle_dir is None or not check_files:
            continue
        root = Path(bundle_dir).resolve()
        target = root / path
        if target.is_symlink() or not target.resolve().is_relative_to(root) or not target.is_file():
            continue  # The shared validator reports unsafe/missing files.
        if kind not in {"native_video", "public_demo"}:
            if target.suffix.lower() != ".json" or artifact.get("media_type") != "application/json":
                errors.append(f"{path}: evidence must be inspectable JSON")
                continue
            try:
                raw = target.read_text(encoding="utf-8")
                data = json.loads(raw)
                errors.extend(_extra_privacy(data, path))
                errors.extend(_extra_privacy(raw, path))
                evidence[kind] = data
            except (UnicodeError, json.JSONDecodeError):
                errors.append(f"{path}: invalid public JSON")
    if bundle_dir is not None and check_files:
        costs = evidence.get("costs")
        if not isinstance(costs, dict) or costs.get("attempts") != manifest.get("costs", {}).get("attempts"):
            errors.append("costs: artifact must retain the complete original attempt ledger")
        controls = manifest.get("outcome", {}).get("control_steps")
        acks = evidence.get("native_ack")
        if type(controls) is int and controls > 0:
            final = [a for a in acks if isinstance(a, dict) and a.get("kind") == "action_complete"] if isinstance(acks, list) else []
            if not final or final[-1].get("control_steps") != [controls]:
                errors.append("native evidence: final action_complete control count differs or is missing")
        trajectory = evidence.get("trajectory")
        if not isinstance(trajectory, dict) or trajectory.get("run_id") != manifest.get("run_id") or not isinstance(trajectory.get("turns"), list):
            errors.append("trajectory: original run_id and turns list required")
        if manifest.get("execution_kind") == "native_vla" and isinstance(trajectory, dict):
            if evidence.get("public_timeline") != trajectory.get("turns"):
                errors.append("native_vla: public timeline differs from the original numeric trajectory")
        if not isinstance(evidence.get("public_timeline"), list):
            errors.append("public_timeline: readable event list required")
    errors.extend(privacy_findings(manifest))
    errors.extend(_extra_privacy(manifest))
    return sorted(set(errors))


def _publication(source, source_sha, provenance=None):
    p = {"source_manifest_sha256": source_sha, "reused_original": False, "reuse_reason": None}
    if provenance is not None:
        if not isinstance(provenance, dict):
            raise ValidationError("provenance must be an object")
        p.update(deepcopy(provenance))
    if p["source_manifest_sha256"] != source_sha:
        raise ValidationError("Provenance source manifest SHA differs from original bytes")
    result = {key: deepcopy(source[key]) for key in FIELDS}
    result.update({key: deepcopy(source[key]) for key in ("execution_kind", "native_episode") if key in source})
    result["environment"] = public(result["environment"])
    result.update(publication_manifest_version=VERSION, provenance=p,
                  artifacts=[deepcopy(a) for a in source["artifacts"] if a["kind"] in ARTIFACT_KINDS])
    return result


def export_publication(source_bundle, destination, provenance=None):
    """Write a separate minimal bundle, copying only selected original bytes.

    destination is the exact run bundle directory. Existing identical output is
    verified and reused; changed or unlisted output is rejected. No source file
    is modified. Return manifest plus local paths and SHA/size metadata.
    """
    source_path = Path(source_bundle).resolve()
    source_file = source_path / "manifest.json" if source_path.is_dir() else source_path
    source_path = source_file.parent
    target = Path(destination).resolve()
    if source_path == target or source_path in target.parents or target in source_path.parents:
        raise ValidationError("Publication destination must be separate from the source bundle")
    if source_file.is_symlink():
        raise ValidationError("Source manifest symlinks are prohibited")
    source = _read(source_file)
    errors = validate_manifest(source, check_files=False)
    if errors:
        raise ValidationError("\n".join(errors))
    manifest = _publication(source, file_sha256(source_file), provenance)
    errors = validate_publication(manifest, source_path)
    if errors:
        raise ValidationError("\n".join(errors))
    expected = {a["path"] for a in manifest["artifacts"]} | {MANIFEST_NAME}
    raw = canonical_bytes(manifest)
    if target.exists():
        actual = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file() or p.is_symlink()}
        if actual != expected or not (target / MANIFEST_NAME).is_file() or (target / MANIFEST_NAME).read_bytes() != raw:
            raise ValidationError("Publication destination collision; immutable output cannot be replaced")
        errors = validate_publication(manifest, target)
        if errors:
            raise ValidationError("\n".join(errors))
        status = "already_present"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".publication-", dir=target.parent))
        try:
            for artifact in manifest["artifacts"]:
                dest = staging / artifact["path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_path / artifact["path"], dest)
            (staging / MANIFEST_NAME).write_bytes(raw)
            errors = validate_publication(manifest, staging)
            if errors:
                raise ValidationError("\n".join(errors))
            staging.rename(target)
            status = "exported"
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return {"run_id": manifest["run_id"], "status": status, "bundle": str(target),
            "manifest_path": str(target / MANIFEST_NAME), "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "files": len(manifest["artifacts"]), "bytes": sum(a["bytes"] for a in manifest["artifacts"]),
            "manifest": manifest}


def validate_panel_registry(task_registry, profile="full54"):
    """Resolve an explicit metric roster; default full54 validation is unchanged."""
    if profile not in ("full54", "devset10", "standard42"):
        raise ValidationError("Unknown panel metric profile; select full54, devset10 or standard42 explicitly")
    registry = _read(task_registry) if isinstance(task_registry, (str, Path)) else task_registry
    tasks = registry.get("tasks", []) if isinstance(registry, dict) else []
    try:
        universe = {task["task"]: task for task in tasks}
    except (TypeError, KeyError):
        raise ValidationError("Panel task registry requires task objects") from None
    if profile == "full54":
        if len(universe) != 54 or len(tasks) != 54:
            raise ValidationError("Panel requires the exact original 54-task registry")
    elif profile == "devset10":
        if (registry.get("profile") != "devset10" or registry.get("roster_id") != "devset10-v1"
                or registry.get("expected_task_count") != 10):
            raise ValidationError("Devset10 requires its explicit profile, roster_id and expected_task_count")
        if (len(tasks) != 10 or set(universe) != set(DEVSET10_TASKS) or
                any((row.get("capability"), row.get("variant")) != DEVSET10_TASKS[name]
                    for name, row in universe.items())):
            raise ValidationError("Devset10 roster must exactly match the original ten task/capability/variant configurations")
        if registry.get("source_manifest_sha256") != DEVSET10_SOURCE_SHA256:
            raise ValidationError("Devset10 roster source SHA must match the pinned original selection manifest")
        if any(type(registry.get(field)) is not int or registry[field] != 0
               for field in ("official_seed", "layout_ordinal", "round_index")):
            raise ValidationError("Original Devset10 roster is explicitly seed0/layout0/round0")
    else:
        if (registry.get("profile") != "standard42" or registry.get("roster_id") != "standard42-v1"
                or registry.get("expected_task_count") != 42):
            raise ValidationError("Standard42 requires its explicit profile, roster_id and expected_task_count")
        if (len(tasks) != 42 or set(universe) != set(STANDARD42_TASKS) or
                any((row.get("capability"), row.get("variant")) != STANDARD42_TASKS[name]
                    for name, row in universe.items())):
            raise ValidationError("Standard42 roster must exactly match the original 42 standard task/capability configurations")
        if registry.get("source_manifest_sha256") != STANDARD42_SOURCE_SHA256:
            raise ValidationError("Standard42 roster source SHA must match the pinned original Full54 selection manifest")
    return registry, universe


def devset10_summary(runs, universe):
    """Ten original task configurations, each with weight 1/10 (not Full54)."""
    chosen = {run["scene"]["task"]: run for run in runs}
    missing = sorted(set(universe) - set(chosen))
    complete = len(chosen) == 10 and not missing
    capabilities = {}
    for capability in dict.fromkeys(row["capability"] for row in universe.values()):
        tasks = [task for task, row in universe.items() if row["capability"] == capability]
        present = [chosen[task] for task in tasks if task in chosen]
        full = len(present) == len(tasks)
        capabilities[capability] = {"complete": full, "planned": len(tasks), "valid": len(present),
            "score": mean(run["outcome"]["score"] * 100 for run in present) if full else None,
            "success_rate": mean(float(run["outcome"]["success"]) * 100 for run in present) if full else None}
    return {"complete": complete, "round_complete": complete, "valid": len(chosen), "planned": 10,
            "score": mean(run["outcome"]["score"] * 100 for run in runs) if complete else None,
            "success_rate": mean(float(run["outcome"]["success"]) * 100 for run in runs) if complete else None,
            "capabilities": capabilities, "missing_or_incomplete": missing,
            "structural_missing_tasks": [], "duplicate_tasks": [], "unexpected_tasks": [],
            "metadata_mismatches": [], "excluded_repeat_attempts": [],
            "selection_policy": "The fixed original Devset10 roster; one original attempt per task; no outcome-based selection.",
            "aggregation": "Devset10: equal 1/10 weight per original task configuration for score and success rate. Capability means are descriptive; this is not the Full54 metric."}


def standard42_summary(runs, universe):
    """Original 42 standard tasks: within-capability means, five weights of 20%."""
    chosen = {run["scene"]["task"]: run for run in runs}
    missing = sorted(set(universe) - set(chosen))
    complete = len(chosen) == 42 and not missing
    capabilities = {}
    for capability, tasks in STANDARD42_CAPABILITY_TASKS.items():
        present = [chosen[task] for task in tasks if task in chosen]
        full = len(present) == len(tasks)
        capabilities[capability] = {"complete": full, "planned": len(tasks), "valid": len(present),
            "score": mean(run["outcome"]["score"] * 100 for run in present) if full else None,
            "success_rate": mean(float(run["outcome"]["success"]) * 100 for run in present) if full else None}
    return {"complete": complete, "round_complete": complete, "valid": len(chosen), "planned": 42,
            "score": mean(group["score"] for group in capabilities.values()) if complete else None,
            "success_rate": mean(group["success_rate"] for group in capabilities.values()) if complete else None,
            "capabilities": capabilities, "missing_or_incomplete": missing,
            "structural_missing_tasks": [], "duplicate_tasks": [], "unexpected_tasks": [],
            "metadata_mismatches": [], "excluded_repeat_attempts": [],
            "selection_policy": "The fixed original 42 standard configurations; one original attempt per task; no outcome-based selection or borrowed random results.",
            "aggregation": "Standard42: mean within each capability, then five equal 20% capability weights for score and success rate; counts 12/6/8/8/8. Generalization uses only its 12 standard tasks. Not Full54; incomplete overall null."}


def build_panel(manifests_or_paths, task_registry, panel_id, *, title=None, algorithm_id=None, profile="full54"):
    """Build a compact, metadata-validated panel without rewriting run details.

    A differing historical algorithm/protocol is included only with an explicit
    target algorithm_id and a recorded reused_original reason. Per-task episode
    caps and import selection descriptions do not split an official54 panel.
    All other non-reused algorithm and execution protocol fields must match.
    """
    if not isinstance(panel_id, str) or not IDENT.fullmatch(panel_id):
        raise ValidationError("panel_id: safe identifier required")
    registry, universe = validate_panel_registry(task_registry, profile)
    runs = []
    for item in manifests_or_paths:
        if isinstance(item, (str, Path)):
            path = Path(item)
            item = _read(path / MANIFEST_NAME if path.is_dir() else path)
        errors = validate_publication(item, check_files=False)
        if errors:
            raise ValidationError("\n".join(errors))
        runs.append(deepcopy(item))
    if not runs:
        raise ValidationError("Panel requires original run manifests")
    counts = Counter(r["scene"]["task"] for r in runs)
    if set(counts) - set(universe) or any(n != 1 for n in counts.values()):
        raise ValidationError("Panel requires exactly one original run per included registered task")
    if len({r["run_id"] for r in runs}) != len(runs) or any(r["attempt"]["index"] != 0 for r in runs):
        raise ValidationError("Panel accepts unique original run identities, not repeated attempts")
    identities = {(r["scene"]["official_seed"], r["scene"]["layout_ordinal"], r["scene"]["round_index"]) for r in runs}
    if len(identities) != 1:
        raise ValidationError("Panel requires one common seed, layout ordinal and round")
    if profile == "devset10" and identities != {(0, 0, 0)}:
        raise ValidationError("Original Devset10 publication requires seed0/layout0/round0")
    if any((r["scene"]["capability"], r["scene"]["variant"]) !=
           (universe[r["scene"]["task"]]["capability"], universe[r["scene"]["task"]]["variant"]) for r in runs):
        raise ValidationError("Panel scene capability/variant differs from registered task")
    direct = [r for r in runs if not r["provenance"]["reused_original"]]
    if not direct:
        raise ValidationError("Panel needs an original target-algorithm run to establish its condition")
    reference = direct[0]
    target_algorithm = algorithm_id or reference["algorithm"]["algorithm_id"]
    if target_algorithm != reference["algorithm"]["algorithm_id"]:
        raise ValidationError("Target algorithm differs from original non-reused runs")
    def execution_protocol(run):
        return {k: v for k, v in run["protocol"].items()
                if k not in {"episode_control_limit", "scope", "selection_policy"}}
    for run in runs:
        reused = run["provenance"]["reused_original"]
        same = run["algorithm"] == reference["algorithm"] and execution_protocol(run) == execution_protocol(reference)
        if not same and not (algorithm_id is not None and reused):
            raise ValidationError("Mixed algorithm/protocol requires explicit target and disclosed original reuse")
    runs.sort(key=lambda r: (r["scene"]["capability"], r["scene"]["task"]))
    if profile == "full54":
        summary = official_summary(runs, universe)
    elif profile == "devset10":
        summary = devset10_summary(runs, universe)
    else:
        summary = standard42_summary(runs, universe)
    rows = []
    for run in runs:
        scene, outcome = run["scene"], run["outcome"]
        rows.append({"run_id": run["run_id"], "task": scene["task"], "capability": scene["capability"],
                     "variant": scene["variant"], "status": run["status"], "score": outcome["score"],
                     "score_percent": outcome["score"] * 100, "success": outcome["success"],
                     "control_steps": outcome["control_steps"], "model_decisions": outcome["model_decisions"],
                     "actual_responses": outcome["actual_responses"], "algorithm": run["algorithm"],
                     "protocol": run["protocol"], "environment": run["environment"],
                     "simulator": run["environment"]["simulator_version"],
                     "reused_original": run["provenance"]["reused_original"],
                     "provenance": run["provenance"], "costs": cost_summary([run]),
                     "artifact_count": len(run["artifacts"]),
                     "detail_url": f"data/publications/{panel_id}/runs/{run['run_id']}.json"})
    kinds = {run.get("execution_kind", "codex") for run in runs}
    if len(kinds) != 1:
        raise ValidationError("Panel cannot mix native VLA and Codex execution costs")
    if kinds == {"native_vla"}:
        for row, run in zip(rows, runs):
            row.update(execution_kind="native_vla", native_episode=run["native_episode"], vla_inference_calls=None,
                       policy_action_requests=run["outcome"]["policy_action_requests"],
                       policy_rpc_calls=run["outcome"]["policy_rpc_calls"])
    seed, layout, round_index = next(iter(identities))
    result = {"publication_manifest_version": VERSION, "panel_id": panel_id,
              "title": title or panel_id, "algorithm_id": target_algorithm,
              "algorithm": reference["algorithm"], "official_seed": seed, "layout_ordinal": layout,
              "round_index": round_index, "run_count": len(runs), "official54": summary, "summary": summary,
              "costs": cost_summary(runs), "runs": rows,
              "reused_count": sum(r["provenance"]["reused_original"] for r in runs),
              "source_algorithm_ids": sorted({r["algorithm"]["algorithm_id"] for r in runs}),
              "scope": "budget-limited single-seed single-layout original 54-task panel",
              "official_leaderboard_submission": False,
              "limitations": ["Official capability weighting is used; this is not a verified official leaderboard submission or the larger official evaluation protocol.",
                              "One seed/layout panel does not establish across-seed robustness. Original source metadata and disclosed historical reuse are retained.",
                              "This compact index validates metadata only; export and storage receipts separately establish local and cloud byte integrity."]}
    if kinds == {"native_vla"}:
        result["execution_kind"] = "native_vla"
    if profile == "devset10":
        result.pop("official54")
        result.update(metric_profile="devset10", metric_label="Devset10 · 10-task equal weight",
                      devset10=summary, scope="devset10: fixed original ten configurations, seed0/layout0; not Full54",
                      roster={"id": "devset10-v1", "task_count": 10,
                              "source_manifest_sha256": DEVSET10_SOURCE_SHA256,
                              "task_registry_sha256": hashlib.sha256(canonical_bytes(registry)).hexdigest()},
                      limitations=["Devset10 uses the fixed original ten task configurations with equal task weights. It is not Full54 and is not an official leaderboard submission.",
                                   "This selected development set does not establish full-benchmark performance or across-seed robustness; no new experiment is implied by publication.",
                                   "Original algorithms, protocols, costs and any explicitly disclosed reuse remain attached to original run identities.",
                                   "This compact index validates metadata only; export and storage receipts separately establish local and cloud byte integrity."])
    if profile == "standard42":
        result.pop("official54")
        result.update(metric_profile="standard42", metric_label="Standard42 · five capabilities 20% each",
                      standard42=summary, scope="standard42: fixed original 42 standard configurations; not Full54",
                      roster={"id": "standard42-v1", "task_count": 42,
                              "source_manifest_sha256": STANDARD42_SOURCE_SHA256,
                              "task_registry_sha256": hashlib.sha256(canonical_bytes(registry)).hexdigest()},
                      limitations=["Standard42 averages the original standard tasks within each capability, then gives each capability 20% weight. Counts are 12/6/8/8/8; random tasks are excluded.",
                                   "This is not Full54 or an official leaderboard submission. No missing or abnormal task is filled with zero, and no result is borrowed from another layout.",
                                   "One seed/layout panel does not establish across-seed robustness. Publication does not authorize a new experiment.",
                                   "Original algorithms, protocols, costs and any explicitly disclosed reuse remain attached to original run identities.",
                                   "This compact index validates metadata only; export and storage receipts separately establish local and cloud byte integrity."])
    errors = privacy_findings(result) + _extra_privacy(result)
    if errors:
        raise ValidationError("\n".join(errors))
    return result
