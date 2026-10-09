"""Native VLA fixtures are synthetic CPU evidence, never benchmark results."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from robodojo_collab.export_native_vla import export_native_vla,native_vla_metadata
from robodojo_collab.publication import export_publication,validate_publication,build_panel
from robodojo_collab.schema import ValidationError,canonical_bytes,file_sha256,validate_manifest
from robodojo_collab.statistics import cost_summary


class NativeVLAExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.input=self.root/'input';self.input.mkdir();self.output=self.root/'source'
        self.task='solve_equation';self.run='native-vla-unit-fixture'
        self.nr={'success_rate':0.0,'eval_time':1,'score':0.5,'details':{'0':{'layout_id':0,'success':False,'score':0.5}}}
        self.ep={'kind':'episode_complete','time_unix':10,'layout_by_env':{'0':0},'control_steps':[2],'native_results':self.nr,'unstable_envs':[]}
        def event(kind,step,**kwargs):return dict(kind=kind,time_unix=step+1,layout_by_env={'0':0},control_steps=[step],**kwargs)
        self.events=[event('reset_start',0,args=[],kwargs={'seed':[0]}),event('reset_complete',0,step_limit=10),
            event('episode_start',0),event('policy_rpc',0,method='get_action',elapsed_s=0.1,result=[{'joint':[1.0]}]),
            event('action_submit',0,actions=[[{'joint':[1.0]}]]),event('action_complete',1,elapsed_s=0.1,native_end=[False],native_success=[False]),
            event('policy_rpc',1,method='update_obs',elapsed_s=0.1,result=None),
            event('action_submit',1,actions=[[{'joint':[2.0]}]]),event('action_complete',2,elapsed_s=0.1,native_end=[True],native_success=[False]),self.ep]
        self.record={'record_version':'native-vla-private-source-v1','run_id':self.run,'model':'dm05','task':self.task,
            'episode_id':0,'env_index':0,'evaluation_seed':0,'layout_ordinal':0,
            'scene':{'task':self.task,'capability':'Open','variant':'standard','layout_sha256':'a'*64,'simulator':'fixture-simulator'},
            'collection_complete':True,'selected_episode_complete':True,'event_boundary_complete':True,
            'recorded_report_control_steps':2,'cost_evidence':{'prior_infrastructure_attempts_preserved_from_source':[]},
            'algorithm_source_lock':{'historical_checkpoint_sha256':None,'historical_adapter_source_sha256':None},
            'audit':{'sha256':'b'*64}}
        self.record['native_result']=self.file('result.json',canonical_bytes(self.nr))
        metadata={'run_id':self.run,'audit_source_metadata':[{'source_line_sha256':'c'*64,'event':{'kind':'audit_installed','task':self.task,'evaluation_seed':0,'configuration':{'policy_name':'DM05','additional_info':'ckpt_name=fixture'},'policy_configuration':{'policy_name':'DM05'}}}],
            'historical_source_record':{'model':'dm05','score_0_to_100':50.0,'success':False}}
        f=self.file('source.json',canonical_bytes(metadata));self.record.update(source_metadata_path=f['local_path'],source_metadata_sha256=f['sha256'])
        self.write_events()
        self.record['videos']=[dict(self.file(v+'.mp4',('synthetic fixture '+v).encode()),view=v) for v in ('head','left_wrist','right_wrist')]
        self.record['demo']=self.file('demo.mp4',b'synthetic demo fixture')
        self.scenes={'0':{self.task:[{'layout_ordinal':0,'layout_sha256':'a'*64,'original_asset_path':'Assets/Eval_Layout/RoboDojo/arx_x5/0/solve_equation_0.json'}]}}
        self.metadata=native_vla_metadata(self.record,self.scenes)

    def tearDown(self):self.temp.cleanup()

    def file(self,name,data):
        p=self.input/name;p.write_bytes(data)
        return {'local_path':str(p),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}

    def write_events(self):
        lines=[canonical_bytes(e) for e in self.events]
        events=[dict(e,source_line_number=i+2,source_line_sha256=hashlib.sha256(raw).hexdigest()) for i,(e,raw) in enumerate(zip(self.events,lines))]
        f=self.file('selected.jsonl',b''.join(lines));self.record.update(selected_events_original_path=f['local_path'],selected_events_original_sha256=f['sha256'])
        f=self.file('projected.jsonl',b''.join(canonical_bytes(e) for e in events));self.record.update(native_events_path=f['local_path'],native_events_sha256=f['sha256'],native_events_bytes=f['bytes'])
        for name,index in [('episode_complete',len(events)-1),('final_action_complete',len(events)-2)]:
            f=self.file(name+'.jsonl',lines[index]);self.record[name]={'event':self.events[index],
                'original_line_path':f['local_path'],'source_line_number':events[index]['source_line_number'],'source_line_sha256':f['sha256']}

    def export(self,**kwargs):
        return export_native_vla(self.record,self.output,metadata=kwargs.get('metadata',self.metadata),scene_registry=self.scenes)

    def mutate_artifact(self,m,kind,value):
        art=next(a for a in m['artifacts'] if a['kind']==kind);p=self.output/art['path'];p.write_bytes(canonical_bytes(value))
        art.update(sha256=file_sha256(p),bytes=p.stat().st_size)

    def test_image_free_native_export_and_existing_publication_path(self):
        before={p.name:p.read_bytes() for p in self.input.iterdir()}
        result=self.export();m=result['manifest']
        self.assertEqual(validate_manifest(m,self.output),[])
        self.assertEqual(m['execution_kind'],'native_vla')
        self.assertIsNone(m['algorithm']['codex_client_version'])
        self.assertIsNone(m['algorithm']['checkpoint']['sha256'])
        self.assertEqual(m['outcome']['policy_action_requests'],1)
        self.assertEqual(m['outcome']['policy_rpc_calls'],2)
        self.assertIsNone(m['outcome']['vla_inference_calls'])
        self.assertEqual({p.name:p.read_bytes() for p in self.input.iterdir()},before)
        self.assertEqual(self.export()['status'],'already_present')
        pub=export_publication(self.output,self.root/'public')
        self.assertEqual(validate_publication(pub['manifest'],pub['bundle']),[])
        self.assertNotIn('public_session',{a['kind'] for a in m['artifacts']})
        self.assertNotIn('original_image',{a['kind'] for a in m['artifacts']})

    def test_historical_literal_policy_configuration_is_data_not_execution(self):
        source=json.loads(Path(self.record['source_metadata_path']).read_text())
        policy={'policy_name':'DM05','evaluation_id':self.run,'host':'127.0.0.1','port':1234}
        source['audit_source_metadata'][0]['event']['policy_configuration']=repr(policy)
        f=self.file('source.json',canonical_bytes(source));self.record['source_metadata_sha256']=f['sha256']
        metadata=native_vla_metadata(self.record,self.scenes)
        public_policy=metadata['source_lock']['original_launches'][0]['policy_configuration']
        self.assertEqual(public_policy,{'policy_name':'DM05','evaluation_id':self.run})
        source['audit_source_metadata'][0]['event']['policy_configuration']="__import__('os').system('false')"
        f=self.file('source.json',canonical_bytes(source));self.record['source_metadata_sha256']=f['sha256']
        with self.assertRaisesRegex(ValidationError,'safe literal'):
            native_vla_metadata(self.record,self.scenes)

    def test_no_token_zeros_and_unknown_gpu_costs(self):
        m=self.export()['manifest'];summary=cost_summary([m])
        self.assertIsNone(summary['known_total_tokens']);self.assertIsNone(summary['paid_requests'])
        self.assertEqual(summary['llm_cost_applicability'],'not_applicable')
        self.assertIsNone(summary['gpu_hours']);self.assertIsNone(summary['gpu_dollar_cost'])
        self.assertIsNone(summary['vla_inference_calls']);self.assertFalse(summary['attempts_complete'])
        bad=deepcopy(m);bad['costs']['attempts'][0]['input_tokens']=0
        self.assertTrue(any('no zero token receipt' in e for e in validate_manifest(bad,check_files=False)))
        bad=deepcopy(m);bad['algorithm']['codex_client_version']='0.153.4'
        self.assertTrue(any('fabricated Codex' in e for e in validate_manifest(bad,check_files=False)))

    def test_gate_or_missing_original_ack_prevents_manifest(self):
        self.record['event_boundary_complete']=False
        with self.assertRaisesRegex(ValidationError,'gate not complete'):self.export()
        self.assertFalse(self.output.exists())
        self.record['event_boundary_complete']=True
        Path(self.record['final_action_complete']['original_line_path']).unlink()
        with self.assertRaises(ValidationError):self.export()
        self.assertFalse(self.output.exists())

    def test_original_sha_and_numeric_action_projection_are_verified(self):
        events=[json.loads(l) for l in Path(self.record['native_events_path']).read_text().splitlines()]
        next(e for e in events if e['kind']=='action_submit')['actions']=[[{'joint':[999.0]}]]
        f=self.file('projected.jsonl',b''.join(canonical_bytes(e) for e in events))
        self.record.update(native_events_sha256=f['sha256'],native_events_bytes=f['bytes'])
        with self.assertRaisesRegex(ValidationError,'changed original numeric'):self.export()
        self.assertFalse(self.output.exists())

    def test_wrong_scene_or_invented_checkpoint_cannot_emit(self):
        meta=deepcopy(self.metadata);meta['scene']['asset_sha256']='d'*64
        with self.assertRaisesRegex(ValidationError,'scene metadata differs'):self.export(metadata=meta)
        meta=deepcopy(self.metadata);meta['algorithm']['checkpoint']['sha256']='d'*64
        with self.assertRaisesRegex(ValidationError,'Historical policy/checkpoint'):self.export(metadata=meta)
        meta=deepcopy(self.metadata);meta['protocol']['action_limit']=20
        with self.assertRaisesRegex(ValidationError,'prediction horizon'):self.export(metadata=meta)
        self.assertFalse(self.output.exists())

    def test_missing_camera_and_immutable_collision_blocked(self):
        video=self.record['videos'].pop()
        with self.assertRaisesRegex(ValidationError,'three original'):self.export()
        self.record['videos'].append(video);self.export()
        (self.output/'unlisted.png').write_bytes(b'extra')
        with self.assertRaisesRegex(ValidationError,'collision'):self.export()

    def test_mutated_final_ack_rejected_even_after_artifact_rehash(self):
        m=self.export()['publication_manifest']
        art=next(a for a in m['artifacts'] if a['kind']=='native_ack');acks=json.loads((self.output/art['path']).read_text())
        acks[0]['native_success']=[True];self.mutate_artifact(m,'native_ack',acks)
        self.assertTrue(any('final action ACK' in e for e in validate_publication(m,self.output)))

    def test_missing_numeric_prefix_rejected_even_after_rehash(self):
        m=self.export()['publication_manifest'];art=next(a for a in m['artifacts'] if a['kind']=='trajectory')
        trajectory=json.loads((self.output/art['path']).read_text())
        trajectory['native_events']=[e for e in trajectory['native_events'] if not (e['kind']=='action_submit' and e['control_steps']==[0])]
        self.mutate_artifact(m,'trajectory',trajectory)
        self.assertTrue(any('pairs are incomplete' in e for e in validate_publication(m,self.output)))

    def test_readable_actions_and_timeline_cannot_disagree_with_original_events(self):
        m=self.export()['publication_manifest'];art=next(a for a in m['artifacts'] if a['kind']=='trajectory')
        trajectory=json.loads((self.output/art['path']).read_text())
        trajectory['turns'][0]['tool_call']['arguments']['actions']=[[{'joint':[999.0]}]]
        self.mutate_artifact(m,'trajectory',trajectory)
        errors=validate_publication(m,self.output)
        self.assertTrue(any('readable trajectory differs' in e for e in errors))
        self.assertTrue(any('public timeline differs' in e for e in errors))

    def test_original_cumulative_result_selected_episode_is_not_rewritten(self):
        nr=deepcopy(self.nr);nr['details']['1']={'layout_id':1,'success':True,'score':1.0};nr.update(eval_time=2,score=.75,success_rate=.5)
        self.record['native_result']=self.file('result.json',canonical_bytes(nr))
        result=self.export();m=result['publication_manifest']
        self.assertEqual(validate_publication(m,self.output),[])
        self.assertEqual(json.loads((self.output/'evidence/native-result.json').read_text()),nr)
        self.assertEqual(json.loads((self.output/'evidence/episode-complete.json').read_text())['native_results'],self.nr)
        self.assertEqual(m['outcome']['score'],.5)

    def test_original_infrastructure_attempt_remains_unknown(self):
        self.record['cost_evidence']['prior_infrastructure_attempts_preserved_from_source']=[{'run_id':'old-startup','status':'failed','stage':'initialization'}]
        m=self.export()['manifest'];cost=cost_summary([m])
        self.assertEqual(cost['attempt_records'],2);self.assertEqual(cost['infrastructure_attempt_records'],1)
        self.assertIsNone(m['costs']['attempts'][1]['control_steps'])
        self.assertIsNone(cost['unknown_attempts'])


if __name__=='__main__':unittest.main()
