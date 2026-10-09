"""CPU-only Standard42 contract: no model, simulator, network or uploads."""
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_publication as fixtures
from robodojo_collab.publication import (STANDARD42_SOURCE_SHA256, STANDARD42_TASKS,
    build_panel, validate_panel_registry)
from robodojo_collab.schema import ValidationError
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('standard42_publisher', ROOT / 'scripts/publish_panel.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class Standard42PublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PublicationTests('test_image_free_sidecar_preserves_source_and_full_costs')
        self.fixture.setUp()
        self.full_runs, self.full_registry = self.fixture.panel_runs()
        self.runs = [r for r in self.full_runs if r['scene']['task'] in STANDARD42_TASKS]
        self.registry = {'profile': 'standard42', 'roster_id': 'standard42-v1',
            'expected_task_count': 42, 'source_manifest_sha256': STANDARD42_SOURCE_SHA256,
            'tasks': [t for t in self.full_registry['tasks'] if t['task'] in STANDARD42_TASKS]}

    def tearDown(self):
        self.fixture.tearDown()

    def build(self, runs=None, registry=None, **kwargs):
        return build_panel(self.runs if runs is None else runs,
            self.registry if registry is None else registry, 'standard42-fixture', profile='standard42', **kwargs)

    def test_explicit_profile_required_and_original_group_counts(self):
        with self.assertRaisesRegex(ValidationError, '54-task'):
            build_panel(self.runs, self.registry, 'default')
        panel = self.build()
        self.assertEqual([x['planned'] for x in panel['summary']['capabilities'].values()], [12, 6, 8, 8, 8])
        self.assertTrue(all(r['variant'] == 'standard' for r in panel['runs']))
        self.assertIn('push_T', {r['task'] for r in panel['runs']})
        self.assertNotIn('push_T_random', {r['task'] for r in panel['runs']})

    def test_five_capability_weights_not_unweighted_42_task_mean(self):
        for run in self.runs:
            yes = run['scene']['capability'] == 'Generalization'
            run['outcome'].update(score=float(yes), success=yes)
        panel = self.build()
        self.assertEqual(panel['summary']['score'], 20)
        self.assertEqual(panel['summary']['success_rate'], 20)
        self.assertNotAlmostEqual(panel['summary']['score'], 100 * 12 / 42)
        self.assertEqual(panel['summary']['capabilities']['Generalization']['score'], 100)
        self.assertEqual(panel['summary']['valid'], 42)

    def test_mean_within_capability_then_equal_capabilities(self):
        for run in self.runs: run['outcome'].update(score=0.0, success=False)
        memory = [r for r in self.runs if r['scene']['capability'] == 'Memory']
        memory[0]['outcome'].update(score=1.0, success=True)
        panel = self.build()
        self.assertAlmostEqual(panel['summary']['score'], 100 / 6 / 5)
        self.assertAlmostEqual(panel['summary']['success_rate'], 100 / 6 / 5)

    def test_clear_non_full54_label_and_original_costs(self):
        panel = self.build()
        self.assertEqual(panel['metric_profile'], 'standard42')
        self.assertEqual(panel['summary'], panel['standard42'])
        self.assertIn('Standard42', panel['metric_label'])
        self.assertIn('not Full54', panel['scope'])
        self.assertNotIn('official54', panel)
        self.assertNotIn('devset10', panel)
        self.assertFalse(panel['official_leaderboard_submission'])
        self.assertEqual(panel['roster']['source_manifest_sha256'], STANDARD42_SOURCE_SHA256)
        self.assertEqual(panel['costs']['unknown_attempts'], 42)
        self.assertEqual(panel['costs']['known_total_tokens'], 42 * 107)

    def test_arbitrary_42_roster_and_random_substitution_rejected(self):
        changed = deepcopy(self.registry); changed['tasks'][0]['task'] = 'invented_standard_task'
        with self.assertRaisesRegex(ValidationError, 'exactly match'): self.build(registry=changed)
        changed = deepcopy(self.registry)
        index = next(i for i, r in enumerate(changed['tasks']) if r['task'] == 'push_T')
        changed['tasks'][index] = next(t for t in self.full_registry['tasks'] if t['task'] == 'push_T_random')
        with self.assertRaisesRegex(ValidationError, 'exactly match'): self.build(registry=changed)

    def test_roster_id_hash_capability_variant_and_duplicates_fail_closed(self):
        for mutation in ('id', 'hash', 'capability', 'variant', 'duplicate'):
            changed = deepcopy(self.registry)
            if mutation == 'id': changed['roster_id'] = 'arbitrary42'
            elif mutation == 'hash': changed['source_manifest_sha256'] = '0' * 64
            elif mutation == 'capability': changed['tasks'][0]['capability'] = 'Generalization'
            elif mutation == 'variant': changed['tasks'][0]['variant'] = 'random'
            else: changed['tasks'][0] = changed['tasks'][1]
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError): self.build(registry=changed)

    def test_41_of_42_has_null_overall_and_no_missing_zero(self):
        omitted = next(r for r in self.runs if r['scene']['capability'] == 'Memory')
        panel = self.build(runs=[r for r in self.runs if r is not omitted])
        self.assertFalse(panel['summary']['complete'])
        self.assertIsNone(panel['summary']['score'])
        self.assertIsNone(panel['summary']['success_rate'])
        self.assertEqual(panel['summary']['missing_or_incomplete'], [omitted['scene']['task']])
        self.assertIsNone(panel['summary']['capabilities']['Memory']['score'])
        self.assertEqual(panel['summary']['capabilities']['Open']['score'], 100)

    def test_random_full54_extra_or_duplicate_runs_never_borrowed(self):
        random = next(r for r in self.full_runs if r['scene']['task'] == 'push_T_random')
        without_push = [r for r in self.runs if r['scene']['task'] != 'push_T']
        for runs in (self.full_runs, without_push + [random], self.runs + [self.runs[0]]):
            with self.subTest(count=len(runs)), self.assertRaisesRegex(ValidationError, 'exactly one'):
                self.build(runs=runs)

    def test_same_recorded_scene_identity_but_no_layout_borrowing(self):
        runs = deepcopy(self.runs)
        for run in runs: run['scene'].update(official_seed=1, layout_ordinal=3, round_index=3)
        panel = self.build(runs=runs)
        self.assertEqual((panel['official_seed'], panel['layout_ordinal'], panel['round_index']), (1, 3, 3))
        runs[0]['scene']['layout_ordinal'] = 0
        with self.assertRaisesRegex(ValidationError, 'one common seed'): self.build(runs=runs)

    def test_unknown_native_success_cannot_be_zero_filled(self):
        runs = deepcopy(self.runs); runs[0]['outcome']['success'] = None
        with self.assertRaises(ValidationError): self.build(runs=runs)

    def test_publisher_requires_explicit_roster_before_any_upload(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); state = root / 'state'
            args = [str(root), '--panel-id', 'standard', '--algorithm-id', 'algo', '--title', 'Standard42',
                    '--server', 'https://example.invalid', '--library', 'unused',
                    '--site-origin', 'https://example.invalid', '--state', str(state), '--profile', 'standard42']
            with patch.object(publisher, 'upload', side_effect=AssertionError('upload prohibited')), \
                 patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit): publisher.main(args)
            self.assertFalse(state.exists())

    def test_incomplete_publisher_stops_before_archive_or_upload(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bundles = root / 'bundles'; bundles.mkdir()
            roster = root / 'standard42-roster.json'; roster.write_text(json.dumps(self.registry))
            for run in self.runs[:-1]:
                p = bundles / run['run_id']; p.mkdir(); (p / 'publication-manifest.json').write_text(json.dumps(run))
            args = [str(bundles), '--panel-id', 'standard', '--algorithm-id', self.runs[0]['algorithm']['algorithm_id'],
                    '--title', 'Standard42', '--server', 'https://example.invalid', '--library', 'unused',
                    '--site-origin', 'https://example.invalid', '--state', str(root/'state'), '--profile', 'standard42',
                    '--task-registry', str(roster)]
            original_read = publisher.read
            with patch.object(publisher, 'read', side_effect=lambda p: {} if Path(p).name == 'scenes.json' else original_read(p)), \
                 patch.object(publisher, 'validate_publication', return_value=[]), \
                 patch.object(publisher, 'validate_registered_scene', return_value=[]), \
                 patch.object(publisher, 'metadata_tar', side_effect=AssertionError('archive prohibited')), \
                 patch.object(publisher, 'upload', side_effect=AssertionError('upload prohibited')):
                with self.assertRaisesRegex(ValueError, 'all 42 original standard valid native terminals'):
                    publisher.main(args)

    def test_catalog_preserves_standard42_metric_label(self):
        panel = self.build()
        with tempfile.TemporaryDirectory() as d:
            web = Path(d); p = web / 'data/publications/standard/index.json'; p.parent.mkdir(parents=True)
            p.write_text(json.dumps(panel)); publisher.update_catalog(web)
            entry = json.loads((web / 'data/publications/catalog.json').read_text())['panels'][0]
            self.assertEqual(entry['metric_profile'], 'standard42')
            self.assertEqual(entry['planned'], 42)
            self.assertEqual(entry['roster']['id'], 'standard42-v1')
            self.assertIn('not Full54', entry['scope'])


if __name__ == '__main__': unittest.main()
