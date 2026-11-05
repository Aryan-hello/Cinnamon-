"""Member-owned Brain task tracking commands; no task step auto-execution."""
import time as _cbt_time
import uuid as _cbt_uuid
import json as _cbt_json
from dataclasses import replace as _cbt_replace
import discord
from discord import app_commands
from cinnamon_modules.brain_tasks import Task,TaskStatus,transition_task
from cinnamon_modules.brain_task_store import create_task,get_task,update_task,prepare_execution,record_execution_result,TaskStoreError
from cinnamon_modules.brain_execution import evaluate_step,ExecutionGate
from cinnamon_modules.brain_planner import parse_plan_proposal,PlanValidationError

_CBT_GROUP=app_commands.Group(name="brain-task",description="Your private Cinnamon Brain task tracker")
_CBT_TTL=7*86400
def _cbt_snapshot(guild_id):
 return advanced_features_data.setdefault("cinnamon_brain_tasks_v1",{}).setdefault(str(guild_id),{})
def _cbt_owner_snapshot(guild_id,user_id):
 return _cbt_snapshot(guild_id).setdefault(str(user_id),{"brain_tasks":{"tasks":{}}})
def _cbt_list(snapshot):
 records=snapshot.get("brain_tasks",{}).get("tasks",{})
 return list(records.values()) if isinstance(records,dict) else []

@_CBT_GROUP.command(name="create",description="Create a task for yourself")
@app_commands.guild_only()
@app_commands.describe(goal="A short task goal (no actions run automatically)")
async def brain_task_create(interaction:discord.Interaction,goal:str):
 goal=str(goal or "").strip()
 if not goal or len(goal)>240:
  return await interaction.response.send_message("🐾 Keep the task goal between 1 and 240 characters.",ephemeral=True)
 await interaction.response.defer(ephemeral=True)
 now=_cbt_time.time();tid=_cbt_uuid.uuid4().hex[:10]
 task=Task(tid,interaction.guild.id,interaction.user.id,goal,now,now+_CBT_TTL,TaskStatus.DRAFT,(),updated_at=now)
 state=_cbt_owner_snapshot(interaction.guild.id,interaction.user.id)
 try:create_task(state,task,now=now)
 except TaskStoreError as exc:
  return await interaction.followup.send("🐾 I couldn't create that task: "+str(exc),ephemeral=True)
 if not await bd_save_data():
  state["brain_tasks"]["tasks"].pop(tid,None)
  return await interaction.followup.send("⚠️ Storage didn't confirm the task. Nothing was saved.",ephemeral=True)
 await interaction.followup.send("🧠 Task **"+tid+"** created.\n**Goal:** "+discord.utils.escape_markdown(goal)+"\n**Status:** Draft · expires in 7 days\n*No actions have been executed.*",ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

@_CBT_GROUP.command(name="list",description="List your Brain tasks")
@app_commands.guild_only()
async def brain_task_list(interaction:discord.Interaction):
 state=_cbt_owner_snapshot(interaction.guild.id,interaction.user.id);records=_cbt_list(state);lines=[]
 for raw in records[-10:]:
  try:
   t=get_task(state,raw.get("task_id"),guild_id=interaction.guild.id,member_id=interaction.user.id)
   if t:lines.append("**"+t.task_id+"** · "+t.status.value+" · "+discord.utils.escape_markdown(t.goal[:100]))
  except (TaskStoreError,AttributeError):continue
 await interaction.response.send_message("🧠 **Your Brain tasks**\n"+("\n".join(lines) if lines else "No tasks yet. Use /brain-task create."),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

@_CBT_GROUP.command(name="status",description="Inspect one of your Brain tasks")
@app_commands.guild_only()
async def brain_task_status(interaction:discord.Interaction,task_id:str):
 state=_cbt_owner_snapshot(interaction.guild.id,interaction.user.id)
 try:t=get_task(state,task_id.strip(),guild_id=interaction.guild.id,member_id=interaction.user.id)
 except TaskStoreError:t=None
 if not t:return await interaction.response.send_message("🐾 Task not found in your private task list.",ephemeral=True)
 await interaction.response.send_message("🧠 **Task "+t.task_id+"**\n**Goal:** "+discord.utils.escape_markdown(t.goal)+"\n**Status:** "+t.status.value+"\n**Revision:** "+str(t.plan_version)+"\n**Expiry:** <t:"+str(int(t.expires_at))+":R>\n**Steps:** "+str(len(t.steps))+"\n*Task tracking only; no step execution is enabled yet.*",ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

@_CBT_GROUP.command(name="cancel",description="Cancel one of your Brain tasks")
@app_commands.guild_only()
async def brain_task_cancel(interaction:discord.Interaction,task_id:str):
 await interaction.response.defer(ephemeral=True);state=_cbt_owner_snapshot(interaction.guild.id,interaction.user.id)
 try:
  current=get_task(state,task_id.strip(),guild_id=interaction.guild.id,member_id=interaction.user.id)
  if not current:raise TaskStoreError("Task not found")
  now=_cbt_time.time()
  changed=update_task(state,task_id=current.task_id,guild_id=interaction.guild.id,member_id=interaction.user.id,expected_version=current.plan_version,transform=lambda t:transition_task(t,TaskStatus.CANCELLED,now=now),now=now)
 except (TaskStoreError,ValueError) as exc:
  return await interaction.followup.send("🐾 Couldn't cancel: "+str(exc),ephemeral=True)
 if not await bd_save_data():
  return await interaction.followup.send("⚠️ Storage didn't confirm cancellation. Check task status before retrying.",ephemeral=True)
 await interaction.followup.send("✅ Task "+changed.task_id+" cancelled.",ephemeral=True)

@_CBT_GROUP.command(name="approve",description="Approve your reviewed task plan for 5 minutes")
@app_commands.guild_only()
async def brain_task_approve(interaction:discord.Interaction,task_id:str):
 await interaction.response.defer(ephemeral=True)
 state=_cbt_owner_snapshot(interaction.guild.id,interaction.user.id)
 try:
  current=get_task(state,task_id.strip(),guild_id=interaction.guild.id,member_id=interaction.user.id)
  if not current:raise TaskStoreError("Task not found")
  if current.status!=TaskStatus.AWAITING_APPROVAL:raise TaskStoreError("Review and save a plan first")
  if not current.steps:raise TaskStoreError("The plan has no steps")
  now=_cbt_time.time()
  changed=update_task(state,task_id=current.task_id,guild_id=interaction.guild.id,member_id=interaction.user.id,expected_version=current.plan_version,transform=lambda t:_cbt_replace(t,status=TaskStatus.READY,approval_expires_at=now+300),now=now)
 except (TaskStoreError,ValueError) as exc:
  return await interaction.followup.send("🐾 Approval refused: "+str(exc),ephemeral=True)
 if not await bd_save_data():
  return await interaction.followup.send("⚠️ Storage did not confirm approval. Do not run this task yet.",ephemeral=True)
 await interaction.followup.send("✅ Task **"+changed.task_id+"** approved for 5 minutes. Approval is limited to this plan; use /brain-task run for each step.",ephemeral=True)

@_CBT_GROUP.command(name="run",description="Execute one approved, reviewed task step")
@app_commands.guild_only()
@app_commands.describe(task_id="Your approved task ID",step_id="The step ID shown in review")
async def brain_task_run(interaction:discord.Interaction,task_id:str,step_id:str):
 await interaction.response.defer(ephemeral=True)
 state=_cbt_owner_snapshot(interaction.guild.id,interaction.user.id)
 try:
  current=get_task(state,task_id.strip(),guild_id=interaction.guild.id,member_id=interaction.user.id)
  if not current:raise TaskStoreError("Task not found")
  step=next((s for s in current.steps if s.step_id==step_id.strip()),None)
  if not step:raise TaskStoreError("Step not found")
  if step.capability_id!="discord.send_message":raise TaskStoreError("This capability has no trusted executor")
  args=_cbt_json.loads(step.arguments_json)
  if set(args)!={"channel_id","content"} or type(args.get("channel_id")) is not int or not isinstance(args.get("content"),str) or not args["content"].strip() or len(args["content"])>1800:
   raise TaskStoreError("Message arguments are invalid")
  channel=interaction.guild.get_channel(args["channel_id"])
  if channel is None or not hasattr(channel,"send"):raise TaskStoreError("Choose a text channel in this server")
  user_perms=channel.permissions_for(interaction.user)
  bot_member=interaction.guild.me
  bot_perms=channel.permissions_for(bot_member)
  if not user_perms.view_channel or not user_perms.send_messages:raise TaskStoreError("You need View Channel and Send Messages there")
  if not bot_perms.view_channel or not bot_perms.send_messages:raise TaskStoreError("Cinnamon lacks permission to send there")
  now=_cbt_time.time()
  gate=evaluate_step(current,step.step_id,now=now,requester_id=interaction.user.id,guild_id=interaction.guild.id,storage_ready=True,feature_enabled=True,permission_ok=True,serious=False)
  if gate!=ExecutionGate.ALLOW:raise TaskStoreError("Execution gate refused: "+gate.value)
  running=prepare_execution(state,task_id=current.task_id,step_id=step.step_id,guild_id=interaction.guild.id,member_id=interaction.user.id,now=now)
  if not await bd_save_data():raise TaskStoreError("The execution claim was not durably saved; no message was sent")
 except (TaskStoreError,ValueError,KeyError,TypeError) as exc:
  return await interaction.followup.send("🐾 Step refused: "+str(exc),ephemeral=True)
 try:
  await channel.send(args["content"],allowed_mentions=discord.AllowedMentions.none())
  success=True;summary="Message sent to channel "+str(channel.id)
 except discord.Forbidden:
  success=False;summary="Discord denied the send"
 except Exception:
  success=None;summary="Send outcome uncertain; this step will not be retried automatically"
 try:
  result=record_execution_result(state,task_id=current.task_id,step_id=step.step_id,guild_id=interaction.guild.id,member_id=interaction.user.id,expected_version=running.plan_version,success=success,summary=summary,now=_cbt_time.time())
  saved=await bd_save_data()
 except Exception:
  result=None;saved=False
 if success is True:
  msg=("✅ "+summary+". " if saved else "⚠️ Message may have been sent, but its result wasn't confirmed in storage. ")
  msg+=("Task completed." if result and result.status==TaskStatus.COMPLETED else "You can run the next dependency-ready step.")
 elif success is False:
  msg="❌ "+summary+(". Failure recorded." if saved else ". Storage did not confirm the failure record.")
 else:
  msg="⚠️ "+summary+". Check Discord before taking any further action."
 await interaction.followup.send(msg,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

\nbot.tree.add_command(_CBT_GROUP)
 
# Proposal-only capability allowlist. These IDs can be drafted/reviewed, never executed.
_CBT_CAPABILITIES={"discord.send_message":{"arguments":{"channel_id":None,"content":None}}}

@_CBT_GROUP.command(name="plan",description="Attach a validated, non-executable plan to your task")
@app_commands.guild_only()
@app_commands.describe(task_id="Your task ID",plan_json="JSON with goal and steps (proposal only)")
async def brain_task_plan(interaction:discord.Interaction,task_id:str,plan_json:str):
 await interaction.response.defer(ephemeral=True)
 try:proposal=parse_plan_proposal(plan_json,_CBT_CAPABILITIES)
 except PlanValidationError as exc:
  return await interaction.followup.send("🐾 Plan rejected: "+str(exc),ephemeral=True)
 state=_cbt_owner_snapshot(interaction.guild.id,interaction.user.id)
 try:
  current=get_task(state,task_id.strip(),guild_id=interaction.guild.id,member_id=interaction.user.id)
  if not current:raise TaskStoreError("Task not found")
  if current.status!=TaskStatus.DRAFT:raise TaskStoreError("Only draft tasks can be edited")
  steps=tuple(_cbt_replace(step,idempotency_key=_cbt_uuid.uuid4().hex) for step in proposal.steps)
  now=_cbt_time.time()
  changed=update_task(state,task_id=current.task_id,guild_id=interaction.guild.id,member_id=interaction.user.id,expected_version=current.plan_version,transform=lambda t:_cbt_replace(t,goal=proposal.goal,steps=steps,status=TaskStatus.AWAITING_APPROVAL,approval_expires_at=now+300),now=now)
 except (TaskStoreError,ValueError) as exc:
  return await interaction.followup.send("🐾 Couldn't attach plan: "+str(exc),ephemeral=True)
 if not await bd_save_data():
  return await interaction.followup.send("⚠️ Storage didn't confirm the plan. Check status before retrying.",ephemeral=True)
 lines=[f"{i}. **{s.capability_id}** · ID {s.step_id} · deps: {', '.join(s.dependencies) or 'none'}" for i,s in enumerate(changed.steps,1)]
 await interaction.followup.send("🧠 **Plan saved as a proposal (not executable).**\n"+discord.utils.escape_markdown(changed.goal)+"\n"+("\n".join(lines) if lines else "No steps.")+"\nUse /brain-task review to inspect it. No actions were run.",ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

@_CBT_GROUP.command(name="review",description="Review your task plan before any future approval")
@app_commands.guild_only()
async def brain_task_review(interaction:discord.Interaction,task_id:str):
 state=_cbt_owner_snapshot(interaction.guild.id,interaction.user.id)
 try:t=get_task(state,task_id.strip(),guild_id=interaction.guild.id,member_id=interaction.user.id)
 except TaskStoreError:t=None
 if not t:return await interaction.response.send_message("🐾 Task not found.",ephemeral=True)
 rows=[]
 for s in t.steps:
  try:args=_cbt_json.loads(s.arguments_json)
  except Exception:args={}
  rows.append(f"**{s.step_id} · {s.capability_id}**\nDeps: {', '.join(s.dependencies) or 'none'}\nArgs: `{_cbt_json.dumps(args,ensure_ascii=False)[:500]}`")
 await interaction.response.send_message("🔎 **Plan review · "+t.task_id+"**\nGoal: "+discord.utils.escape_markdown(t.goal)+"\n"+("\n".join(rows) if rows else "No plan steps.")+"\n\n⚠️ Review only. Cinnamon currently cannot execute Brain task steps.",ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

