"""Pure fail-closed gate before a trusted adapter executes one task step."""
from enum import Enum
from cinnamon_modules.brain_tasks import Task,TaskStatus,StepStatus,dependencies_satisfied

class ExecutionGate(str,Enum):
 ALLOW="allow"; SCOPE="scope_mismatch"; STORAGE="storage_unavailable"
 DISABLED="feature_disabled"; PERMISSION="permission_revoked"; SERIOUS="serious_context"
 EXPIRED="expired"; STATUS="task_not_ready"; STEP="step_not_pending"; DEPENDENCY="dependency_pending"

def evaluate_step(task:Task,step_id:str,*,now:float,requester_id:int,guild_id:int,
 storage_ready:bool,feature_enabled:bool,permission_ok:bool,serious:bool)->ExecutionGate:
 """Return a single gate result. ALLOW is not an execution token or permission grant."""
 if type(task) is not Task:return ExecutionGate.STATUS
 if type(guild_id) is not int or guild_id!=task.guild_id or type(requester_id) is not int or requester_id!=task.member_id:
  return ExecutionGate.SCOPE
 if not storage_ready:return ExecutionGate.STORAGE
 if not feature_enabled:return ExecutionGate.DISABLED
 if not permission_ok:return ExecutionGate.PERMISSION
 if serious:return ExecutionGate.SERIOUS
 if type(now) not in (int,float) or now>=task.expires_at or (task.approval_expires_at and now>=task.approval_expires_at):
  return ExecutionGate.EXPIRED
 if task.status!=TaskStatus.READY:return ExecutionGate.STATUS
 step=next((s for s in task.steps if s.step_id==step_id),None)
 if step is None or step.status!=StepStatus.PENDING:return ExecutionGate.STEP
 if not dependencies_satisfied(step,task.steps):return ExecutionGate.DEPENDENCY
 return ExecutionGate.ALLOW
