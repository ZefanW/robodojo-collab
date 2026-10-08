"""Read-only, explicit allowlist exporter for previously archived RoboDojo runs.

No source modules are imported. No model, simulator, network, or subprocess call is
made. Remote immutable evidence, when needed, must be fetched separately first.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import shutil
import tarfile
from datetime import datetime, timezone


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"
    if path.exists() and path.read_bytes() != data:
        raise ValueError(f"Refusing to replace a different existing export: {path.name}")
    path.write_bytes(data)


# Reject rather than silently leak or retain a nested private field. Only selected
# public fields are passed here; this is a second layer, not the primary policy.
PRIVATE_KEYS = {"account_id", "thread_id", "turn_id", "response_id", "responseId", "authorization", "access_token", "refresh_token", "encrypted_content", "reasoning", "raw_reasoning", "raw-reasoning", "api_key", "cookie", "auth", "session_id"}
INTERNAL = re.compile(r"(?:/(?:Users|cephfs|localssd|root|nfs_[^/\s]*)/|\b(?:wangzefan\d*-\d+|10\.(?:\d{1,3}\.){2}\d{1,3})\b|\bsk-[A-Za-z0-9_-]{12,})")


def public(value):
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items() if k not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [public(v) for v in value]
    if isinstance(value, str) and INTERNAL.search(value):
        return "[redacted private infrastructure reference]"
    return value


def take(value, keys):
    return public({k: value[k] for k in keys if k in value})


def iso(unix):
    return datetime.fromtimestamp(unix, timezone.utc).isoformat().replace("+00:00", "Z") if unix is not None else None


def validate_terminal(row, native, terminal):
    if row.get("status") != "complete":
        raise ValueError("Only complete immutable source rows may be exported")
    if terminal.get("kind") != "episode_complete" or terminal.get("unstable_envs") != []:
        raise ValueError("Missing valid native episode_complete evidence")
    if terminal.get("native_results") != native:
        raise ValueError("Native result and episode_complete disagree")
    controls = terminal.get("control_steps")
    if controls != [row.get("control_steps")]:
        raise ValueError("Native control count disagrees with source row")
    outcome = native.get("details", {}).get("0")
    if outcome != row.get("native_outcome"):
        raise ValueError("Native per-layout outcome disagrees with source row")
    return outcome


def cost_attempts(calls):
    """Every paid-start is an attempt; identical mirror identities count once."""
    attempts, seen = [], set()
    for p in sorted(Path(calls).rglob("paid-start.json")):
        paid = read(p)
        identity = canonical([paid.get("thread_id"), paid.get("request_sha256"), paid.get("time"), paid.get("phase")])
        if all(paid.get(k) is not None for k in ("thread_id", "request_sha256", "time")):
            if identity in seen:
                continue
            seen.add(identity)
        folder = p.parent
        saved = read(folder / "response.json") if (folder / "response.json").exists() else {}
        usage = read(folder / "usage.json") if (folder / "usage.json").exists() else saved.get("tokens", {})
        known = all(type(usage.get(k)) is int for k in ("inputTokens", "cachedInputTokens", "outputTokens"))
        ids = set()
        for name in ("raw-response-receipts.json", "journal-response-receipts.json"):
            if (folder / name).exists():
                ids.update(x["responseId"] for x in read(folder / name) if x.get("responseId"))
        accounting = read(folder / "accounting.json") if (folder / "accounting.json").exists() else {}
        count = len(ids) or accounting.get("actual_model_responses") or saved.get("actual_model_responses")
        # Absent receipt means unknown, even if a paid request was started.
        if not known or type(count) is not int:
            count = None
        attempts.append({"attempt_id": p.parent.relative_to(calls).as_posix().replace("/", "-"),
                         "input_tokens": usage.get("inputTokens") if known else None,
                         "cached_input_tokens": usage.get("cachedInputTokens") if known else None,
                         "output_tokens": usage.get("outputTokens") if known else None,
                         "model_responses": count, "paid_requests": 1, "usage_known": known})
    if not attempts:
        raise ValueError("No paid attempt ledger exists")
    for a in attempts:
        if a["usage_known"] and a["cached_input_tokens"] > a["input_tokens"]:
            raise ValueError("Cached input is not a subset of input")
    return attempts


def native_evidence(path, run_id):
    d = read(path)
    if "events" in d and "native_result" in d:
        terminals = [e for e in d["events"] if e.get("kind") == "episode_complete"]
        if len(terminals) != 1:
            raise ValueError("Expected one native terminal")
        return d["native_result"], terminals[0], [e for e in d["events"] if e.get("kind") in {"action_complete", "action_submit", "episode_complete"}]
    rows = d.get("rows", d.get("results", []))
    row = next((x for x in rows if x.get("run_id") == run_id), None)
    if row is None:
        raise ValueError("Run absent from supplied native evidence")
    terminal = row.get("episode_complete") or row.get("terminal", [None])[0]
    acks = [row["last_ack"]] if row.get("last_ack") else []
    return row["native_result"], terminal, acks + [terminal]


def deterministic_tar(bundle, output):
    """Stable USTAR archive. Refuse symlinks and never pack staging/private."""
    bundle, output = Path(bundle), Path(output)
    if output.exists():
        raise ValueError("Archive destination already exists; verify/reuse it instead")
    with tarfile.open(output, "w", format=tarfile.USTAR_FORMAT) as tar:
        for p in sorted(bundle.rglob("*")):
            if p.is_symlink():
                raise ValueError("Bundle contains a symlink")
            if not p.is_file():
                continue
            info = tar.gettarinfo(str(p), p.relative_to(bundle).as_posix())
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = ""
            info.mode = 0o644
            with p.open("rb") as stream:
                tar.addfile(info, stream)
    return {"file": output.name, "sha256": sha_file(output), "bytes": output.stat().st_size}


def export_run(source, destination, *, run_id, runtime, video_root, protocol, algorithm_id, evidence, client_version, contributor_id="maintainer-archive", policy_key=None, scene_verification=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Exports must live outside the source workspace")
    video = source / video_root / run_id
    row = read(video / "native-source.json")
    marker = read(source / runtime / "archives" / (run_id + ".json"))
    if not all(marker.get(k) is True for k in ("verified", "videos_sha256", "receipts_and_sessions_sha256", "demo_sha256")):
        raise ValueError("Archive marker is missing or unverified")
    native, terminal, native_acks = native_evidence(evidence, run_id)
    outcome = validate_terminal(row, native, terminal)
    demo = read(video / "rationale-demo.json")
    if sha_file(video / "public-transcript.json") != demo.get("transcript_sha256"):
        raise ValueError("Archived public transcript checksum mismatch")
    receipt_manifest = read(video / "local-receipts-sha256.json")
    remote_receipts = read(video / "receipts-remote-verified.json")
    if remote_receipts.get("verified") is not True or sha_file(video / "local-receipts-sha256.json") != remote_receipts.get("manifest_sha256"):
        raise ValueError("Archived receipt manifest lacks matching remote verification")
    consumed_proofs = {}
    consumed_names = {"paid-start.json", "request.json", "response.json", "usage.json", "accounting.json", "raw-response-receipts.json", "journal-response-receipts.json"}
    for name, record in receipt_manifest["files"].items():
        parts = Path(name).parts
        if not parts or parts[0] not in {"calls", "codex"}:
            continue
        wanted = (parts[0] == "calls" and Path(name).name in consumed_names) or (parts[0] == "codex" and "/permanent-history/input-" in name)
        if not wanted:
            continue
        target = source / runtime / parts[0] / run_id / Path(*parts[1:])
        if not target.is_file() or target.is_symlink() or sha_file(target) != record.get("sha256"):
            raise ValueError("Consumed archived public input/cost receipt checksum mismatch: " + name)
        consumed_proofs[name] = record["sha256"]
    if not consumed_proofs:
        raise ValueError("No archived input/cost integrity proofs")
    trace = read(video / "public-transcript.json")
    if trace.get("in_progress") is not False or trace.get("run_id") != run_id:
        raise ValueError("Transcript is incomplete or belongs to another run")
    case = row["case"]
    if case["evaluation_seed"] not in (0, 1, 2):
        raise ValueError("Not a real official seed directory")
    if int(case["layout_ordinal"]) < 0 or not re.fullmatch(r"[a-f0-9]{64}", case["layout_sha256"]):
        raise ValueError("Invalid scene identity")
    asset_verified = False
    if scene_verification:
        asset_records = read(scene_verification)
        asset_record = next((x for x in asset_records if x.get("run_id") == run_id), None)
        if not asset_record or asset_record.get("asset_sha256") != case["layout_sha256"] or asset_record.get("manifest_asset_sha256") != case["layout_sha256"]:
            raise ValueError("Scene asset SHA verification mismatch")
        asset_verified = True
    calls = source / runtime / "calls" / run_id
    request = read(calls / "0000" / "request.json")
    source_lock = read(source / "protocol" / protocol / "source-lock.json")
    locks = source_lock.get("files", {})
    key = policy_key or next((k for k in locks if k.endswith("/cap20_policy.py")), None)
    policy_sha = locks.get(key) if key else None
    # A source SHA maps to an actual local file; never substitute a current commit.
    verified_locks, unavailable_locks = {}, []
    for name, recorded in locks.items():
        p = source / name
        if p.is_file() and sha_file(p) == recorded:
            verified_locks[name] = recorded
        else:
            unavailable_locks.append(name)
    if key and key not in verified_locks:
        raise ValueError("Selected frozen policy file changed or is unavailable")
    bundle = destination / run_id
    bundle.mkdir(parents=True, exist_ok=True)
    artifacts = []
    def register(rel, kind, view=None):
        p = bundle / rel
        obj = {"path": rel, "kind": kind, "sha256": sha_file(p), "bytes": p.stat().st_size,
               "media_type": mimetypes.guess_type(rel)[0] or "application/octet-stream"}
        if view:
            obj["view"] = view
        artifacts.append(obj)
    def put(rel, value, kind):
        write(bundle / rel, public(value)); register(rel, kind)
    def copy(src, rel, kind, view=None, expected=None):
        original = sha_file(src)
        if expected and original != expected:
            raise ValueError("Archived video checksum mismatch")
        target = bundle / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if sha_file(target) != original:
                raise ValueError("Destination has conflicting artifact")
        else:
            shutil.copyfile(src, target)
        if sha_file(src) != original or sha_file(target) != original:
            raise ValueError("Source changed during read or copy was corrupted")
        register(rel, kind, view)
    put("evidence/legacy-archive-verification.json", {"archive_marker_sha256": sha_file(source / runtime / "archives" / (run_id + ".json")), "archive_marker": marker, "native_evidence_file_sha256": sha_file(evidence), "public_transcript_sha256": sha_file(video / "public-transcript.json"), "receipt_manifest_sha256": remote_receipts["manifest_sha256"], "verified_consumed_files": consumed_proofs}, "other")
    # Raw native terminal/result fields contain no identity or paths.
    put("evidence/native-result.json", native, "native_result")
    put("evidence/episode-complete.json", terminal, "episode_complete")
    ack_keys = {"kind", "time_unix", "layout_by_env", "control_steps", "elapsed_s", "native_end", "native_success", "native_results", "unstable_envs", "action", "actions", "action_type"}
    put("evidence/native-acks.json", [take(e, ack_keys) for e in native_acks], "native_ack")
    # Trajectory retains observed state, requested command, planner result and executed prefix.
    turns = []
    for turn in trace.get("turns", []):
        x = take(turn, ("policy_step", "observation", "decision", "execution"))
        x["calls"] = [take(c, ("call_index", "policy_step", "repair_attempt", "latency_s", "model", "finish_reason", "accepted", "tool", "arguments", "validation_error", "tool_result")) for c in turn.get("llm_calls", [])]
        turns.append(x)
    put("evidence/trajectory.json", {"run_id": run_id, "instruction": trace.get("instruction"), "turns": turns}, "trajectory")
    timeline = []
    for turn in turns:
        for call in turn["calls"]:
            args = call.get("arguments", {})
            timeline.append({"policy_step": turn.get("policy_step"), "control_start": turn.get("observation", {}).get("env_step"), "control_end": turn.get("execution", {}).get("env_step_end"), "tool": call.get("tool"), "arguments": args, "public_note": args.get("note", args.get("reason")), "feedback": call.get("tool_result"), "accepted": call.get("accepted"), "cameras": turn.get("execution", {}).get("cameras", {})})
    put("evidence/public-timeline.json", timeline, "public_timeline")
    # Native permanent-history input-N contains public system/user/tool messages.
    # Assistant text/output files, reasoning/session journals are never opened.
    history = source / runtime / "codex" / run_id / "permanent-history"
    inputs, image_paths = [], set()
    for p in sorted(history.glob("input-*.json")):
        data = read(p)
        messages = []
        for m in data.get("new_messages", []):
            role = m.get("role")
            if role not in {"system", "user", "tool"}:
                continue
            content = m.get("content")
            if isinstance(content, list):
                new = []
                for c in content:
                    if c.get("type") == "text":
                        new.append({"type": "text", "text": public(c.get("text", ""))})
                    elif c.get("type") == "image_url":
                        url = c.get("image_url", {}).get("url")
                        if not isinstance(url, str) or not url.startswith("data:image/"):
                            raise ValueError("Original image payload unavailable")
                        header, data64 = url.split(",", 1)
                        raw = base64.b64decode(data64, validate=True)
                        ext = "jpg" if "jpeg" in header else "png" if "png" in header else None
                        if ext is None:
                            raise ValueError("Unsupported image type")
                        rel = "images/" + digest(raw) + "." + ext
                        target = bundle / rel
                        target.parent.mkdir(exist_ok=True)
                        if target.exists() and target.read_bytes() != raw:
                            raise ValueError("Conflicting image")
                        target.write_bytes(raw)
                        if rel not in image_paths:
                            register(rel, "original_image"); image_paths.add(rel)
                        new.append({"type": "image", "path": rel, "data_url_sha256": digest(url.encode())})
                content = new
            else:
                content = public(content)
            messages.append({"role": role, "content": content})
        inputs.append({"index": data["index"], "messages": messages, "source_input_sha256": sha_file(p)})
    if not inputs or not image_paths:
        raise ValueError("Original public input and images are required")
    put("evidence/public-session.json", {"export_policy": "public-input-tools-feedback-v1", "inputs": inputs, "tool_calls": timeline, "tools": public(request["tools"]), "private_reasoning_exported": False}, "public_session")
    first_observation_text = json.dumps(inputs[0]["messages"], ensure_ascii=False)
    budget_match = re.search(r"Env steps remaining before the episode ends: (\d+)", first_observation_text)
    episode_limit = int(budget_match.group(1)) if budget_match else None
    if asset_verified:
        put("evidence/scene-verification.json", {"run_id": run_id, "asset_sha256": case["layout_sha256"], "manifest_asset_sha256": case["layout_sha256"], "verification": "read-only SHA256 of original official scene asset; bytes not redistributed"}, "other")
    attempts = cost_attempts(calls)
    put("evidence/costs.json", {"attempts": attempts, "cache_is_input_subset": True, "unknown_is_null": True}, "costs")
    put("evidence/source-lock.json", {"source_lock_file_sha256": sha_file(source / "protocol" / protocol / "source-lock.json"), "verified_files": verified_locks, "unavailable_or_changed_files": unavailable_locks, "hash_encoding": "prompt: UTF-8 system content; tools: sorted compact UTF-8 JSON"}, "source_lock")
    checks = {Path(k).name: v for k, v in row["video_checksums"].items()}
    for view in ("head", "left_wrist", "right_wrist"):
        found = list(video.glob("episode_*_cam_" + view + "_*.mp4"))
        if len(found) != 1 or found[0].name not in checks:
            raise ValueError("Exactly one archived native video per camera required")
        copy(found[0], "videos/" + view + ".mp4", "native_video", view, checks[found[0].name])
    demo = read(video / "rationale-demo.json")
    if demo.get("public_note_only") is not True:
        raise ValueError("Demo is not marked public-note-only")
    copy(video / "04_three_views_rationale.mp4", "videos/public-demo.mp4", "public_demo", expected=demo["video_sha256"])
    limitations = ["This representative sample is not a complete comparable round and has no overall benchmark score.", "Native internal identities are pseudonymized; raw account/session journals are retained only by the source owner.", "Public note/reason is original visible tool text, not hidden model reasoning.", "Historical GPU model, driver, full dependency versions, and source Git commit were not captured in the per-run imported records; null is intentional.", "Official scene asset bytes are not redistributed; scene identity is a SHA256."]
    if not asset_verified:
        limitations.append("Asset identity is the frozen original manifest SHA; direct source asset bytes were not available for an independent hash check during this export.")
    if unavailable_locks:
        limitations.append("Some historical source lock entries are no longer present or differ; each is listed explicitly. Selected policy SHA verified.")
    if len(native_acks) < row["control_steps"]:
        limitations.append("Only the archived terminal and last native ACK snapshot are exported for this run; full per-control command/observation trace remains available.")
    if "full_codex" in algorithm_id:
        limitations.append("This case ran on Sim5.1; the selected Astra baseline and coor case ran on Sim6. The comparison is not isolated to algorithm alone.")
    manifest = {"schema_version": "1.0", "run_id": run_id,
                "algorithm": {"algorithm_id": algorithm_id, "version": "legacy-v1", "source_commit": None, "prompt_sha256": digest(next(m["content"] for m in request["messages"] if m["role"] == "system").encode()), "tools_sha256": digest(canonical(request["tools"])), "policy_sha256": policy_sha, "model": request["model"], "reasoning_effort": request.get("reasoning_effort"), "codex_client_version": client_version},
                "protocol": {"id": protocol, "version": "1", "scope": "representative-import", "action_limit": 20, "episode_control_limit": episode_limit, "model_decision_limit": row.get("effective_max_model_calls"), "selection_policy": "All selected solve_equation variants, independent of outcome; not best-of selection."},
                "scene": {"task": case["task"], "capability": case["capability"], "variant": case["variant"], "official_seed": case["evaluation_seed"], "layout_ordinal": case["layout_ordinal"], "asset_path": case["original_asset_path"], "asset_sha256": case["layout_sha256"], "round_index": 0},
                "attempt": {"index": 0, "contributor_id": contributor_id, "reason": "original frozen experiment imported after archive completion", "repeats_run_id": None},
                "environment": {"simulator_version": case.get("simulator"), "machine_id": "archive-simulator-" + str(case.get("simulator", "unknown")).lower().replace(".", "-"), "gpu": None, "driver": None, "os": "Linux", "dependencies": {}},
                "status": "complete", "timestamps": {"started_at": iso(row.get("started_unix")), "finished_at": iso(row.get("finished_unix"))},
                "outcome": {"native_result": True, "episode_complete": True, "score": outcome["score"], "score_scale": "0..1", "success": outcome["success"], "control_steps": row["control_steps"], "model_decisions": row["model_decisions"], "actual_responses": None if any(a["model_responses"] is None for a in attempts) else sum(a["model_responses"] for a in attempts), "unstable_envs": [], "evidence_consistent": True},
                "costs": {"attempts": attempts}, "artifacts": sorted(artifacts, key=lambda x: x["path"]),
                "audit": {"session_public_id": "public-" + digest(run_id.encode())[:20], "export_policy": "explicit-allowlist-v1", "redactions": ["account identifiers", "native session identifiers", "private reasoning and encrypted items", "private filesystem paths", "credentials and authentication records"], "limitations": limitations}}
    if INTERNAL.search(json.dumps(manifest)):
        raise ValueError("Private infrastructure reference in manifest")
    write(bundle / "manifest.json", manifest)
    return {"run_id": run_id, "bundle": str(bundle), "files": len(artifacts), "bytes": sum(x["bytes"] for x in artifacts), "image_count": len(image_paths), "score": outcome["score"], "paid_requests": len(attempts), "manifest_sha256": sha_file(bundle / "manifest.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "destination", "run-id", "runtime", "video-root", "protocol", "algorithm-id", "evidence", "client-version"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--contributor-id", default="maintainer-archive")
    parser.add_argument("--policy-key")
    parser.add_argument("--scene-verification")
    parser.add_argument("--tar", action="store_true")
    args = vars(parser.parse_args()); tar = args.pop("tar")
    result = export_run(**args)
    if tar:
        result["archive"] = deterministic_tar(result["bundle"], Path(result["bundle"]).with_suffix(".tar"))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
