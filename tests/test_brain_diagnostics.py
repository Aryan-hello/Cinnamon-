import unittest
from cinnamon_modules.brain_diagnostics import BrainDiagnostics,record_result,consistency_score

class BrainDiagnosticsTests(unittest.TestCase):
 def test_records_bounded_aggregate_metrics_not_text(self):
  d=BrainDiagnostics()
  record_result(d,"success",latency_ms=20)
  record_result(d,"failure",latency_ms=40)
  self.assertEqual(d.total,2);self.assertEqual(d.failures,1)
  self.assertEqual(d.latency_total_ms,60)
  self.assertFalse(hasattr(d,"messages"))
 def test_unknown_outcome_is_not_silently_success(self):
  d=BrainDiagnostics()
  with self.assertRaises(ValueError):record_result(d,"maybe",latency_ms=1)
 def test_consistency_score_is_deterministic_and_bounded(self):
  self.assertEqual(consistency_score(0,0),100)
  self.assertEqual(consistency_score(10,10),0)
  self.assertEqual(consistency_score(3,10),70)
  self.assertEqual(consistency_score(-1,2),0)
if __name__=="__main__":unittest.main()
