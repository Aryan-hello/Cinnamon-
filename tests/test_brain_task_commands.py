import unittest
from cinnamon_modules.brain_tasks import Task,TaskStatus
from cinnamon_modules.brain_task_store import create_task,get_task
class TaskCommandAdapterTests(unittest.TestCase):
 def test_task_record_roundtrip_and_owner_scope(self):
  state={};task=Task("a1",1,2,"remember to review",100,1000,TaskStatus.DRAFT,())
  create_task(state,task,now=100)
  self.assertEqual(get_task(state,"a1",guild_id=1,member_id=2).goal,"remember to review")
  self.assertIsNone(get_task(state,"a1",guild_id=1,member_id=3))
if __name__=="__main__":unittest.main()
