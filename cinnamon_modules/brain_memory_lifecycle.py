"""Explicit, privacy-limited member memory lifecycle on a caller-owned snapshot."""
from __future__ import annotations
from cinnamon_modules.brain_memory import validate_preference,MemoryValidationError

MAX_PER_MEMBER=12
class MemoryLifecycleError(ValueError):pass

def _scope(guild_id,member_id):
 if type(guild_id) is not int or guild_id<=0 or type(member_id) is not int or member_id<=0:
  raise MemoryLifecycleError("Invalid memory scope")
 return f"{guild_id}:{member_id}"

def _container(snapshot,create=False):
 if not isinstance(snapshot,dict):raise MemoryLifecycleError("Snapshot unavailable")
 data=snapshot.get("brain_memory")
 if data is None:
  if not create:return {"members":{},"opt_out":[]}
  data={"members":{},"opt_out":[]};snapshot["brain_memory"]=data
 if not isinstance(data,dict) or not isinstance(data.get("members"),dict) or not isinstance(data.get("opt_out"),list):
  raise MemoryLifecycleError("Memory storage unavailable or corrupt")
 return data

def _opted(data,key):return key in data["opt_out"]

def set_opt_out(snapshot,*,guild_id,member_id,enabled):
 if type(enabled) is not bool:raise MemoryLifecycleError("Invalid opt-out setting")
 data=_container(snapshot,create=True);key=_scope(guild_id,member_id)
 if enabled:
  if key not in data["opt_out"]:data["opt_out"].append(key)
  data["members"].pop(key,None) # opting out also clears existing saved notes
 else:data["opt_out"]=[v for v in data["opt_out"] if v!=key]
 return enabled

def save_note(snapshot,*,guild_id,member_id,note_id,category,detail):
 data=_container(snapshot,create=True);key=_scope(guild_id,member_id)
 if _opted(data,key):raise MemoryLifecycleError("Memory is disabled for this member")
 if not isinstance(note_id,str) or not 1<=len(note_id)<=64:raise MemoryLifecycleError("Invalid note ID")
 try:pref=validate_preference(category,detail)
 except MemoryValidationError as exc:raise MemoryLifecycleError(str(exc)) from None
 notes=data["members"].setdefault(key,{})
 if not isinstance(notes,dict):raise MemoryLifecycleError("Member memory is corrupt")
 if note_id not in notes and len(notes)>=MAX_PER_MEMBER:raise MemoryLifecycleError("Memory limit reached")
 record={"note_id":note_id,"guild_id":guild_id,"member_id":member_id,
         "category":pref.category,"detail":pref.detail,"active":True}
 notes[note_id]=record
 return dict(record)

def list_notes(snapshot,*,guild_id,member_id):
 data=_container(snapshot);key=_scope(guild_id,member_id)
 if _opted(data,key):return []
 notes=data["members"].get(key,{})
 if not isinstance(notes,dict):raise MemoryLifecycleError("Member memory is corrupt")
 result=[]
 for note in notes.values():
  if not isinstance(note,dict) or note.get("guild_id")!=guild_id or note.get("member_id")!=member_id:continue
  try:pref=validate_preference(note.get("category"),note.get("detail"))
  except MemoryValidationError:continue
  result.append({"note_id":note.get("note_id",""),"guild_id":guild_id,"member_id":member_id,
                 "category":pref.category,"detail":pref.detail,"active":True})
 return sorted(result,key=lambda n:n["note_id"])

def delete_note(snapshot,*,guild_id,member_id,note_id):
 data=_container(snapshot);key=_scope(guild_id,member_id)
 if _opted(data,key):return False
 notes=data["members"].get(key,{})
 if not isinstance(notes,dict):raise MemoryLifecycleError("Member memory is corrupt")
 record=notes.get(note_id)
 if not isinstance(record,dict) or record.get("guild_id")!=guild_id or record.get("member_id")!=member_id:return False
 del notes[note_id]
 return True
