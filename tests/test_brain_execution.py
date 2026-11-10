import unittest
from cinnamon_modules.brain_tasks import Task,TaskStep,TaskStatus,StepStatus
from cinnamon_modules.brain_execution import evaluate_step,ExecutionGate

class BrainExecutionGateTests(unittest.TestCase):
 def task(self,status=TaskStatus.READY, approval=200):
  return Task("t1",10,20,"do thing",100,500,status,
   (TaskStep("s1","safe.read"),TaskStep("s2","safe.write",("s1",))),
   updated_at=100,approval_expires_at=approval)
 def test_only_one_approved_ready_step_can_run(self):
  t=self.task()
  gate=evaluate_step(t,"s1",now=150,requester_id=20,guild_id=10,
   storage_ready=True,feature_enabled=True,permission_ok=True,serious=False)
  self.assertEqual(gate,ExecutionGate.ALLOW)
 def test_wrong_scope_and_requester_block(self):
  t=self.task()
  self.assertEqual(evaluate_step(t,"s1",now=150,requester_id=21,guild_id=10,
   storage_ready=True,feature_enabled=True,permission_ok=True,serious=False),ExecutionGate.SCOPE)
  self.assertEqual(evaluate_step(t,"s1",now=150,requester_id=20,guild_id=11,
   storage_ready=True,feature_enabled=True,permission_ok=True,serious=False),ExecutionGate.SCOPE)
 def test_stale_approval_or_expiry_blocks(self):
  t=self.task(approval=140)
  self.assertEqual(evaluate_step(t,"s1",now=150,requester_id=20,guild_id=10,
   storage_ready=True,feature_enabled=True,permission_ok=True,serious=False),ExecutionGate.EXPIRED)
  self.assertEqual(evaluate_step(self.task(),"s1",now=600,requester_id=20,guild_id=10,
   storage_ready=True,feature_enabled=True,permission_ok=True,serious=False),ExecutionGate.EXPIRED)
 def test_storage_permission_serious_and_feature_block(self):
  t=self.task()
  common=dict(now=150,requester_id=20,guild_id=10,feature_enabled=True,permission_ok=True,serious=False)
  self.assertEqual(evaluate_step(t,"s1",storage_ready=False,**common),ExecutionGate.STORAGE)
  self.assertEqual(evaluate_step(t,"s1",storage_ready=True,feature_enabled=False,permission_ok=True,serious=False,now=150,requester_id=20,guild_id=10),ExecutionGate.DISABLED)
  self.assertEqual(evaluate_step(t,"s1",storage_ready=True,feature_enabled=True,permission_ok=False,serious=False,now=150,requester_id=20,guild_id=10),ExecutionGate.PERMISSION)
  self.assertEqual(evaluate_step(t,"s1",storage_ready=True,feature_enabled=True,permission_ok=True,serious=True,now=150,requester_id=20,guild_id=10),ExecutionGate.SERIOUS)
 def test_dependency_and_task_status_gate(self):
  t=self.task()
  self.assertEqual(evaluate_step(t,"s2",now=150,requester_id=20,guild_id=10,
   storage_ready=True,feature_enabled=True,permission_ok=True,serious=False),ExecutionGate.DEPENDENCY)
  running=self.task(TaskStatus.RUNNING)
  self.assertEqual(evaluate_step(running,"s1",now=150,requester_id=20,guild_id=10,
   storage_ready=True,feature_enabled=True,permission_ok=True,serious=False),ExecutionGate.STATUS)

if __name__=="__main__":unittest.main()
