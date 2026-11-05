import json, unittest
from cinnamon_modules.brain_planner import PlanValidationError, parse_plan_proposal
class PlannerTests(unittest.TestCase):
 def test_accepts_only_known_capability_and_closed_shape(self):
  reg={"channel.read":{"arguments":{"channel_id":"int"}}}
  raw=json.dumps({"steps":[{"step_id":"s1","capability_id":"channel.read","arguments":{"channel_id":4},"dependencies":[]}]})
  plan=parse_plan_proposal(raw,reg)
  self.assertEqual(plan.steps[0].capability_id,"channel.read")
 def test_rejects_unknown_capability_and_extra_fields(self):
  for obj in ({"steps":[{"step_id":"s","capability_id":"evil","arguments":{},"dependencies":[]}]},
              {"steps":[],"admin":True}):
   with self.assertRaises(PlanValidationError):parse_plan_proposal(json.dumps(obj),{})
 def test_rejects_malformed_oversized_and_dependency_cycle(self):
  for raw in ("not json","x"*12000,json.dumps({"steps":[{"step_id":"a","capability_id":"x","arguments":{},"dependencies":["b"]},{"step_id":"b","capability_id":"x","arguments":{},"dependencies":["a"]}]}):
   with self.assertRaises(PlanValidationError):parse_plan_proposal(raw,{"x":{}})
if __name__=="__main__":unittest.main()
