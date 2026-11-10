import unittest
from cinnamon_modules.brain_tasks import (
    Task, TaskStep, TaskStatus, StepStatus, TaskValidationError,
    validate_task, transition_task, can_transition,
)

class BrainTaskTests(unittest.TestCase):
    def make_task(self):
        return Task("t1", 10, 20, "organize channel", 100, 200,
                    TaskStatus.DRAFT, (TaskStep("s1", "channel.read"),))

    def test_valid_task_and_step_caps(self):
        self.assertEqual(validate_task(self.make_task()).task_id, "t1")
        task=self.make_task()
        steps=tuple(TaskStep(f"s{i}", "channel.read") for i in range(9))
        with self.assertRaises(TaskValidationError):
            validate_task(Task(task.task_id,task.guild_id,task.member_id,task.goal,
                task.created_at,task.expires_at,task.status,steps))

    def test_scope_ids_and_timestamps_are_strict(self):
        task=self.make_task()
        with self.assertRaises(TaskValidationError):
            validate_task(Task("t",True,20,"goal",100,200,TaskStatus.DRAFT,()))
        with self.assertRaises(TaskValidationError):
            validate_task(Task("t",10,20,"goal",200,100,TaskStatus.DRAFT,()))

    def test_dependencies_must_exist_and_be_acyclic(self):
        task=self.make_task()
        cyclic=(TaskStep("a","channel.read",("b",)),TaskStep("b","channel.read",("a",)))
        missing=(TaskStep("a","channel.read",("missing",)),)
        for steps in (cyclic,missing):
            with self.assertRaises(TaskValidationError):
                validate_task(Task(task.task_id,10,20,"goal",100,200,TaskStatus.DRAFT,steps))

    def test_transition_policy_rejects_terminal_reopen(self):
        self.assertTrue(can_transition(TaskStatus.DRAFT,TaskStatus.READY))
        self.assertFalse(can_transition(TaskStatus.COMPLETED,TaskStatus.READY))
        with self.assertRaises(TaskValidationError):
            transition_task(self.make_task(),TaskStatus.COMPLETED)

    def test_cancel_expire_uncertain_are_terminal(self):
        for status in (TaskStatus.CANCELLED,TaskStatus.EXPIRED,TaskStatus.UNCERTAIN):
            self.assertFalse(can_transition(status,TaskStatus.READY))

if __name__=="__main__": unittest.main()
