"""Synthetic CPU regression cases for original cumulative native episodes."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import unittest
import test_native_vla as fixtures
from robodojo_collab.export_native_vla import export_native_vla,native_vla_metadata
from robodojo_collab.schema import canonical_bytes,ValidationError,validate_manifest,validate_native_vla_evidence


class NativeEpisodeBoundaryTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.NativeVLAExportTests();f.setUp();self.f=f
        self.addCleanup(f.tearDown)
        f.record.update(episode_id=1,layout_ordinal=1,recorded_report_control_steps=None,observed_native_control_steps=2,demo=None,demo_available=False)
        f.scenes['0'][f.task][0]['layout_ordinal']=1
        f.nr={'eval_time':3,'score':50.0,'success_rate':1/3,'details':{'0':{'layout_id':0,'success':True,'score':1.0},'1':{'layout_id':1,'success':False,'score':0.5},'2':{'layout_id':2,'success':False,'score':0.0}}}
        f.ep.update(layout_by_env={'0':1},native_results={'eval_time':2,'score':75.0,'success_rate':0.5,'details':{k:v for k,v in f.nr['details'].items() if k in ('0','1')}})
        for e in f.events:e['layout_by_env']={'0':1}
        f.events[0].update(layout_by_env={'0':0},control_steps=[12],kwargs={'seed':[1]})
        f.events.insert(1,{'kind':'policy_rpc','time_unix':1.1,'layout_by_env':{'0':1},'control_steps':[0],'method':'reset','elapsed_s':0.1,'result':None})
        f.record['native_result']=f.file('result.json',canonical_bytes(f.nr))
        source=json.loads(Path(f.record['source_metadata_path']).read_text());source['historical_source_record'].update(source_kind='historical_multi_episode',control_steps_reported=None)
        f.record['source_metadata_sha256']=f.file('source.json',canonical_bytes(source))['sha256']
        self.sync()
        roster={'expected_task_count':42,'profile':'standard42','roster_id':'standard42-v1','source_manifest_sha256':'5b4c87033126d285ef3be773a027c02600d621fdad478e99f2e124f7f15a4728'}
        from robodojo_collab.schema import STANDARD42_CAPABILITY_TASKS
        roster['tasks']=[{'task':task,'capability':cap,'variant':'standard'} for cap,tasks in STANDARD42_CAPABILITY_TASKS.items() for task in tasks]
        self.roster=roster
        f.metadata=native_vla_metadata(f.record,f.scenes,profile='standard42',task_registry=roster)

    def sync(self):
        self.f.write_events();self.f.record['audit']['selected_event_counts']=dict(Counter(e['kind'] for e in self.f.events))

    def export(self):
        return export_native_vla(self.f.record,self.f.output,metadata=self.f.metadata,scene_registry=self.f.scenes)

    def test_previous_episode_reset_kept_and_report_null_is_not_observed_count(self):
        result=self.export();m=result['manifest'];self.assertEqual(validate_manifest(m,self.f.output),[])
        trace=json.loads((self.f.output/'evidence/trajectory.json').read_text());self.assertEqual(trace['native_events'][0]['layout_by_env'],{'0':0});self.assertEqual(trace['native_events'][0]['control_steps'],[12]);self.assertEqual(trace['native_events'][1]['method'],'reset')
        lock=json.loads((self.f.output/'evidence/source-lock.json').read_text());self.assertIsNone(lock['original_selection']['reported_control_steps']);self.assertEqual(lock['original_selection']['observed_native_control_steps'],2)
        self.assertEqual((self.f.output/'evidence/native-result.json').read_bytes(),Path(self.f.record['native_result']['local_path']).read_bytes());self.assertEqual(m['outcome']['score'],0.5)

    def test_real_cross_layout_action_or_rpc_is_rejected(self):
        for kind in ('action_submit','policy_rpc'):
            with self.subTest(kind=kind):
                events=deepcopy(self.f.events);target=next(e for e in self.f.events[4:] if e['kind']==kind);target['layout_by_env']={'0':8};self.sync()
                with self.assertRaises(ValidationError):self.export()
                self.f.events=events;self.sync()

    def test_reset_must_be_initial_and_zero_target_reset_complete(self):
        for mutate in (lambda es:es[2].update(control_steps=[1]),lambda es:es[2].update(layout_by_env={'0':8}),lambda es:es[1].update(method='get_action'),lambda es:es.insert(0,deepcopy(es[1]))):
            with self.subTest(mutate=mutate):
                events=deepcopy(self.f.events);mutate(self.f.events);self.sync()
                with self.assertRaises(ValidationError):self.export()
                self.f.events=events;self.sync()

    def test_observed_missing_wrong_or_report_known_wrong_remains_rejected(self):
        for reported,observed in ((None,None),(None,3),(3,2)):
            with self.subTest(reported=reported,observed=observed):
                self.f.record.update(recorded_report_control_steps=reported,observed_native_control_steps=observed)
                with self.assertRaises(ValidationError):self.export()

    def test_prefix_may_not_mix_units_with_same_final_original_result(self):
        self.f.ep['native_results']['score']=0.75;self.sync()
        with self.assertRaises(ValidationError):self.export()

    def test_wrong_final_aggregate_or_success_rate_rejected(self):
        for field,value in (('score',55.0),('success_rate',0.5)):
            with self.subTest(field=field):
                nr=deepcopy(self.f.nr);nr[field]=value;self.f.record['native_result']=self.f.file('result.json',canonical_bytes(nr))
                with self.assertRaises(ValidationError):self.export()

    def test_final_ack_success_or_controls_mismatch_rejected(self):
        self.f.events[-2]['native_success']=[True];self.sync()
        with self.assertRaises(ValidationError):self.export()


if __name__=='__main__':unittest.main()
