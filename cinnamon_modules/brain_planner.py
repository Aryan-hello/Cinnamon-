"""Untrusted plan parsing: validated proposals only, never execution authority."""
from __future__ import annotations
from dataclasses import dataclass
import json
from typing import Mapping
from cinnamon_modules.brain_tasks import TaskStep, TaskValidationError, validate_task, Task, TaskStatus

MAX_PLAN_CHARS=10_000
MAX_ARGUMENTS=2_000
class PlanValidationError(ValueError): pass
@dataclass(frozen=True)
class PlanProposal:
 goal: str
 steps: tuple[TaskStep,...]

def parse_plan_proposal(payload: str, capability_registry: Mapping[str,object]) -> PlanProposal:
 if not isinstance(payload,str) or len(payload)>MAX_PLAN_CHARS: raise PlanValidationError("Plan payload exceeds limit")
 try: obj=json.loads(payload)
 except (ValueError,TypeError): raise PlanValidationError("Plan is not valid JSON") from None
 if not isinstance(obj,dict) or set(obj)!={"goal","steps"}: raise PlanValidationError("Plan must contain only goal and steps")
 goal=obj["goal"]
 if not isinstance(goal,str) or not goal.strip() or len(goal)>240: raise PlanValidationError("Invalid plan goal")
 raw=obj["steps"]
 if not isinstance(raw,list) or len(raw)>8: raise PlanValidationError("Plan must have at most 8 steps")
 steps=[]; ids=set()
 for item in raw:
  if not isinstance(item,dict) or set(item)!={"step_id","capability_id","arguments","dependencies"}: raise PlanValidationError("Invalid step shape")
  sid,cap,args,deps=item["step_id"],item["capability_id"],item["arguments"],item["dependencies"]
  if not isinstance(sid,str) or not sid or sid in ids: raise PlanValidationError("Duplicate or invalid step ID")
  ids.add(sid)
  if not isinstance(cap,str) or cap not in capability_registry: raise PlanValidationError("Unknown capability")
  if not isinstance(args,dict) or not isinstance(deps,list) or any(not isinstance(d,str) for d in deps): raise PlanValidationError("Invalid arguments or dependencies")
  schema=capability_registry[cap]
  if isinstance(schema,dict) and "arguments" in schema:
   arg_schema=schema["arguments"]
   if isinstance(arg_schema,dict) and set(args)!=set(arg_schema): raise PlanValidationError("Arguments do not match capability schema")
  encoded=json.dumps(args,separators=(",",":"),allow_nan=False)
  if len(encoded)>MAX_ARGUMENTS: raise PlanValidationError("Arguments exceed limit")
  steps.append(TaskStep(sid,cap,tuple(deps),arguments_json=encoded))
 try:
  validate_task(Task("proposal",1,1,goal,1,2,TaskStatus.DRAFT,tuple(steps)))
 except TaskValidationError as exc: raise PlanValidationError(str(exc)) from None
 return PlanProposal(goal,tuple(steps))
