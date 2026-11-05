import unittest
from cinnamon_modules.brain_memory_retrieval import retrieve_memories
class PreferenceRuntimeRetrievalTests(unittest.TestCase):
 def test_only_matching_notes_for_member_are_returned(self):
  notes=[{"guild_id":1,"member_id":2,"note_id":"a","detail":"likes puzzle games","category":"games"},
         {"guild_id":1,"member_id":2,"note_id":"b","detail":"likes fantasy stories","category":"stories"},
         {"guild_id":1,"member_id":3,"note_id":"c","detail":"likes puzzle games","category":"games"}]
  result=retrieve_memories([{"id":"a","detail":"likes puzzle games"},{"id":"b","detail":"likes fantasy stories"}],guild_id=1,member_id=2,query="puzzle games")
  self.assertEqual([x["note_id"] for x in result],["a"])
 def test_opt_out_and_no_match_return_empty(self):
  notes=[{"guild_id":1,"member_id":2,"note_id":"a","detail":"likes puzzles","category":"games"}]
  self.assertEqual(retrieve_memories(notes,guild_id=1,member_id=2,query="puzzles",opted_out=True),[])
  self.assertEqual(retrieve_memories(notes,guild_id=1,member_id=2,query="astronomy"),[])
if __name__=="__main__":unittest.main()
