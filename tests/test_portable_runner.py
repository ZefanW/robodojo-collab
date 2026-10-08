import hashlib,importlib.util,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from robodojo_collab import claims
from robodojo_collab.runner import BudgetGuard,AssignmentGuard,collect,digest,reconcile,work_id,validate_package
from robodojo_collab.transport import atomic,mailbox_operation

class PortableTests(unittest.TestCase):
 def test_explicit_reserve_and_unknown_usage(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'passive.json';identity='test-local-only';cfg={'reserve_percent':20,'allow_existing_credits':False,'snapshot_file':str(p),'account_identity_sha256':hashlib.sha256(identity.encode()).hexdigest(),'max_age_seconds':300}
   guard=BudgetGuard(cfg)
   snapshot={'accountId':identity,'rateLimits':{'primary':{'usedPercent':79},'secondary':{'usedPercent':50}}}
   guard.observe(snapshot,time.time(),'test');guard.check()
   for changed in [dict(snapshot,accountId='different'),dict(snapshot,rateLimits={}),dict(snapshot,rateLimits={'primary':{'usedPercent':80}})]:
    atomic(p,{'observed_unix':time.time(),'source':'native-passive-notification','snapshot':changed})
    with self.assertRaises(RuntimeError):guard.check()
   atomic(p,{'observed_unix':time.time()-301,'source':'native-passive-notification','snapshot':snapshot})
   with self.assertRaises(RuntimeError):guard.check()
   with self.assertRaises(ValueError):BudgetGuard(dict(cfg,reserve_percent=None))

 def test_immutable_delivery_and_collect(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)/'sim';run=root/'r';f=run/'mailbox/0000';f.mkdir(parents=True)
   payload={'run_id':'r','index':0};raw=json.dumps(payload,separators=(',',':')).encode();(f/'request.json').write_bytes(raw);sha=hashlib.sha256(raw).hexdigest()
   atomic(f.parent/'pending.json',{'run_id':'r','index':0,'request_sha256':sha})
   receipt={'request_sha256':sha,'response':{'model':'synthetic'}}
   self.assertEqual(mailbox_operation(root,'next','r')['payload'],payload)
   packet={'index':0,'receipt':receipt}
   self.assertFalse(mailbox_operation(root,'deliver','r',packet)['reused']);self.assertTrue(mailbox_operation(root,'deliver','r',packet)['reused'])
   with self.assertRaises(ValueError):mailbox_operation(root,'deliver','r',dict(packet,receipt=dict(receipt,other=True)))
   native=Path(td)/'native';(native/'audit').mkdir(parents=True)
   atomic(native/'_result.json',{'details':{}});(native/'audit/events.jsonl').write_text(json.dumps({'kind':'episode_complete'})+'\n')
   atomic(run/'native.json',{'native_dir':str(native)})
   manifest=mailbox_operation(root,'archive-manifest','r');self.assertTrue(manifest['files'])
   with self.assertRaises(ValueError):mailbox_operation(root,'next','../bad')

 def test_paid_unknown_never_replayed(self):
  with tempfile.TemporaryDirectory() as td:
   local=Path(td);folder=local/'calls/0000';folder.mkdir(parents=True);atomic(folder/'paid-start.json',{})
   with self.assertRaisesRegex(RuntimeError,'Unresolved paid'):reconcile({'transport':{'mode':'local','root':td}},{'run_id':'r'},local)

 def test_shared_claim_bound_to_one_run(self):
  with tempfile.TemporaryDirectory() as td:
   p={'run_id':'r','algorithm':{'algorithm_id':'a','version':'1'},'scene':{'task':'t','official_seed':0,'layout_ordinal':1,'asset_sha256':'0'*64},'attempt':{'index':0,'contributor_id':'person'}};p['work_id']=work_id(p)
   receipt=claims.acquire(Path(td)/'ledger',p['work_id'],'person');token=Path(td)/'token';token.write_text(receipt['token'])
   cfg={'mode':'shared','ledger':str(Path(td)/'ledger'),'token_file':str(token)}
   guard=AssignmentGuard(cfg,p);guard.bind();self.assertEqual(guard.check()['run_id'],'r')
   other=AssignmentGuard(cfg,dict(p,run_id='other'))
   with self.assertRaises(claims.ClaimError):other.bind()

 def test_true_scene_fields_not_seed_alias(self):
  p={'run_id':'r','algorithm':{'algorithm_id':'astra-l3-persistent-cap20','model':'gpt-6-astra','reasoning_effort':'medium','codex_client_version':'0.153.4'},'scene':{'task':'t','official_seed':3,'layout_ordinal':0,'asset_sha256':'0'*64},'protocol':{'action_limit':20,'max_model_decisions':100}}
  with self.assertRaises(ValueError):validate_package(p)

if __name__=='__main__':unittest.main()
