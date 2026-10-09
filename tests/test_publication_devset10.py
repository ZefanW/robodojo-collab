"""Fixed-roster Devset10 checks; no paid calls, GPU, network or real uploads."""
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_publication as fixtures
from robodojo_collab.publication import (DEVSET10_SOURCE_SHA256, DEVSET10_TASKS,
                                         build_panel, validate_panel_registry)
from robodojo_collab.schema import ValidationError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('devset_publisher', ROOT / 'scripts/publish_panel.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class Devset10PublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PublicationTests('test_image_free_sidecar_preserves_source_and_full_costs')
        self.fixture.setUp()
        self.full_runs, self.full_registry = self.fixture.panel_runs()
        self.runs = [r for r in self.full_runs if r['scene']['task'] in DEVSET10_TASKS]
        self.registry = {'profile': 'devset10', 'roster_id': 'devset10-v1', 'expected_task_count': 10,
            'source_manifest_sha256': DEVSET10_SOURCE_SHA256,
            'official_seed': 0, 'layout_ordinal': 0, 'round_index': 0,
            'tasks': [t for t in self.full_registry['tasks'] if t['task'] in DEVSET10_TASKS]}

    def tearDown(self):
        self.fixture.tearDown()

    def build(self, runs=None, registry=None, **kwargs):
        return build_panel(self.runs if runs is None else runs,
                           self.registry if registry is None else registry,
                           'original-devset10', profile='devset10', **kwargs)

    def test_explicit_profile_required_and_default_full54_unchanged(self):
        with self.assertRaisesRegex(ValidationError, '54-task'):
            build_panel(self.runs, self.registry, 'ten')
        default = build_panel(self.full_runs, self.full_registry, 'full')
        explicit = build_panel(self.full_runs, self.full_registry, 'full', profile='full54')
        self.assertEqual(default, explicit)
        self.assertEqual(default['summary']['score'], 20)
        self.assertEqual(default['summary']['planned'], 54)
        self.assertIn('official54', default)
        self.assertNotIn('metric_profile', default)

    def test_equal_task_weight_and_clear_non_full54_labels(self):
        for i, run in enumerate(self.runs):
            run['outcome'].update(score=i / 10, success=i < 3)
        panel = self.build()
        self.assertEqual(panel['summary']['score'], 45)
        self.assertEqual(panel['summary']['success_rate'], 30)
        self.assertEqual(panel['summary']['valid'], 10)
        self.assertEqual(panel['summary']['planned'], 10)
        self.assertEqual(panel['summary'], panel['devset10'])
        self.assertNotIn('official54', panel)
        self.assertEqual(panel['metric_profile'], 'devset10')
        self.assertIn('Devset10', panel['metric_label'])
        self.assertIn('not Full54', panel['scope'])
        self.assertFalse(panel['official_leaderboard_submission'])
        self.assertEqual(panel['roster']['source_manifest_sha256'], DEVSET10_SOURCE_SHA256)
        self.assertTrue(all(c['planned'] == 2 for c in panel['summary']['capabilities'].values()))

    def test_arbitrary_ten_task_roster_rejected_despite_claimed_id(self):
        changed = deepcopy(self.registry)
        replacement = next(t for t in self.full_registry['tasks'] if t['task'] not in DEVSET10_TASKS)
        changed['tasks'][0] = replacement
        with self.assertRaisesRegex(ValidationError, 'exactly match'):
            self.build(registry=changed)

    def test_changed_capability_variant_duplicate_or_source_sha_rejected(self):
        for field, value in [('capability', 'Open'), ('variant', 'random')]:
            changed = deepcopy(self.registry)
            target = next(t for t in changed['tasks'] if t['task'] == 'build_tower')
            target[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValidationError, 'exactly match'):
                self.build(registry=changed)
        changed = deepcopy(self.registry); changed['tasks'][0] = changed['tasks'][1]
        with self.assertRaisesRegex(ValidationError, 'exactly match'):
            self.build(registry=changed)
        changed = deepcopy(self.registry); changed['source_manifest_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValidationError, 'source SHA'):
            self.build(registry=changed)

    def test_partial_devset_does_not_fill_missing_task_with_zero(self):
        panel = self.build(runs=self.runs[:-1])
        self.assertIsNone(panel['summary']['score'])
        self.assertIsNone(panel['summary']['success_rate'])
        self.assertFalse(panel['summary']['complete'])
        self.assertEqual(panel['summary']['planned'], 10)
        self.assertEqual(panel['summary']['valid'], 9)
        self.assertEqual(len(panel['summary']['missing_or_incomplete']), 1)

    def test_duplicate_or_unexpected_run_rejected(self):
        with self.assertRaisesRegex(ValidationError, 'exactly one'):
            self.build(runs=self.runs + [self.runs[0]])
        outsider = next(r for r in self.full_runs if r['scene']['task'] not in DEVSET10_TASKS)
        with self.assertRaisesRegex(ValidationError, 'exactly one'):
            self.build(runs=self.runs[:-1] + [outsider])

    def test_original_scene_identity_and_algorithms_stay_strict(self):
        changed = deepcopy(self.runs)
        for run in changed:
            run['scene']['layout_ordinal'] = 1
        with self.assertRaisesRegex(ValidationError, 'seed0/layout0'):
            self.build(runs=changed)
        changed = deepcopy(self.runs); changed[0]['algorithm']['codex_client_version'] = 'different'
        with self.assertRaisesRegex(ValidationError, 'Mixed algorithm'):
            self.build(runs=changed)

    def test_profile_typo_and_full54_roster_fail_closed(self):
        with self.assertRaisesRegex(ValidationError, 'Unknown panel metric profile'):
            validate_panel_registry(self.registry, 'devset')
        with self.assertRaisesRegex(ValidationError, 'explicit profile'):
            self.build(registry=self.full_registry)

    def test_publisher_requires_roster_before_creating_state_or_uploading(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); state = root / 'state'
            args = [str(root), '--panel-id', 'dev', '--algorithm-id', 'algo', '--title', 'Devset10',
                    '--server', 'https://example.invalid', '--library', 'unused',
                    '--site-origin', 'https://example.invalid', '--state', str(state), '--profile', 'devset10']
            with patch.object(publisher, 'upload', side_effect=AssertionError('network prohibited')), \
                 patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    publisher.main(args)
            self.assertFalse(state.exists())

    def test_catalog_retains_profile_for_devset_and_full54_entry_unchanged(self):
        dev = self.build(); full = build_panel(self.full_runs, self.full_registry, 'full')
        with tempfile.TemporaryDirectory() as d:
            web = Path(d)
            for item in (dev, full):
                p = web / 'data/publications' / item['panel_id'] / 'index.json'
                p.parent.mkdir(parents=True); p.write_text(json.dumps(item))
            publisher.update_catalog(web)
            rows = json.loads((web / 'data/publications/catalog.json').read_text())['panels']
            by_id = {r['panel_id']: r for r in rows}
            self.assertEqual(by_id['original-devset10']['metric_profile'], 'devset10')
            self.assertEqual(by_id['original-devset10']['planned'], 10)
            self.assertNotIn('metric_profile', by_id['full'])
            self.assertEqual(by_id['full']['planned'], 54)


if __name__ == '__main__':
    unittest.main()
