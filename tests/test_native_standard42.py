"""Synthetic offline regression for the narrowly scoped Standard42 media contract."""
from copy import deepcopy
from pathlib import Path
import unittest
import test_native_vla as fixtures
from robodojo_collab.export_native_vla import export_native_vla, native_vla_metadata
from robodojo_collab.publication import (STANDARD42_SOURCE_SHA256, STANDARD42_TASKS,
    validate_publication, export_publication)
from robodojo_collab.schema import ValidationError, validate_manifest, native_standard42_media


class NativeStandard42Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NativeVLAExportTests('test_image_free_native_export_and_existing_publication_path')
        self.fixture.setUp()
        self.record = self.fixture.record
        self.registry = {'profile': 'standard42', 'roster_id': 'standard42-v1', 'expected_task_count': 42,
            'source_manifest_sha256': STANDARD42_SOURCE_SHA256,
            'tasks': [{'task': task, 'capability': cap, 'variant': variant} for task, (cap, variant) in STANDARD42_TASKS.items()]}

    def tearDown(self):
        self.fixture.tearDown()

    def metadata(self, registry=None):
        return native_vla_metadata(self.record, self.fixture.scenes, profile='standard42',
            task_registry=self.registry if registry is None else registry)

    def export(self, metadata=None):
        return export_native_vla(self.record, self.fixture.output,
            metadata=self.metadata() if metadata is None else metadata, scene_registry=self.fixture.scenes)

    def remove_demo(self):
        self.record.update(demo=None, demo_available=False)

    def test_explicit_standard42_omits_absent_demo_and_keeps_original_cameras(self):
        self.remove_demo()
        before = {p.name: p.read_bytes() for p in self.fixture.input.iterdir()}
        result = self.export(); m = result['manifest']
        self.assertEqual(validate_manifest(m, self.fixture.output), [])
        self.assertEqual(validate_publication(result['publication_manifest'], self.fixture.output), [])
        self.assertEqual(m['protocol']['metric_profile'], 'standard42')
        self.assertEqual(m['protocol']['id'], 'native-vla-original-standard42-v1')
        self.assertNotIn('Full54 inventory', m['protocol']['selection_policy'])
        self.assertIn('No original demo was indexed', ' '.join(m['audit']['limitations']))
        self.assertEqual(len([a for a in m['artifacts'] if a['kind'] == 'native_video']), 3)
        self.assertNotIn('public_demo', {a['kind'] for a in m['artifacts']})
        self.assertEqual({p.name: p.read_bytes() for p in self.fixture.input.iterdir()}, before)
        public = export_publication(self.fixture.output, self.fixture.root/'public')
        self.assertEqual(validate_publication(public['manifest'], public['bundle']), [])
        self.assertEqual(self.export()['status'], 'already_present')

    def test_default_native_profile_still_requires_demo(self):
        self.remove_demo()
        with self.assertRaisesRegex(ValidationError, 'Original demo required'):
            self.export(metadata=self.fixture.metadata)
        self.assertFalse(self.fixture.output.exists())

    def test_standard42_requires_explicit_pinned_registry(self):
        with self.assertRaisesRegex(ValidationError, 'explicit pinned'):
            native_vla_metadata(self.record, self.fixture.scenes, profile='standard42')
        changed = deepcopy(self.registry); changed['source_manifest_sha256'] = 'd'*64
        with self.assertRaisesRegex(ValidationError, 'source SHA'): self.metadata(changed)
        changed = deepcopy(self.registry); changed['tasks'][0]['task'] = 'invented'
        with self.assertRaisesRegex(ValidationError, 'exactly match'): self.metadata(changed)
        self.record['scene']['variant'] = 'random'
        with self.assertRaisesRegex(ValidationError, 'fixed original'): self.metadata()

    def test_unknown_demo_availability_is_not_absence(self):
        self.record['demo'] = None
        with self.assertRaisesRegex(ValidationError, 'explicitly recorded'): self.metadata()
        self.assertFalse(self.fixture.output.exists())

    def test_three_camera_and_native_ack_requirements_are_not_relaxed(self):
        self.remove_demo(); metadata = self.metadata(); camera = self.record['videos'].pop()
        with self.assertRaisesRegex(ValidationError, 'three original'): self.export(metadata)
        self.record['videos'].append(camera)
        Path(self.record['final_action_complete']['original_line_path']).unlink()
        with self.assertRaises(ValidationError): self.export(metadata)
        self.assertFalse(self.fixture.output.exists())

    def test_standard42_with_recorded_demo_preserves_original_bytes(self):
        result = self.export()
        demo = next(a for a in result['manifest']['artifacts'] if a['kind'] == 'public_demo')
        self.assertEqual(demo['sha256'], self.record['demo']['sha256'])
        self.assertEqual(validate_publication(result['publication_manifest'], self.fixture.output), [])

    def test_media_exception_requires_all_explicit_standard42_native_markers(self):
        self.remove_demo(); result = self.export(); m = result['publication_manifest']
        mutations = [('protocol', 'metric_profile', 'full54'), ('protocol', 'id', 'native-vla-original-full54-v1'),
            ('protocol', 'roster_id', 'arbitrary42'), ('protocol', 'roster_source_sha256', 'd'*64),
            ('protocol', 'demo_policy', 'optional'), ('scene', 'variant', 'random'),
            ('scene', 'task', 'not-in-roster'), ('scene', 'capability', 'Memory')]
        for section, key, value in mutations:
            changed = deepcopy(m); changed[section][key] = value
            self.assertTrue(any('public_demo' in e for e in validate_publication(changed, check_files=False)), (section, key))
        changed = deepcopy(m); changed['execution_kind'] = 'codex'
        self.assertTrue(any('public_demo' in e for e in validate_publication(changed, check_files=False)))

    def test_full54_and_devset10_demo_requirement_unchanged(self):
        original = self.fixture.export()['publication_manifest']
        for profile in ('full54', 'devset10'):
            changed = deepcopy(original)
            changed['protocol']['metric_profile'] = profile
            changed['artifacts'] = [a for a in changed['artifacts'] if a['kind'] != 'public_demo']
            self.assertTrue(any('public_demo' in e for e in validate_publication(changed, check_files=False)))

    def test_malformed_scope_never_qualifies_for_media_exception(self):
        for value in ({'protocol': None}, {'scene': None}, {'scene': {'task': []}}):
            self.assertFalse(native_standard42_media(value))


if __name__ == '__main__':
    unittest.main()
