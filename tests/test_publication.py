import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from robodojo_collab.cli import make_sample
from robodojo_collab.publication import (ARTIFACT_KINDS, MANIFEST_NAME, build_panel,
                                         export_publication, validate_publication)
from robodojo_collab.schema import ValidationError, canonical_bytes, file_sha256

ROOT = Path(__file__).resolve().parents[1]


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        make_sample(self.source)
        self.m = json.loads((self.source / "manifest.json").read_text())
        self.m["run_id"] = "original-run"
        self.m["protocol"].update(scope="unit-test-native-evidence", id="original-policy")
        self.m["scene"].update(task="solve_equation", capability="Open", variant="standard")
        self.m["status"] = "complete"
        self.m["outcome"].update(native_result=True, episode_complete=True, evidence_consistent=True,
                                 score=0.5, success=False, control_steps=12, model_decisions=1,
                                 actual_responses=1, unstable_envs=[])
        self.m["costs"] = {"attempts": [dict(attempt_id="0000", input_tokens=100,
            cached_input_tokens=80, output_tokens=7, model_responses=1, paid_requests=1,
            usage_known=True), dict(attempt_id="0001", input_tokens=None,
            cached_input_tokens=None, output_tokens=None, model_responses=None,
            paid_requests=1, usage_known=False)]}
        nr = {"details": {"0": {"score": 0.5, "success": False}}}
        ep = dict(kind="episode_complete", native_results=nr, control_steps=[12], unstable_envs=[])
        self.m["artifacts"] = []
        for kind, data in [("native_result", nr), ("episode_complete", ep),
                ("native_ack", [{"kind": "action_complete", "control_steps": [12]}, ep]),
                ("trajectory", {"run_id": "original-run", "turns": []}),
                ("public_timeline", []), ("source_lock", {"sha256": "a" * 64}),
                ("costs", self.m["costs"]), ("public_session", {"inputs": []})]:
            self.put(kind + ".json", kind, data)
        self.put("images/observation.jpg", "original_image", b"fixture image", "image/jpeg")
        for view in ("head", "left_wrist", "right_wrist"):
            self.put(view + ".mp4", "native_video", b"fixture video " + view.encode(), "video/mp4", view)
        self.put("demo.mp4", "public_demo", b"fixture demo", "video/mp4")
        self.save()
        self.destination = self.root / "publication"

    def tearDown(self):
        self.temp.cleanup()

    def put(self, name, kind, data, media_type="application/json", view=None):
        raw = data if isinstance(data, bytes) else canonical_bytes(data)
        target = self.source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        art = dict(path=name, kind=kind, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), media_type=media_type)
        if view:
            art["view"] = view
        self.m["artifacts"] = [a for a in self.m["artifacts"] if a["path"] != name] + [art]

    def save(self):
        (self.source / "manifest.json").write_bytes(canonical_bytes(self.m))

    def export(self, **kwargs):
        return export_publication(self.source, self.destination, **kwargs)

    def panel_runs(self):
        manifest = self.export()["manifest"]
        registry = json.loads((ROOT / "registry/tasks.json").read_text())
        runs = []
        for i, task in enumerate(registry["tasks"]):
            run = copy.deepcopy(manifest)
            run["run_id"] = task["task"]
            run["scene"].update(task)
            run["protocol"]["episode_control_limit"] = 100 + i * 10
            run["outcome"]["score"] = float(task["capability"] == "Open")
            run["outcome"]["success"] = task["capability"] == "Open"
            runs.append(run)
        return runs, registry

    def test_image_free_sidecar_preserves_source_and_full_costs(self):
        before = (self.source / "manifest.json").read_bytes()
        (self.source / "auth.json").write_text("private unlisted content")
        result = self.export()
        manifest = result["manifest"]
        self.assertEqual((self.source / "manifest.json").read_bytes(), before)
        self.assertEqual(manifest["provenance"]["source_manifest_sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(manifest["costs"], self.m["costs"])
        self.assertTrue(set(a["kind"] for a in manifest["artifacts"]) <= ARTIFACT_KINDS)
        self.assertFalse((self.destination / "images").exists())
        self.assertFalse((self.destination / "public_session.json").exists())
        self.assertFalse((self.destination / "auth.json").exists())
        self.assertEqual(validate_publication(manifest, self.destination), [])
        self.assertEqual(self.export()["status"], "already_present")

    def test_sha_mismatch_does_not_publish(self):
        (self.source / "head.mp4").write_bytes(b"changed")
        with self.assertRaisesRegex(ValidationError, "mismatch"):
            self.export()
        self.assertFalse(self.destination.exists())

    def test_immutable_destination_rejects_changed_or_unlisted_files(self):
        self.export()
        (self.destination / "unlisted.png").write_bytes(b"image")
        with self.assertRaisesRegex(ValidationError, "collision"):
            self.export()

    def test_terminal_and_final_action_ack_must_both_match(self):
        acks = json.loads((self.source / "native_ack.json").read_text())
        acks[0]["control_steps"] = [11]
        self.put("native_ack.json", "native_ack", acks)
        self.save()
        with self.assertRaisesRegex(ValidationError, "final action_complete"):
            self.export()

    def test_cost_file_cannot_drop_unknown_attempt(self):
        self.put("costs.json", "costs", {"attempts": self.m["costs"]["attempts"][:1]})
        self.save()
        with self.assertRaisesRegex(ValidationError, "complete original attempt ledger"):
            self.export()

    def test_cache_is_subset_not_extra_tokens(self):
        run = self.export()["manifest"]
        runs, registry = self.panel_runs()
        panel = build_panel(runs, registry, "test-panel")
        self.assertEqual(panel["costs"]["known_total_tokens"], 54 * 107)
        self.assertEqual(panel["costs"]["unknown_attempts"], 54)
        self.assertFalse(panel["costs"]["complete"])
        run["costs"]["attempts"][0]["cached_input_tokens"] = 101
        self.assertTrue(any("subset" in e for e in validate_publication(run, check_files=False)))

    def test_requires_three_views_timeline_and_private_free_json(self):
        self.m["artifacts"] = [a for a in self.m["artifacts"] if a.get("view") != "head"]
        self.save()
        with self.assertRaisesRegex(ValidationError, "three distinct"):
            self.export()
        self.put("head.mp4", "native_video", b"fixture video", "video/mp4", "head")
        self.put("public_timeline.json", "public_timeline", [{"thread_id": "private-original-id"}])
        self.save()
        with self.assertRaisesRegex(ValidationError, "private session field"):
            self.export()

    def test_image_cannot_be_disguised_as_trajectory(self):
        self.put("trajectory.json", "trajectory", {"run_id": "original-run", "turns": [],
                                                  "payload": "data:image/jpeg;base64,AAAA"})
        self.save()
        with self.assertRaisesRegex(ValidationError, "embedded image"):
            self.export()

    def test_reuse_requires_reason_and_preserves_source_algorithm(self):
        with self.assertRaisesRegex(ValidationError, "reuse_reason"):
            self.export(provenance={"reused_original": True})
        exported = self.export(provenance={"reused_original": True, "reuse_reason": "Original selected path never exceeded the matched action cap."})
        self.assertEqual(exported["manifest"]["algorithm"], self.m["algorithm"])
        self.assertTrue(exported["manifest"]["provenance"]["reused_original"])
        self.assertEqual(file_sha256(self.destination / MANIFEST_NAME), exported["manifest_sha256"])

    def test_panel_uses_official_weights_and_ignores_task_episode_caps(self):
        runs, registry = self.panel_runs()
        panel = build_panel(runs, registry, "test-panel")
        self.assertEqual(panel["summary"]["score"], 20)
        self.assertEqual(panel["official54"], panel["summary"])
        self.assertEqual(panel["summary"]["success_rate"], 20)
        self.assertEqual(panel["reused_count"], 0)
        self.assertFalse(panel["official_leaderboard_submission"])
        self.assertTrue(panel["runs"][0]["detail_url"].startswith("data/publications/test-panel/runs/"))
        self.assertIn("simulator", panel["runs"][0])

    def test_partial_panel_is_missing_not_zero_and_duplicates_rejected(self):
        runs, registry = self.panel_runs()
        partial = build_panel(runs[:-1], registry, "partial")
        self.assertIsNone(partial["summary"]["score"])
        with self.assertRaisesRegex(ValidationError, "exactly one"):
            build_panel(runs + [runs[0]], registry, "duplicate")
        runs[0]["scene"]["layout_ordinal"] = 1
        with self.assertRaisesRegex(ValidationError, "common seed"):
            build_panel(runs, registry, "mixed")

    def test_mixed_algorithm_needs_explicit_original_reuse(self):
        runs, registry = self.panel_runs()
        target = runs[1]["algorithm"]["algorithm_id"]
        runs[0]["algorithm"]["algorithm_id"] = "prior-original-policy"
        runs[0]["algorithm"]["policy_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValidationError, "Mixed algorithm"):
            build_panel(runs, registry, "mixed")
        runs[0]["provenance"].update(reused_original=True, reuse_reason="Original path lengths are equivalent to the cap policy.")
        with self.assertRaisesRegex(ValidationError, "explicit target"):
            build_panel(runs, registry, "mixed")
        panel = build_panel(runs, registry, "mixed", algorithm_id=target)
        self.assertEqual(panel["reused_count"], 1)
        original = next(r for r in panel["runs"] if r["task"] == runs[0]["scene"]["task"])
        self.assertEqual(original["algorithm"]["algorithm_id"], "prior-original-policy")
        self.assertTrue(original["reused_original"])


if __name__ == "__main__":
    unittest.main()
