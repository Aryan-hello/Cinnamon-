"""Bounded, scope-safe task records inside a caller-owned snapshot.

This is deliberately a pure adapter: persistence/locking belong to SnapshotStore,
and Discord authorization belongs to the trusted command/executor layer.
"""
from __future__ import annotations
from dataclasses import replace
import json
from typing import Callable
from cinnamon_modules.brain_tasks import Task, TaskStep, TaskStatus, StepStatus, validate_task, transition_task

MAX_TASKS = 100
MAX_TASK_JSON = 16_000

class TaskStoreError(ValueError):
    pass

def _encode(task: Task) -> dict:
    validate_task(task)
    return {
        "task_id":task.task_id,"guild_id":task.guild_id,"member_id":task.member_id,
        "goal":task.goal,"created_at":task.created_at,"expires_at":task.expires_at,
        "status":task.status.value,"updated_at":task.updated_at,"plan_version":task.plan_version,
        "approval_expires_at":task.approval_expires_at,"receipt_ids":list(task.receipt_ids),
        "steps":[{"step_id":s.step_id,"capability_id":s.capability_id,
            "dependencies":list(s.dependencies),"status":s.status.value,"attempts":s.attempts,
            "arguments_json":s.arguments_json,"idempotency_key":s.idempotency_key,
            "outcome_summary":s.outcome_summary} for s in task.steps],
    }

def _decode(raw) -> Task:
    if not isinstance(raw,dict): raise TaskStoreError("Task record is corrupt")
    try:
        steps=tuple(TaskStep(s["step_id"],s["capability_id"],tuple(s["dependencies"]),
            StepStatus(s["status"]),s["attempts"],s["arguments_json"],
            s["idempotency_key"],s["outcome_summary"]) for s in raw["steps"])
        task=Task(raw["task_id"],raw["guild_id"],raw["member_id"],raw["goal"],
            raw["created_at"],raw["expires_at"],TaskStatus(raw["status"]),steps,
            raw["updated_at"],raw["plan_version"],raw["approval_expires_at"],
            tuple(raw["receipt_ids"]))
        validate_task(task)
        if len(json.dumps(_encode(task),allow_nan=False,separators=(",",":")))>MAX_TASK_JSON:
            raise TaskStoreError("Task record exceeds storage budget")
        return task
    except TaskStoreError: raise
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        raise TaskStoreError("Task record is corrupt") from exc

def _records(snapshot:dict, *, create=False) -> dict:
    if not isinstance(snapshot,dict): raise TaskStoreError("Snapshot must be a mapping")
    container=snapshot.get("brain_tasks")
    if container is None and create:
        container={"tasks":{}};snapshot["brain_tasks"]=container
    if not isinstance(container,dict) or not isinstance(container.get("tasks"),dict):
        raise TaskStoreError("Task storage is unavailable or corrupt")
    return container["tasks"]

def create_task(snapshot:dict, task:Task, *, now:float) -> Task:
    validate_task(task)
    if type(now) not in (int,float) or now>=task.expires_at or now<task.created_at:
        raise TaskStoreError("Task is expired or creation time is invalid")
    records=_records(snapshot,create=True)
    if task.task_id in records:
        existing=_decode(records[task.task_id])
        if existing==task:return existing
        raise TaskStoreError("Task ID already exists")
    if len(records)>=MAX_TASKS: raise TaskStoreError("Task capacity reached")
    records[task.task_id]=_encode(task)
    return task

def get_task(snapshot:dict, task_id:str, *, guild_id:int, member_id:int) -> Task|None:
    records=_records(snapshot)
    raw=records.get(task_id)
    if raw is None:return None
    task=_decode(raw)
    if task.guild_id!=guild_id or task.member_id!=member_id:return None
    return task

def update_task(snapshot:dict, *, task_id:str, guild_id:int, member_id:int,
                expected_version:int, transform:Callable[[Task],Task], now:float) -> Task:
    records=_records(snapshot)
    current=_decode(records.get(task_id))
    if current.guild_id!=guild_id or current.member_id!=member_id:
        raise TaskStoreError("Task not found in this scope")
    if current.plan_version!=expected_version:raise TaskStoreError("Stale task revision")
    if current.expires_at<=now:raise TaskStoreError("Task expired")
    if not callable(transform):raise TaskStoreError("Invalid task update")
    updated=transform(current)
    if type(updated) is not Task or updated.task_id!=current.task_id or updated.guild_id!=guild_id or updated.member_id!=member_id:
        raise TaskStoreError("Task update changed its identity or scope")
    updated=replace(updated,plan_version=current.plan_version+1,updated_at=float(now))
    validate_task(updated)
    records[task_id]=_encode(updated)
    return updated

def cancel_task(snapshot:dict, task_id:str, *, guild_id:int, member_id:int, now:float) -> Task:
    return update_task(snapshot,task_id=task_id,guild_id=guild_id,member_id=member_id,
        expected_version=_decode(_records(snapshot).get(task_id)).plan_version,
        transform=lambda task: transition_task(task,TaskStatus.CANCELLED,now=now),now=now)

def prune_tasks(snapshot:dict, *, now:float) -> list[str]:
    records=_records(snapshot);removed=[]
    for task_id,raw in list(records.items()):
        task=_decode(raw)
        if task.expires_at<=now:
            del records[task_id];removed.append(task_id)
    return removed

def prepare_execution(snapshot:dict, *, task_id:str, step_id:str, guild_id:int, member_id:int, now:float)->Task:
 """Persist RUNNING claim before any external call; duplicate claims fail closed."""
 current=get_task(snapshot,task_id,guild_id=guild_id,member_id=member_id)
 if current is None:raise TaskStoreError("Task not found")
 if current.status!=TaskStatus.READY:raise TaskStoreError("Task is not ready")
 if current.expires_at<=now or (current.approval_expires_at and current.approval_expires_at<=now):raise TaskStoreError("Task or approval expired")
 step=next((s for s in current.steps if s.step_id==step_id),None)
 if step is None or step.status!=StepStatus.PENDING:raise TaskStoreError("Step is not pending")
 if not all(next((x.status==StepStatus.COMPLETED for x in current.steps if x.step_id==d),False) for d in step.dependencies):raise TaskStoreError("Dependencies incomplete")
 steps=tuple(_replace(s,status=StepStatus.RUNNING,attempts=s.attempts+1) if s.step_id==step_id else s for s in current.steps)
 running=_replace(current,status=TaskStatus.RUNNING,steps=steps,updated_at=float(now))
 records=_records(snapshot);records[task_id]=_encode(running)
 return running

def prune_tasks(snapshot:dict, *, now:float) -> list[str]:
    records=_records(snapshot);removed=[]
    for task_id,raw in list(records.items()):
        task=_decode(raw)
        if task.expires_at<=now:
            del records[task_id];removed.append(task_id)
    return removed

def prepare_execution(snapshot:dict, *, task_id:str, step_id:str, guild_id:int, member_id:int, now:float)->Task:
 """Persist RUNNING claim before any external call; duplicate claims fail closed."""
 current=get_task(snapshot,task_id,guild_id=guild_id,member_id=member_id)
 if current is None:raise TaskStoreError("Task not found")
 if current.status!=TaskStatus.READY:raise TaskStoreError("Task is not ready")
 if current.expires_at<=now or (current.approval_expires_at and current.approval_expires_at<=now):raise TaskStoreError("Task or approval expired")
 step=next((s for s in current.steps if s.step_id==step_id),None)
 if step is None or step.status!=StepStatus.PENDING:raise TaskStoreError("Step is not pending")
 if not all(next((x.status==StepStatus.COMPLETED for x in current.steps if x.step_id==d),False) for d in step.dependencies):raise TaskStoreError("Dependencies incomplete")
 from dataclasses import replace as _replace
 from cinnamon_modules.brain_tasks import StepStatus
 steps=tuple(_replace(s,status=StepStatus.RUNNING,attempts=s.attempts+1) if s.step_id==step_id else s for s in current.steps)
 running=_replace(current,status=TaskStatus.RUNNING,steps=steps,updated_at=float(now))
 records=_records(snapshot);records[task_id]=_encode(running)
 return running

def record_execution_result(snapshot:dict, *, task_id:str,step_id:str,guild_id:int,member_id:int,expected_version:int,success:bool|None,summary:str,now:float)->Task:
 """Persist success/failure/uncertainty. Unknown external outcomes never retry."""
 from dataclasses import replace as _replace
 from cinnamon_modules.brain_tasks import StepStatus
 current=get_task(snapshot,task_id,guild_id=guild_id,member_id=member_id)
 if current is None:raise TaskStoreError("Task not found")
 if current.plan_version!=expected_version:raise TaskStoreError("Stale task revision")
 if current.status!=TaskStatus.RUNNING:raise TaskStoreError("Task is not running")
 step=next((s for s in current.steps if s.step_id==step_id),None)
 if step is None or step.status!=StepStatus.RUNNING:raise TaskStoreError("Step is not running")
 if success not in (True,False,None):raise TaskStoreError("Invalid outcome")
 status=StepStatus.COMPLETED if success is True else StepStatus.FAILED if success is False else StepStatus.UNCERTAIN
 steps=tuple(_replace(s,status=status,outcome_summary=str(summary)[:300]) if s.step_id==step_id else s for s in current.steps)
 if success is True and all(s.status==StepStatus.COMPLETED for s in steps):target=TaskStatus.COMPLETED
 elif success is True:target=TaskStatus.READY
 elif success is False:target=TaskStatus.FAILED
 else:target=TaskStatus.UNCERTAIN
 updated=_replace(current,status=target,steps=steps,updated_at=float(now),plan_version=current.plan_version+1)
 validate_task(updated);_records(snapshot)[task_id]=_encode(updated)
 return updated
