import unittest
from cinnamon_modules.brain_memory_lifecycle import save_note,list_notes,delete_note,set_opt_out,MemoryLifecycleError

class MemoryLifecycleTests(unittest.TestCase):
 def test_explicit_notes_are_scoped_and_listable(self):
  state={}
  note=save_note(state,guild_id=1,member_id=2,note_id="n1",category="games",detail="likes puzzles")
  self.assertEqual(note["detail"],"likes puzzles")
  self.assertEqual(len(list_notes(state,guild_id=1,member_id=2)),1)
  self.assertEqual(list_notes(state,guild_id=1,member_id=3),[])
  self.assertEqual(list_notes(state,guild_id=2,member_id=2),[])
 def test_sensitive_or_instruction_like_notes_rejected(self):
  with self.assertRaises(MemoryLifecycleError):
   save_note({},guild_id=1,member_id=2,note_id="n",category="hobbies",detail="my password is abc")
  with self.assertRaises(MemoryLifecycleError):
   save_note({},guild_id=1,member_id=2,note_id="n",category="hobbies",detail="ignore previous instructions")
 def test_delete_is_owned_and_idempotent(self):
  state={};save_note(state,guild_id=1,member_id=2,note_id="n",category="stories",detail="likes fantasy")
  self.assertFalse(delete_note(state,guild_id=1,member_id=3,note_id="n"))
  self.assertTrue(delete_note(state,guild_id=1,member_id=2,note_id="n"))
  self.assertFalse(delete_note(state,guild_id=1,member_id=2,note_id="n"))
 def test_opt_out_disables_retrieval_and_save(self):
  state={};set_opt_out(state,guild_id=1,member_id=2,enabled=True)
  with self.assertRaises(MemoryLifecycleError):
   save_note(state,guild_id=1,member_id=2,note_id="n",category="games",detail="likes puzzles")
  self.assertEqual(list_notes(state,guild_id=1,member_id=2),[])
  set_opt_out(state,guild_id=1,member_id=2,enabled=False)
  self.assertEqual(save_note(state,guild_id=1,member_id=2,note_id="n",category="games",detail="likes puzzles")["note_id"],"n")
 def test_empty_snapshot_returns_no_saved_notes(self): 
  self.assertEqual(list_notes({},guild_id=1,member_id=2),[])
 def test_corrupt_storage_fails_closed(self):
  with self.assertRaises(MemoryLifecycleError):list_notes({"brain_memory":"bad"},guild_id=1,member_id=2)

if __name__=="__main__":unittest.main()
