"""CPU-only original-camera exception tests; fixtures never run an experiment."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from robodojo_collab.schema import (validate_manifest, persistent_original_media,
 PERSISTENT_ORIGINAL_DEMO_POLICY as POLICY, PERSISTENT_ORIGINAL_DEMO_NOTE as NOTE,
 PERSISTENT_ORIGINAL_DEMO_TASKS as TASKS)
from robodojo_collab.publication import export_publication, validate_publication
from robodojo_collab.export_legacy import export_run,sha_file,write
import test_publication as fixtures

class PersistentMediaTests(unittest.TestCase):
 def setUp(self):
  self.f=fixtures.PublicationTests();self.f.setUp();self.m=self.f.m
  self.m['run_id']='l3_persistent_v1_solve_equation_s0_layout0_20261002_v1'
  self.m['algorithm']['algorithm_id']='astra_l3_persistent'
  self.m['protocol'].update(id='l3-expansion-20261002',scope='historical-import',action_limit=None)
  self.m['scene'].update(official_seed=0,layout_ordinal=0)
  self.m['audit'].update(media_policy=POLICY,original_demo_available=False,original_demo_note=NOTE)
  self.m['artifacts']=[a for a in self.m['artifacts'] if a['kind']!='public_demo']
  self.f.put('trajectory.json','trajectory',{'run_id':self.m['run_id'],'turns':[]});self.f.save()
 def tearDown(self):self.f.tearDown()
 def test_all_nine_exact_identities(self):
  for task,(cap,var) in TASKS.items():
   m=deepcopy(self.m);m['run_id']=f'l3_persistent_v1_{task}_s0_layout0_20261002_v1';m['scene'].update(task=task,capability=cap,variant=var)
   self.assertTrue(persistent_original_media(m));self.assertEqual(validate_manifest(m,check_files=False),[])
 def test_full_source_and_publication_gates(self):
  before=(self.f.source/'manifest.json').read_bytes();self.assertEqual(validate_manifest(self.m,self.f.source),[])
  r=self.f.export();p=r['manifest'];self.assertEqual(validate_publication(p,r['bundle']),[])
  self.assertEqual(p['costs'],self.m['costs']);self.assertEqual(p['outcome'],self.m['outcome']);self.assertEqual(before,(self.f.source/'manifest.json').read_bytes())
 def test_identity_mutations_cannot_relax_demo(self):
  changes=[('algorithm','algorithm_id','astra_l3_persistent_cap20'),('protocol','id','l3-final-baselines-20261003'),('protocol','scope','devset10'),('protocol','action_limit',20),('scene','official_seed',1),('scene','layout_ordinal',1),('scene','task','align_blocks'),('scene','capability','Memory'),('scene','variant','random'),('audit','media_policy','optional'),('audit','original_demo_available',True),('audit','original_demo_note','')]
  for section,key,value in changes:
   m=deepcopy(self.m);m[section][key]=value;self.assertFalse(persistent_original_media(m));self.assertTrue(any('public_demo' in e for e in validate_manifest(m,check_files=False)))
  m=deepcopy(self.m);m['run_id']+='-retry';self.assertFalse(persistent_original_media(m))
 def test_other_core_evidence_and_privacy_still_required(self):
  p=self.f.export()['manifest']
  for kind in ('native_video','native_ack','native_result','trajectory','costs'):
   m=deepcopy(p);m['artifacts'].remove(next(a for a in m['artifacts'] if a['kind']==kind));self.assertTrue(validate_publication(m,check_files=False),kind)
  m=deepcopy(p);m['audit']['secret']='/'.join(('', 'Users', 'fixture', 'secret'));self.assertTrue(validate_publication(m,check_files=False))
 def test_absent_marker_rejects_existing_demo(self):
  self.f.put('demo.mp4','public_demo',b'clip','video/mp4');self.assertTrue(any('conflicts' in e for e in validate_manifest(self.m,check_files=False)))
 def test_malformed_scope(self):
  for m in (None,[],{'scene':[]},{'audit':None},{'scene':{'task':[]}}):self.assertFalse(persistent_original_media(m))

class PersistentExporterTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.base=Path(self.t.name);self.src=self.base/'source';self.rid='l3_persistent_v1_solve_equation_s0_layout0_20261002_v1';self.v=self.src/'videos'/self.rid;self.v.mkdir(parents=True)
  self.kw=dict(run_id=self.rid,runtime='runtime',video_root='videos',protocol='l3-expansion-20261002',algorithm_id='astra_l3_persistent',evidence=self.base/'native.json',client_version='0.153.4',scope='historical-import',action_limit=None,round_index=0,include_images=False,original_demo_policy=POLICY)
  outcome={'score':.5,'success':False,'layout_id':0};nr={'details':{'0':outcome}};ep={'kind':'episode_complete','native_results':nr,'control_steps':[12],'unstable_envs':[]}
  write(self.kw['evidence'],{'native_result':nr,'events':[{'kind':'action_complete','control_steps':[12]},ep]});checks={}
  for view in ('head','left_wrist','right_wrist'):
   p=self.v/f'episode_0_cam_{view}_test.mp4';p.write_bytes(b'original '+view.encode());checks[p.name]=sha_file(p)
  row={'status':'complete','control_steps':12,'model_decisions':1,'native_outcome':outcome,'video_checksums':checks,'case':{'task':'solve_equation','capability':'Open','variant':'standard','evaluation_seed':0,'layout_ordinal':0,'layout_sha256':'a'*64,'original_asset_path':'Open/solve_equation/0/0.json','simulator':'Sim6'}}
  write(self.v/'native-source.json',row);write(self.v/'public-transcript.json',{'run_id':self.rid,'in_progress':False,'turns':[]})
  write(self.v/'original-transcript-verification.json',{'run_id':self.rid,'verified':True,'evidence_sha256':'b'*64,'transcript_sha256':sha_file(self.v/'public-transcript.json'),'derived_export_compatibility_only':True})
  write(self.src/'runtime/archives'/f'{self.rid}.json',{'verified':True,'videos_sha256':True,'receipts_and_sessions_sha256':True,'demo_sha256':False})
  call=self.src/'runtime/calls'/self.rid/'0000';write(call/'request.json',{'model':'gpt-6-astra','reasoning_effort':'medium','messages':[{'role':'system','content':'original instruction'}],'tools':[]});write(call/'paid-start.json',{});write(call/'usage.json',{'inputTokens':10,'cachedInputTokens':8,'outputTokens':2});write(call/'accounting.json',{'actual_model_responses':1})
  history=self.src/'runtime/codex'/self.rid/'permanent-history/input-0.json';write(history,{'index':0,'new_messages':[{'role':'user','content':'Env steps remaining before the episode ends: 100'}]});files={}
  for p in (call/'request.json',call/'paid-start.json',call/'usage.json',call/'accounting.json',history):
   rel=p.relative_to(self.src/'runtime').parts;files['/'.join([rel[0],*rel[2:]])]={'sha256':sha_file(p)}
  write(self.v/'local-receipts-sha256.json',{'files':files});write(self.v/'receipts-remote-verified.json',{'verified':True,'manifest_sha256':sha_file(self.v/'local-receipts-sha256.json')});write(self.src/'protocol/l3-expansion-20261002/source-lock.json',{'files':{}})
 def tearDown(self):self.t.cleanup()
 def export(self,**extra):return export_run(self.src,self.base/'out',**(self.kw|extra))
 def test_real_export_without_fabricated_demo(self):
  r=self.export();m=json.loads((Path(r['bundle'])/'manifest.json').read_text());self.assertEqual(validate_manifest(m,r['bundle']),[])
  p=export_publication(r['bundle'],self.base/'public');self.assertEqual(validate_publication(p['manifest'],p['bundle']),[]);self.assertFalse((self.v/'rationale-demo.json').exists())
 def test_trace_proof_required(self):
  (self.v/'original-transcript-verification.json').unlink()
  with self.assertRaises(FileNotFoundError):self.export()
 def test_wrong_identity_and_existing_demo_rejected(self):
  with self.assertRaisesRegex(ValueError,'allowlisted'):self.export(action_limit=20)
  (self.v/'04_three_views_rationale.mp4').write_bytes(b'existing')
  with self.assertRaisesRegex(ValueError,'cannot omit'):self.export()
 def test_camera_required(self):
  next(self.v.glob('*cam_head*')).unlink()
  with self.assertRaisesRegex(ValueError,'Exactly one'):self.export()
 def test_wrong_trace_bytes_rejected(self):
  p=self.v/'public-transcript.json';p.write_text(p.read_text()+' ')
  with self.assertRaisesRegex(ValueError,'transcript checksum'):self.export()
 def test_marker_requires_verified_original_cameras(self):
  p=self.src/'runtime/archives'/f'{self.rid}.json';m=json.loads(p.read_text());m['videos_sha256']=False;p.write_text(json.dumps(m))
  with self.assertRaisesRegex(ValueError,'Archive marker'):self.export()
 def test_default_media_rule_unchanged(self):
  with self.assertRaises(FileNotFoundError):self.export(original_demo_policy=None)

if __name__=='__main__':unittest.main()
