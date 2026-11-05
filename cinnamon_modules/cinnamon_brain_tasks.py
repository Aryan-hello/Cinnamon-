"""Member-owned Brain task tracking commands; no task step auto-execution."""
import time as _cbt_time
import uuid as _cbt_uuid
import discord
from discord import app_commands
from cinnamon_modules.brain_tasks import Task,TaskStatus,transition_task
from cinnamon_modules.brain_task_store import create_task,get_task,update_task,TaskStoreError

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
bot.tree.add_command(_CBT_GROUP)
