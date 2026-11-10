"""Pure, bounded task records and transition rules for Cinnamon Brain v5."""
from __future__ import annotations
from dataclasses import dataclass, replace
from enum import Enum
import math
import re
from typing import Iterable

MAX_STEPS = 8
MAX_GOAL_CHARS = 240
MAX_CAPABILITY_CHARS = 80
MAX_ARGS_CHARS = 2_000
MAX_DEPENDENCIES = 8

class TaskValidationError(ValueError):
    """Task data violates the closed schema or policy."""

class TaskStatus(str, Enum):
    DRAFT="draft"; AWAITING_APPROVAL="awaiting_approval"; READY="ready"
    RUNNING="running"; BLOCKED="blocked"; COMPLETED="completed"
    FAILED="failed"; CANCELLED="cancelled"; EXPIRED="expired"; UNCERTAIN="uncertain"

class StepStatus(str, Enum):
    PENDING="pending"; RUNNING="running"; COMPLETED="completed"
    FAILED="failed"; BLOCKED="blocked"; UNCERTAIN="uncertain"; SKIPPED="skipped"

@dataclass(frozen=True)
class TaskStep:
    step_id: str
    capability_id: str
    dependencies: tuple[str,...]=()
    status: StepStatus=StepStatus.PENDING
    attempts: int=0
    arguments_json: str="{}"
    idempotency_key: str=""
    outcome_summary: str=""

@dataclass(frozen=True)
class Task:
    task_id: str
    guild_id: int
    member_id: int
    goal: str
    created_at: float
    expires_at: float
    status: TaskStatus
    steps: tuple[TaskStep,...]
    updated_at: float=0.0
    plan_version: int=1
    approval_expires_at: float=0.0
    receipt_ids: tuple[str,...]=()

_ID=re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CAP=re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
_TERMINAL={TaskStatus.COMPLETED,TaskStatus.FAILED,TaskStatus.CANCELLED,TaskStatus.EXPIRED,TaskStatus.UNCERTAIN}
_ALLOWED={
 TaskStatus.DRAFT:{TaskStatus.AWAITING_APPROVAL,TaskStatus.READY,TaskStatus.CANCELLED,TaskStatus.EXPIRED,TaskStatus.BLOCKED},
 TaskStatus.AWAITING_APPROVAL:{TaskStatus.READY,TaskStatus.CANCELLED,TaskStatus.EXPIRED,TaskStatus.BLOCKED},
 TaskStatus.READY:{TaskStatus.RUNNING,TaskStatus.CANCELLED,TaskStatus.EXPIRED,TaskStatus.BLOCKED},
 TaskStatus.RUNNING:{TaskStatus.READY,TaskStatus.BLOCKED,TaskStatus.COMPLETED,TaskStatus.FAILED,TaskStatus.CANCELLED,TaskStatus.EXPIRED,TaskStatus.UNCERTAIN},
 TaskStatus.BLOCKED:{TaskStatus.READY,TaskStatus.CANCELLED,TaskStatus.EXPIRED,TaskStatus.FAILED},
}
def _enum(value, cls, label):
 try: return cls(value)
 except (ValueError,TypeError): raise TaskValidationError(f"Invalid {label}") from None

def validate_task(task: Task) -> Task:
 if type(task) is not Task: raise TaskValidationError("Task must use the typed schema")
 if not isinstance(task.task_id,str) or not _ID.fullmatch(task.task_id): raise TaskValidationError("Invalid task ID")
 if type(task.guild_id) is not int or task.guild_id<=0 or type(task.member_id) is not int or task.member_id<=0: raise TaskValidationError("Invalid task scope")
 if not isinstance(task.goal,str) or not task.goal.strip() or len(task.goal)>MAX_GOAL_CHARS: raise TaskValidationError("Invalid task goal")
 for n in (task.created_at,task.expires_at,task.updated_at,task.approval_expires_at):
  if type(n) not in (int,float) or not math.isfinite(n): raise TaskValidationError("Invalid task timestamp")
 if task.expires_at<=task.created_at: raise TaskValidationError("Task expiry must follow creation")
 if type(task.plan_version) is not int or task.plan_version<1: raise TaskValidationError("Invalid plan version")
 status=_enum(task.status,TaskStatus,"task status")
 if not isinstance(task.steps,tuple) or len(task.steps)>MAX_STEPS: raise TaskValidationError("Task exceeds step cap")
 ids=set()
 for s in task.steps:
  if type(s) is not TaskStep or not _ID.fullmatch(s.step_id) or s.step_id in ids: raise TaskValidationError("Invalid or duplicate step ID")
  ids.add(s.step_id)
  if not isinstance(s.capability_id,str) or not _CAP.fullmatch(s.capability_id): raise TaskValidationError("Invalid capability ID")
  if not isinstance(s.dependencies,tuple) or len(s.dependencies)>MAX_DEPENDENCIES or any(not isinstance(d,str) for d in s.dependencies): raise TaskValidationError("Invalid dependencies")
  if len(set(s.dependencies))!=len(s.dependencies) or s.step_id in s.dependencies: raise TaskValidationError("Duplicate or self dependency")
  _enum(s.status,StepStatus,"step status")
  if type(s.attempts) is not int or not 0<=s.attempts<=100: raise TaskValidationError("Invalid attempt count")
  if not isinstance(s.arguments_json,str) or len(s.arguments_json)>MAX_ARGS_CHARS: raise TaskValidationError("Arguments exceed size cap")
  if not isinstance(s.idempotency_key,str) or len(s.idempotency_key)>128: raise TaskValidationError("Invalid idempotency key")
  if not isinstance(s.outcome_summary,str) or len(s.outcome_summary)>300: raise TaskValidationError("Invalid outcome summary")
 for s in task.steps:
  if any(d not in ids for d in s.dependencies): raise TaskValidationError("Missing dependency")
 graph={s.step_id:s.dependencies for s in task.steps}; visiting=set(); done=set()
 def visit(node):
  if node in visiting: raise TaskValidationError("Dependency cycle")
  if node in done:return
  visiting.add(node)
  for d in graph[node]:visit(d)
  visiting.remove(node);done.add(node)
 for node in graph:visit(node)
 if not isinstance(task.receipt_ids,tuple) or len(task.receipt_ids)>100 or any(not isinstance(r,str) or len(r)>128 for r in task.receipt_ids): raise TaskValidationError("Invalid receipts")
 return task

def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
 current=_enum(current,TaskStatus,"task status");target=_enum(target,TaskStatus,"task status")
 return target in _ALLOWED.get(current,set())

def transition_task(task: Task, target: TaskStatus, *, now: float|None=None) -> Task:
 validate_task(task); target=_enum(target,TaskStatus,"task status")
 if not can_transition(task.status,target): raise TaskValidationError(f"Illegal transition: {task.status.value} -> {target.value}")
 if now is not None and (type(now) not in (int,float) or not math.isfinite(now)): raise TaskValidationError("Invalid transition time")
 return replace(task,status=target,updated_at=task.updated_at if now is None else float(now))
def dependencies_satisfied(step: TaskStep, steps: Iterable[TaskStep]) -> bool:
 index={s.step_id:s for s in steps}
 return all(d in index and index[d].status==StepStatus.COMPLETED for d in step.dependencies)
