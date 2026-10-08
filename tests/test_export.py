import json
from pathlib import Path
import tempfile
import unittest
from robodojo_collab.export_legacy import public, cost_attempts, validate_terminal, deterministic_tar, write


class ExportTests(unittest.TestCase):
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
