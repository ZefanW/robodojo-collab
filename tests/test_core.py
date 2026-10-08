import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from robodojo_collab.cli import make_sample,import_bundle,build_index
from robodojo_collab.schema import load_manifest,validate_manifest,ValidationError,privacy_findings
from robodojo_collab.statistics import official_summary,cumulative_summary,cost_summary
from robodojo_collab import claims

ROOT=Path(__file__).resolve().parents[1]

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        make_sample(self.root/'sample');self.m=load_manifest(self.root/'sample')
    def tearDown(self):self.tmp.cleanup()
    def test_fixture_and_idempotent_import(self):
        self.assertEqual(import_bundle(self.root/'sample',self.root/'store')['status'],'imported')
        self.assertEqual(import_bundle(self.root/'sample',self.root/'store')['status'],'already_present')
        self.m['attempt']['reason']='changed'
        (self.root/'sample/manifest.json').write_text(json.dumps(self.m))
        with self.assertRaises(ValidationError):import_bundle(self.root/'sample',self.root/'store')
    def test_sha_and_unlisted_secret_is_not_copied(self):
        (self.root/'sample/auth.json').write_text('SECRET')
        import_bundle(self.root/'sample',self.root/'store')
        self.assertFalse((self.root/'store/offline-fixture-001/auth.json').exists())
        (self.root/'sample/public-fixture.json').write_text('{}')
        self.assertTrue(any('mismatch' in e for e in validate_manifest(self.m,self.root/'sample')))
    def test_seed3_and_traversal_rejected(self):
        self.m['scene']['official_seed']=3;self.m['artifacts'][0]['path']='../secret'
        errors=validate_manifest(self.m)
        self.assertTrue(any('official_seed' in e for e in errors));self.assertTrue(any('unsafe' in e for e in errors))
    def test_privacy_rejects_raw_analysis_and_paths(self):
        self.assertTrue(privacy_findings({'reasoning':'private','x':'/Users/private/data','authorization':'Bearer abcdefghijklmno'}))
        self.assertFalse(privacy_findings({'reasoning_effort':'medium','public_note':'Move to the red block.'}))
    def test_cache_subset_and_unknown(self):
        self.m['costs']['attempts']=[{'attempt_id':'1','input_tokens':100,'cached_input_tokens':90,'output_tokens':5,'paid_requests':1,'model_responses':1,'usage_known':True},{'attempt_id':'2','input_tokens':None,'cached_input_tokens':None,'output_tokens':None,'paid_requests':1,'model_responses':None,'usage_known':False}]
        c=cost_summary([self.m]);self.assertEqual(c['known_total_tokens'],105);self.assertEqual(c['unknown_attempts'],1);self.assertFalse(c['complete'])
        self.m['costs']['attempts'][0]['cached_input_tokens']=101
        self.assertTrue(any('subset' in e for e in validate_manifest(self.m)))
    def test_complete_requires_native_evidence(self):
        self.m['status']='complete';self.m['outcome']['score']=1
        self.assertTrue(any('complete:' in e for e in validate_manifest(self.m)))
    def test_native_terminal_mismatch_is_rejected_after_rehash(self):
        import hashlib
        from robodojo_collab.schema import canonical_bytes
        self.m['protocol']['scope']='unit-test-native-evidence'
        self.m['status']='complete';self.m['outcome'].update(native_result=True,episode_complete=True,evidence_consistent=True,score=1.0,success=True,control_steps=12)
        nr={'details':{'0':{'score':1.0,'success':True}},'score':100}
        ep={'kind':'episode_complete','control_steps':[12],'native_results':nr,'unstable_envs':[]}
        entries=[('result.json','native_result',nr),('terminal.json','episode_complete',ep),('acks.json','native_ack',[ep]),('trajectory.json','trajectory',[]),('session.json','public_session',[]),('demo.json','public_demo',{})]
        self.m['artifacts']=[]
        for path,kind,data in entries:
            raw=canonical_bytes(data);(self.root/'sample'/path).write_bytes(raw)
            self.m['artifacts'].append({'path':path,'kind':kind,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'media_type':'application/json'})
        for view in ('head','left','right'):
            path=view+'.mp4';raw=b'test-fixture-not-a-real-video';(self.root/'sample'/path).write_bytes(raw)
            self.m['artifacts'].append({'path':path,'kind':'native_video','sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'media_type':'video/mp4','view':view})
        self.m['costs']['attempts']=[{'attempt_id':'test','input_tokens':None,'cached_input_tokens':None,'output_tokens':None,'model_responses':None,'paid_requests':1,'usage_known':False}]
        self.assertEqual(validate_manifest(self.m,self.root/'sample'),[])
        self.m['outcome']['control_steps']=13
        self.assertTrue(any('control' in e for e in validate_manifest(self.m,self.root/'sample')))
    def test_storage_overlay_preserves_immutable_manifest(self):
        import_bundle(self.root/'sample',self.root/'store')
        before=(self.root/'store/offline-fixture-001/manifest.json').read_bytes()
        storage={'artifacts':{self.m['artifacts'][0]['sha256']:{'provider':'tsinghua','landing_url':'https://cloud.tsinghua.edu.cn/','download_url':None,'playback_url':None,'verification':'local_sha256'}}}
        (self.root/'locations.json').write_text(json.dumps(storage))
        build_index(self.root/'store',ROOT/'registry/tasks.json',self.root/'index.json',storage_path=self.root/'locations.json')
        self.assertEqual(before,(self.root/'store/offline-fixture-001/manifest.json').read_bytes())
        self.assertEqual(json.loads((self.root/'index.json').read_text())['runs'][0]['artifacts'][0]['storage']['provider'],'tsinghua')
    def test_index_fixture_no_fake_score(self):
        import_bundle(self.root/'sample',self.root/'store')
        build_index(self.root/'store',ROOT/'registry/tasks.json',self.root/'index.json')
        d=json.loads((self.root/'index.json').read_text());self.assertIsNone(d['statistics']['groups'][0]['cumulative']['score'])
    def test_exact_official_weighting_missing_duplicate(self):
        registry=json.loads((ROOT/'registry/tasks.json').read_text());universe={r['task']:r for r in registry['tasks']};rows=[]
        for task,t in universe.items():
            m=copy.deepcopy(self.m);m['run_id']=task;m['scene'].update(t);m['status']='complete';m['outcome'].update(native_result=True,episode_complete=True,evidence_consistent=True,score=1 if t['capability']=='Open' else 0,success=t['capability']=='Open');rows.append(m)
        self.assertEqual(official_summary(rows,universe)['score'],20)
        self.assertIsNone(official_summary(rows[:-1],universe)['score'])
        self.assertIsNone(official_summary(rows+[copy.deepcopy(rows[0])],universe)['score'])
        repeat=copy.deepcopy(rows[0]);repeat['attempt']['index']=1;repeat['outcome']['score']=1
        self.assertEqual(official_summary(rows+[repeat],universe)['score'],20)
        stat=cumulative_summary(rows,universe);self.assertEqual(stat['score'],20)
        self.assertTrue(all(v['sample_variance'] is None for v in stat['tasks'].values()))
    def test_generalization_half_each(self):
        registry=json.loads((ROOT/'registry/tasks.json').read_text());universe={r['task']:r for r in registry['tasks']};rows=[]
        for task,t in universe.items():
            m=copy.deepcopy(self.m);m['run_id']=task;m['scene'].update(t);m['status']='complete';m['outcome'].update(native_result=True,episode_complete=True,evidence_consistent=True,score=float(t['capability']=='Generalization' and t['variant']=='random'),success=False);rows.append(m)
        self.assertEqual(official_summary(rows,universe)['capabilities']['Generalization']['score'],50)
        self.assertEqual(official_summary(rows,universe)['score'],10)
    def test_expired_claim_never_takeover(self):
        ledger=self.root/'claims';c=claims.acquire(ledger,'work','alice',1)
        path=claims._path(ledger,'work');d=json.loads(path.read_text());d['expires_unix']=0;path.write_text(json.dumps(d))
        with self.assertRaises(claims.ClaimError):claims.acquire(ledger,'work','bob')
        with self.assertRaises(claims.ClaimError):claims.renew(ledger,'work','alice',c['token'])
        evidence={'work_id':'work','original_session_preserved':True,'native_state_verified':True,'paid_receipts_reconciled':True,'no_unknown_delivery':True,'account_allowance_verified':True,'next_boundary':3,'reviewed_at':'2026-10-08T00:00:00Z'}
        ep=self.root/'evidence.json';ep.write_text(json.dumps(evidence));r=claims.reconcile(ledger,'work','alice',c['token'],ep)
        self.assertEqual(len(r['history']),1)
        claims.bind(ledger,'work','alice',c['token'],'run1')
        with self.assertRaises(claims.ClaimError):claims.bind(ledger,'work','alice',c['token'],'run2')
        claims.bind(ledger,'work','alice',c['token'],'run1','a'*64)
        with self.assertRaises(claims.ClaimError):claims.bind(ledger,'work','alice',c['token'],'run1','b'*64)
        with self.assertRaises(claims.ClaimError):claims.bind(ledger,'work','alice',c['token'],'run1')
        claims.complete(ledger,'work','alice',c['token'],'run1')
        with self.assertRaises(claims.ClaimError):claims.reconcile(ledger,'work','alice',c['token'],ep)
    def test_git_ledger_cas_claims_public_hash_only(self):
        import subprocess
        def git(cwd,*args):return subprocess.run(['git',*args],cwd=cwd,text=True,capture_output=True,check=True).stdout.strip()
        remote=self.root/'remote.git';git(self.root,'init','--bare',str(remote))
        seed=self.root/'seed';git(self.root,'clone',str(remote),str(seed));git(seed,'checkout','-b','work-claims')
        git(seed,'config','user.name','Test');git(seed,'config','user.email','test@example.invalid')
        (seed/'README').write_text('Offline CAS test ledger')
        git(seed,'add','README');git(seed,'commit','-m','Initialize ledger');git(seed,'push','origin','work-claims')
        token='test-private-token'
        c=claims.git_ledger(str(remote),'work-claims','acquire','scene-A','alice',token)
        self.assertTrue(c['remote_readback_verified']);self.assertNotIn('token',c)
        self.assertNotIn(token,json.dumps(c))
        with self.assertRaises(claims.ClaimError):claims.git_ledger(str(remote),'work-claims','acquire','scene-A','bob','other-token')
        state=claims.git_ledger(str(remote),'work-claims','inspect','scene-A');self.assertEqual(state['owner'],'alice')
        claims.git_ledger(str(remote),'work-claims','renew','scene-A','alice',token)
        claims.git_ledger(str(remote),'work-claims','bind','scene-A','alice',token,run_id='run-A')
        with self.assertRaises(claims.ClaimError):claims.git_ledger(str(remote),'work-claims','bind','scene-A','alice',token,run_id='different-run')
        # A contributor whose exact prebinding was merged by PR only needs read
        # permission at launch; the verified identical binding is not re-pushed.
        from unittest.mock import patch
        original_git=claims._git
        def no_write_git(cwd,*args):
            if args[0] in ('push','commit'):raise AssertionError('Identical accepted binding must be read-only')
            return original_git(cwd,*args)
        with patch.object(claims,'_git',side_effect=no_write_git):
            accepted=claims.git_ledger(str(remote),'work-claims','bind','scene-A','alice',token,run_id='run-A')
        self.assertTrue(accepted['unchanged']);self.assertTrue(accepted['remote_readback_verified'])
        claims.git_ledger(str(remote),'work-claims','complete','scene-A','alice',token,run_id='run-A')
        with self.assertRaises(claims.ClaimError):claims.git_ledger(str(remote),'work-claims','renew','scene-A','alice',token)
        # Force two clones to reach push from the same parent, proving that a
        # normal non-force push is an atomic compare-and-swap rather than a check.
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from unittest.mock import patch
        barrier=Barrier(2);original=claims._git
        def racing_git(cwd,*args):
            if args[0]=='push':barrier.wait(timeout=20)
            return original(cwd,*args)
        def contender(owner):
            try:return claims.git_ledger(str(remote),'work-claims','acquire','scene-race',owner,owner+'-private-token')['owner']
            except claims.ClaimError:return None
        with patch.object(claims,'_git',side_effect=racing_git):
            with ThreadPoolExecutor(max_workers=2) as pool:winners=list(pool.map(contender,('alice','bob')))
        self.assertEqual(len([x for x in winners if x]),1)
    def test_private_key_never_reaches_import(self):
        self.m['audit']['limitations']=['-----BEGIN OPENSSH PRIVATE KEY-----']
        (self.root/'sample/manifest.json').write_text(json.dumps(self.m))
        with self.assertRaises(ValidationError):import_bundle(self.root/'sample',self.root/'store')

if __name__=='__main__':unittest.main()
