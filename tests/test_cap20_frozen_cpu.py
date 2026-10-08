"""Meaningful CPU checks only; no model/network/physics execution."""
import copy, importlib, json, sys, tempfile, types, unittest
from pathlib import Path
from dataclasses import dataclass
import os
if not os.environ.get('ROBODOJO_TEST_ROBOPROBE'):raise unittest.SkipTest('Set ROBODOJO_TEST_ROBOPROBE for frozen-source CPU action tests')
import numpy as np
P=Path(__file__).resolve().parents[1]/'scripts/runtime'
sys.path.insert(0,str(P))
ns=types.ModuleType('XPolicyLab');ns.__path__=[os.environ['ROBODOJO_TEST_ROBOPROBE']];sys.modules['XPolicyLab']=ns
from policy.cap20_policy import make_cap20_policy
from XPolicyLab.policy.RoboDojo_Agent_L3_Inspect.policy import MotionOutcome
from XPolicyLab.policy.RoboDojo_Agent_L3_Inspect.types import Action,ActionChunk,Observation
from XPolicyLab.policy.RoboDojo_Agent_L3_Inspect_EEF.policy import EefAgentPolicy

def chunk(n,release_at=50):
 return ActionChunk(actions=[Action(data={'left_arm_joint_state':np.full(6,i/10), 'right_arm_joint_state':np.full(6,-i/20),'left_ee_joint_state':np.array([0. if i<release_at else 1.]),'right_ee_joint_state':np.array([1.])},meta={'chunk_final':True} if i==n-1 else {}) for i in range(n)],control_hz=25,meta={'trace':{'tool':'move_eef','planned_waypoints':n,'gripper_waypoints':6}})
class Fake:
 def __init__(self,c):self.original=MotionOutcome(c,'original accepted text');self._gripper_goals={'left':0.,'right':1.};self._last_targets={'right':'previous'};self.plans=0;self.confirmed=[]
 def _handle_motion(self,name,args,obs):
  self.plans+=1;self._gripper_goals={'left':1.,'right':1.};self._last_targets={'left':'original target'};return self.original
 def confirm_executed(self,n):self.confirmed.append(n)
 def _observation_message(self,observation,**kw):
  old=self._last_targets;self._last_targets={};return {'role':'user','content':[{'type':'text','text':'MEASURED actual pose; Arrival check for '+str(old)}]}
 def audit_config(self):return {'original':1}
class CapTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory()
 def tearDown(self):self.tmp.cleanup()
 def policy(self,c):
  p=make_cap20_policy(Fake)(c);p.configure_cap20(self.tmp.name);return p
 def call(self,p):return p._handle_motion('move_eef',{},Observation({}, {},step=3))
 def test_short_identity_and_feedback(self):
  p=self.policy(chunk(19));o=self.call(p);self.assertIs(o,p.original);self.assertIs(o.chunk,p.original.chunk);self.assertEqual(o.tool_result,'original accepted text');p.confirm_executed(19);self.assertNotIn('cap',p._observation_message(None)['content'][0]['text']);self.assertEqual(p._gripper_goals,{'left':1.,'right':1.})
 def test_exact_20_identity(self):
  p=self.policy(chunk(20));self.assertIs(self.call(p),p.original)
 def test_prefix_exact_no_resample_no_plan_repeat(self):
  p=self.policy(chunk(66));original=p.original.chunk;o=self.call(p);self.assertEqual(len(o.chunk.actions),20);self.assertEqual(p.plans,1)
  for a,b in zip(o.chunk.actions,original.actions):self.assertIs(a,b)
  self.assertEqual(len(original.actions),66);self.assertNotIn('cap20',original.meta['trace']);self.assertEqual(o.chunk.meta['trace']['planned_waypoints'],66)
 def test_no_angle_refusal(self):
  c=chunk(66);c.actions[0].data['left_arm_joint_state'][:]=100.;p=self.policy(c);self.assertIsNotNone(self.call(p).chunk)
 def test_gripper_not_executed_does_not_leak(self):
  p=self.policy(chunk(66,50));self.call(p);p.confirm_executed(20);self.assertEqual(p._gripper_goals,{'left':0.,'right':1.});self.assertEqual(p._last_targets,{'left':'original target'})
 def test_gripper_executed_is_latched(self):
  p=self.policy(chunk(66,10));self.call(p);p.confirm_executed(20);self.assertEqual(p._gripper_goals['left'],1.)
 def test_native_terminal_before_20(self):
  p=self.policy(chunk(66,30));o=self.call(p);executed=[]
  # Same native break-before-next-control semantics; physics is a CPU stub.
  for a in o.chunk.actions:
   executed.append(a)
   if len(executed)==7:break
  p.confirm_executed(len(executed));audit=json.loads(next(Path(self.tmp.name).glob('*.json')).read_text());self.assertEqual(audit['executed_controls'],7);self.assertEqual(audit['unexecuted_controls'],59);self.assertTrue(audit['native_ended_before_prefix_complete']);self.assertEqual(p._gripper_goals['left'],0.)
 def test_zero_executed_restores_latch(self):
  p=self.policy(chunk(66));self.call(p);p.confirm_executed(0);self.assertEqual(p._gripper_goals,{'left':0.,'right':1.})
 def test_actual_feedback_once(self):
  p=self.policy(chunk(66));self.call(p);p.confirm_executed(20);t=p._observation_message(None)['content'][0]['text'];self.assertIn('executed 20 of 66',t);self.assertIn('46 unexecuted',t);self.assertIn('MEASURED actual pose',t);self.assertIn('original target',t);self.assertNotIn('executed 20',p._observation_message(None)['content'][0]['text'])
 def test_suffix_not_retained(self):
  p=self.policy(chunk(66));self.call(p);p.confirm_executed(20);self.assertIsNone(p._cap20_pending);self.assertNotIn('actions',p._cap20_feedback)
 def test_planner_failure_unchanged(self):
  p=self.policy(chunk(1));p.original=MotionOutcome(None,'original Fail',False);self.assertIs(self.call(p),p.original);self.assertEqual(list(Path(self.tmp.name).glob('*.json')),[])
 def test_link6_lazy_not_consumed(self):
  class Lazy:
   def __len__(self):return 5
   def __getitem__(self,i):raise AssertionError('must not precompute IK')
  p=self.policy(ActionChunk(Lazy()));self.assertIs(p._handle_motion('move_link6',{},None),p.original);self.assertEqual(list(Path(self.tmp.name).glob('*.json')),[])
 def test_no_double_plan_before_ack(self):
  p=self.policy(chunk(66));self.call(p)
  with self.assertRaises(RuntimeError):self.call(p)
 def test_invalid_ack_count_rejected(self):
  p=self.policy(chunk(66));self.call(p)
  with self.assertRaises(RuntimeError):p.confirm_executed(41)
 def test_config_is_explicit(self):
  p=self.policy(chunk(1));c=p.audit_config();self.assertIsNone(c['action_cap20']['angle_threshold']);self.assertEqual(c['original'],1)
 def test_original_eef_planner_and_retime_prefix(self):
  # Invoke the actual original _handle_motion, with a deterministic numerical
  # planner stub. All native retiming, jaw sequencing and target bookkeeping run.
  def make(cls):
   p=cls.__new__(cls);p._gripper_goals={'left':0.,'right':1.};p._last_targets={}
   p._max_duration_s=10.;p.action_spec=types.SimpleNamespace(control_hz=25);p._negate_xyz=False
   p._jitter_sphere_per_move=False;p._jitter_sphere_r=0.;p._jitter_sphere_mean_r=0.
   p._jitter_dx=p._jitter_dy=p._jitter_dz=p._jitter_sphere_dx=p._jitter_sphere_dy=p._jitter_sphere_dz=0.
   p._arm_step_limits={a:np.full(6,.05) for a in ('left','right')};p._gripper_step_limits={a:.18 for a in ('left','right')}
   p._planner=lambda **kw:{'status':'Success','position':np.array([[0]*6,[3.0,0,0,0,0,0]],dtype=np.float32)}
   return p
  state={a+'_arm_joint_state':np.zeros(6) for a in ('left','right')};state.update({a+'_ee_joint_state':np.array([0. if a=='left' else 1.]) for a in ('left','right')});state.update({a+'_ee_pose':np.array([0,0,1,1,0,0,0],float) for a in ('left','right')})
  obs=Observation({},state,step=0);args={'targets':{'left_z':1.0,'left_gripper':1.},'note':'test'}
  original=make(EefAgentPolicy);limited=make(make_cap20_policy(EefAgentPolicy));limited.configure_cap20(self.tmp.name)
  a=original._handle_motion('move_eef',args,obs);b=limited._handle_motion('move_eef',args,obs)
  self.assertEqual(len(a.chunk.actions),66);self.assertEqual(len(b.chunk.actions),20)
  for x,y in zip(a.chunk.actions,b.chunk.actions):
   for key in x.data:np.testing.assert_array_equal(x.data[key],y.data[key])
  limited.confirm_executed(20);self.assertEqual(limited._gripper_goals['left'],0.)
  self.assertIn('left',limited._last_targets)
  residual=limited._arrival_text(obs);self.assertIn('Arrival check',residual)
if __name__=='__main__':unittest.main()
