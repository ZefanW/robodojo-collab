import json
from pathlib import Path
import tempfile
import unittest
from robodojo_collab.export_legacy import public, cost_attempts, validate_terminal, deterministic_tar, write, protocol_metadata, INITIAL_SAMPLE_RUNS


class ExportTests(unittest.TestCase):
    def test_original_four_sample_metadata_is_unchanged(self):
        for run in INITIAL_SAMPLE_RUNS:
            metadata, compatible = protocol_metadata({}, run)
            self.assertTrue(compatible)
            self.assertEqual(metadata, {'scope': 'representative-import', 'action_limit': 20,
                'round_index': 0, 'selection_policy': 'All selected solve_equation variants, independent of outcome; not best-of selection.'})

    def test_explicit_historical_metadata_preserves_15_and_round_1(self):
        metadata, compatible = protocol_metadata({'case': {'round_index': 1}}, 'historical-run',
            scope='official-scene-repetitions', action_limit=15, selection_policy='All original attempts, independent of outcome.')
        self.assertFalse(compatible)
        self.assertEqual(metadata['action_limit'], 15)
        self.assertEqual(metadata['round_index'], 1)
        self.assertEqual(metadata['scope'], 'official-scene-repetitions')

    def test_unknown_cap_stays_null_and_unknown_round_rejected(self):
        metadata, _ = protocol_metadata({}, 'old-long-action', round_index=0)
        self.assertIsNone(metadata['action_limit'])
        self.assertIn('unspecified', metadata['selection_policy'])
        with self.assertRaisesRegex(ValueError, 'round index is unknown'):
            protocol_metadata({'case': {'layout_ordinal': 0}}, 'old-long-action')

    def test_round_conflict_and_invalid_explicit_limits_rejected(self):
        with self.assertRaisesRegex(ValueError, 'disagrees'):
            protocol_metadata({'case': {'round_index': 1}}, 'run', round_index=0)
        for value in [-1, True, '20']:
            with self.assertRaisesRegex(ValueError, 'Action limit'):
                protocol_metadata({}, 'run', round_index=0, action_limit=value)

    def test_explicit_metadata_overrides_sample_compatibility(self):
        metadata, compatible = protocol_metadata({}, next(iter(INITIAL_SAMPLE_RUNS)),
            scope='historical-import', action_limit=20, round_index=0,
            selection_policy='All original completed runs, independent of outcome.')
        self.assertFalse(compatible)
        self.assertEqual(metadata['scope'], 'historical-import')

    def test_allowlist_secondary_redaction(self):
        x=public({'account_id':'private','safe':'abc','nested':{'reasoning':'hidden','path':'/Users/person/private'},'list':[{'thread_id':'s','value':3}]})
        self.assertEqual(x,{'safe':'abc','nested':{'path':'[redacted private infrastructure reference]'},'list':[{'value':3}]})

    def test_missing_usage_is_not_zero_and_mirrors_count_once(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            paid={'thread_id':'x','request_sha256':'a','time':1}
            for n in ['0000','0000/retry-copy']:
                write(root/n/'paid-start.json',paid)
            result=cost_attempts(root)
            self.assertEqual(len(result),1)
            self.assertIsNone(result[0]['input_tokens'])
            self.assertIsNone(result[0]['model_responses'])
            self.assertFalse(result[0]['usage_known'])

    def test_unknown_identity_does_not_deduplicate_distinct_attempts(self):
        with tempfile.TemporaryDirectory() as t:
            for n in ['0000','0001']:
                write(Path(t)/n/'paid-start.json',{})
            self.assertEqual(len(cost_attempts(Path(t))),2)

    def test_explicit_null_usage_stays_unknown(self):
        with tempfile.TemporaryDirectory() as t:
            for n, explicit_usage in [('0000', True), ('0001', False)]:
                p = Path(t) / n
                write(p / 'paid-start.json', {})
                write(p / 'response.json', {'tokens': None})
                if explicit_usage:
                    write(p / 'usage.json', None)
            attempts = cost_attempts(Path(t))
            self.assertEqual(len(attempts), 2)
            self.assertTrue(all(not a['usage_known'] and a['input_tokens'] is None
                                for a in attempts))

    def test_selected_retry_mirror_does_not_invent_original_usage(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / '0076'
            retry = root / 'retries' / '001'
            usage = {'inputTokens': 100, 'cachedInputTokens': 80, 'outputTokens': 7}
            write(root / 'selected-attempt.json', {'attempt_path': 'retries/001'})
            for index, folder in enumerate([root, retry]):
                write(folder / 'paid-start.json', {'thread_id': 'same-thread',
                    'request_sha256': 'same-request', 'time': index})
                write(folder / 'response.json', {'tokens': usage, 'actual_model_responses': 1})
                write(folder / 'accounting.json', {'actual_model_responses': 1})
            write(retry / 'usage.json', usage)
            attempts = cost_attempts(Path(t))
            self.assertEqual(len(attempts), 2)
            self.assertFalse(attempts[0]['usage_known'])
            self.assertIsNone(attempts[0]['input_tokens'])
            self.assertIsNone(attempts[0]['model_responses'])
            self.assertEqual(attempts[1]['input_tokens'], 100)
            self.assertEqual(attempts[1]['model_responses'], 1)

    def test_cached_input_subset(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'0000'
            write(p/'paid-start.json',{})
            write(p/'usage.json',{'inputTokens':10,'cachedInputTokens':11,'outputTokens':1})
            with self.assertRaisesRegex(ValueError,'subset'):cost_attempts(Path(t))

    def test_terminal_checks_counts_and_outcome(self):
        outcome={'layout_id':0,'success':False,'score':0.0}
        native={'details':{'0':outcome}}
        terminal={'kind':'episode_complete','unstable_envs':[],'native_results':native,'control_steps':[300]}
        row={'status':'complete','control_steps':300,'native_outcome':outcome}
        self.assertEqual(validate_terminal(row,native,terminal),outcome)
        row['control_steps']=299
        with self.assertRaisesRegex(ValueError,'control count'):validate_terminal(row,native,terminal)
        row['status']='running'
        with self.assertRaisesRegex(ValueError,'complete immutable'):validate_terminal(row,native,terminal)

    def test_deterministic_and_conflict_safe(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);bundle=root/'bundle';write(bundle/'a.json',{'a':1});write(bundle/'a.json',{'a':1})
            with self.assertRaisesRegex(ValueError,'different existing'):write(bundle/'a.json',{'a':2})
            first=deterministic_tar(bundle,root/'one.tar');second=deterministic_tar(bundle,root/'two.tar')
            self.assertEqual(first['sha256'],second['sha256'])
            with self.assertRaisesRegex(ValueError,'already exists'):deterministic_tar(bundle,root/'one.tar')


if __name__=='__main__':unittest.main()
