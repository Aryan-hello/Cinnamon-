import unittest
from cinnamon_modules.brain_task_store import prepare_execution,record_execution_result,TaskStoreError
from cinnamon_modules.brain_tasks import Task,TaskStep,TaskStatus,StepStatus
class ExecutionStoreTests(unittest.TestCase):
 def setUp(self):
  self.state={"brain_tasks":{"tasks":{}}}
  self.task=Task("t1",1,2,"goal",10,100,TaskStatus.READY,(TaskStep("s1","discord.send_message",(),StepStatus.PENDING,0,"{}","key-1",""),),updated_at=10)
  from cinnamon_modules.brain_task_store import create_task
  create_task(self.state,self.task,now=10)
 def test_prepare_claims_one_step_and_persists_running_before_call(self):
  t=prepare_execution(self.state,task_id="t1",step_id="s1",guild_id=1,member_id=2,now=20)
  self.assertEqual(t.status,TaskStatus.RUNNING)
  self.assertEqual(t.steps[0].status,StepStatus.RUNNING)
  self.assertEqual(t.steps[0].attempts,1)
 def test_same_idempotency_key_cannot_claim_twice(self):
  prepare_execution(self.state,task_id="t1",step_id="s1",guild_id=1,member_id=2,now=20)
  with self.assertRaises(TaskStoreError):
   prepare_execution(self.state,task_id="t1",step_id="s1",guild_id=1,member_id=2,now=21)
 def test_record_success_completes_step_and_task(self):
  prepare_execution(self.state,task_id="t1",step_id="s1",guild_id=1,member_id=2,now=20)
  t=record_execution_result(self.state,task_id="t1",step_id="s1",guild_id=1,member_id=2,expected_version=2,success=True,summary="ok",now=21)
  self.assertEqual(t.steps[0].status,StepStatus.COMPLETED)
  self.assertEqual(t.status,TaskStatus.COMPLETED)
 def test_uncertain_result_blocks_retry(self):
  prepare_execution(self.state,task_id="t1",step_id="s1",guild_id=1,member_id=2,now=20)
  t=record_execution_result(self.state,task_id="t1",step_id="s1",guild_id=1,member_id=2,expected_version=2,success=None,summary="outcome unknown",now=21)
  self.assertEqual(t.status,TaskStatus.UNCERTAIN)
if __name__=="__main__":unittest.main()
