"""CPU-only synthetic shape fixture; never a real benchmark result or video."""
import base64,json,tempfile,unittest
from pathlib import Path
from robodojo_collab.export_new import export_portable,verify_collection
from robodojo_collab.export_legacy import write,sha_file,digest,canonical


class PortableExportTests(unittest.TestCase):
    def fixture(self,root):
        controller=root/'controller';native=root/'collected';run='portable-export-test';h='a'*64
        system='Test public prompt';tools=[{'name':'move_eef'}]
        package={'run_id':run,'algorithm':{'algorithm_id':'offline-export-test','version':'1','model':'none','reasoning_effort':'none','codex_client_version':'none','prompt_sha256':digest(system.encode()),'tools_sha256':digest(json.dumps(tools,sort_keys=True).encode())},'scene':{'task':'solve_equation','official_seed':0,'layout_ordinal':0,'asset_path':'Assets/0/solve_equation_0.json','asset_sha256':h},'protocol':{'id':'offline-test','version':'1','action_limit':20},'attempt':{'index':0,'contributor_id':'test'}}
        write(controller/'package.json',package)
        write(controller/'calls/0000/request.json',{'messages':[{'role':'system','content':system}],'tools':tools})
        write(controller/'calls/0000/paid-start.json',{'time':1})
        write(controller/'calls/0000/usage.json',{'inputTokens':100,'cachedInputTokens':20,'outputTokens':5})
        write(controller/'calls/0000/accounting.json',{'actual_model_responses':1})
        image='data:image/png;base64,'+base64.b64encode(b'offline-test-image').decode()
        write(controller/'session/permanent-history/input-0000.json',{'index':0,'new_messages':[{'role':'system','content':system},{'role':'user','content':[{'type':'text','text':'Env steps remaining before the episode ends: 300'},{'type':'image_url','image_url':{'url':image}}]}]})
        result={'details':{'0':{'layout_id':0,'score':0.0,'success':False}}}
        terminal={'kind':'episode_complete','time_unix':2,'native_results':result,'unstable_envs':[],'control_steps':[1]}
        write(native/'native/_result.json',result)
        (native/'native/audit').mkdir();(native/'native/audit/events.jsonl').write_text(json.dumps(terminal)+'\n')
        env={'simulator_version':'test','machine_id':'test','gpu':None,'driver':None,'os':'test','dependencies':{}}
        info={'run_id':run,'package_sha256':digest(canonical(package)),'started_unix':1,'public_environment':env,'native_source_sha256':{'native.py':h},'source_lock_sha256':h,'policy_sha256':h}
        write(native/'run/native.json',info)
        trace={'run_id':run,'in_progress':False,'llm_calls':1,'instruction':'Test only','turns':[{'policy_step':0,'observation':{'env_step':0},'llm_calls':[{'tool':'move_eef','arguments':{'note':'Original public note'},'accepted':True,'tool_result':'Test feedback'}],'execution':{'env_step_end':1,'cameras':{'head':{'start':0,'end':1}}}}]}
        write(native/'run/trace/layout-0/l3_inspect_transcript.json',trace)
        for view in ('head','left_wrist','right_wrist'):(native/'native'/('episode_0_cam_'+view+'_fail.mp4')).write_bytes(b'NOT-A-VIDEO-TEST-ONLY')
        files=[{'path':p.relative_to(native).as_posix(),'sha256':sha_file(p),'size':p.stat().st_size} for p in native.rglob('*') if p.is_file()]
        write(native/'collection-proof.json',{'run_id':run,'verified':True,'files':files})
        return controller,native,package

    def test_complete_projection_and_idempotence(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);controller,native,pkg=self.fixture(root)
            result=export_portable(controller,native,root/'public')
            manifest=Path(result['bundle'])/'manifest.json';before=manifest.read_bytes()
            export_portable(controller,native,root/'public')
            self.assertEqual(before,manifest.read_bytes())
            text=(Path(result['bundle'])/'evidence/public-session.json').read_text()
            self.assertIn('Original public note',text)
            self.assertNotIn('thread_id',text)
            self.assertTrue((Path(result['bundle'])/'demo/index.html').is_file())

    def test_mutated_collection_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            _,native,pkg=self.fixture(Path(t));(native/'native/_result.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'changed'):verify_collection(native,pkg['run_id'])

    def test_prompt_mismatch_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);controller,native,pkg=self.fixture(root)
            p=controller/'calls/0000/request.json';v=json.loads(p.read_text());v['messages'][0]['content']='changed';p.write_text(json.dumps(v))
            with self.assertRaisesRegex(ValueError,'prompt/tools differ'):export_portable(controller,native,root/'public')
            self.assertFalse((root/'public'/pkg['run_id']/'manifest.json').exists())

if __name__=='__main__':unittest.main()
