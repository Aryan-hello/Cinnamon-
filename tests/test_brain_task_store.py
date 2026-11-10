import unittest
from cinnamon_modules.brain_tasks import Task,TaskStep,TaskStatus,StepStatus,validate_task
from cinnamon_modules.brain_task_store import create_task, get_task, update_task, cancel_task, prune_tasks, TaskStoreError

class BrainTaskStoreTests(unittest.TestCase):
    def task(self, task_id="t1", guild=10, member=20, now=100):
        return Task(task_id,guild,member,"organize",now,now+3600,TaskStatus.DRAFT,(TaskStep("s1","help.lookup"),))
    def test_create_and_get_are_scope_limited(self):
        state={}
        task=self.task()
        create_task(state,task,now=100)
        self.assertEqual(get_task(state,"t1",guild_id=10,member_id=20),task)
        self.assertIsNone(get_task(state,"t1",guild_id=10,member_id=21))
        self.assertIsNone(get_task(state,"t1",guild_id=11,member_id=20))
    def test_duplicate_create_is_idempotent_only_for_same_task(self):
        state={}; task=self.task()
        self.assertEqual(create_task(state,task,now=100),task)
        self.assertEqual(create_task(state,task,now=100),task)
        with self.assertRaises(TaskStoreError): create_task(state,self.task(guild=99),now=100)
    def test_update_requires_matching_scope_and_revision(self):
        state={}; task=self.task(); create_task(state,task,now=100)
        changed=update_task(state,task_id="t1",guild_id=10,member_id=20,expected_version=1,
            transform=lambda x: x,now=101)
        self.assertEqual(changed.plan_version,2)
        with self.assertRaises(TaskStoreError):
            update_task(state,task_id="t1",guild_id=10,member_id=20,expected_version=1,
                transform=lambda x:x,now=102)
    def test_cancel_only_owned_task(self):
        state={}; create_task(state,self.task(),now=100)
        with self.assertRaises(TaskStoreError): cancel_task(state,"t1",guild_id=10,member_id=21,now=101)
        cancelled=cancel_task(state,"t1",guild_id=10,member_id=20,now=101)
        self.assertEqual(cancelled.status,TaskStatus.CANCELLED)
    def test_expired_tasks_prune_bounded(self):
        state={}; create_task(state,self.task(),now=100)
        self.assertEqual(prune_tasks(state,now=3700),["t1"])
        self.assertIsNone(get_task(state,"t1",guild_id=10,member_id=20))
    def test_restart_recovery_marks_running_step_uncertain(self):
        from cinnamon_modules.brain_task_store import recover_interrupted_tasks
        from dataclasses import replace
        state={}; task=self.task()
        task=replace(task,status=TaskStatus.RUNNING,steps=(replace(task.steps[0],status=StepStatus.RUNNING,attempts=1),))
        create_task(state,task,now=100)
        recovered=recover_interrupted_tasks(state,now=200)
        self.assertEqual(recovered,["t1"])
        saved=get_task(state,"t1",guild_id=10,member_id=20)
        self.assertEqual(saved.status,TaskStatus.UNCERTAIN)
        self.assertEqual(saved.steps[0].status,StepStatus.UNCERTAIN)
        self.assertIn("restart",saved.steps[0].outcome_summary.lower())

    def test_corrupt_container_rejected_not_reset(self):
        with self.assertRaises(TaskStoreError): get_task({"brain_tasks":"bad"},"t1",guild_id=10,member_id=20)

if __name__=="__main__": unittest.main()
