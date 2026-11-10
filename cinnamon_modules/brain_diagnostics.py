"""Aggregate Brain diagnostics without storing conversation text."""
from dataclasses import dataclass
@dataclass
class BrainDiagnostics:
 total:int=0
 successes:int=0
 failures:int=0
 uncertain:int=0
 latency_total_ms:int=0
 latency_samples:int=0
 def snapshot(self):
  return {"total":self.total,"successes":self.successes,"failures":self.failures,"uncertain":self.uncertain,"latency_total_ms":self.latency_total_ms,"latency_samples":self.latency_samples}
def record_result(metrics,outcome,*,latency_ms):
 if outcome not in {"success","failure","uncertain"}:raise ValueError("Unknown outcome")
 if type(latency_ms) is not int or not 0<=latency_ms<=600000:raise ValueError("Invalid latency")
 metrics.total+=1
 if outcome=="success":metrics.successes+=1
 elif outcome=="failure":metrics.failures+=1
 else:metrics.uncertain+=1
 metrics.latency_total_ms+=latency_ms;metrics.latency_samples+=1
 return metrics.snapshot()
def consistency_score(conflicts,checks):
 if type(conflicts) is not int or type(checks) is not int or conflicts<0 or checks<0:return 0
 if checks==0:return 100
 return max(0,min(100,round(100*(checks-conflicts)/checks)))
