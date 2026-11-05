"""Deterministic, scope-first retrieval for explicit Cinnamon member notes."""
from __future__ import annotations
import re
from typing import Iterable,Mapping
TOKEN=re.compile(r"[a-z0-9]{2,}",re.I)
def retrieve_relevant_memories(query: str, notes: Iterable[Mapping], *, guild_id: int, member_id: int, limit: int=5, max_chars: int=900, opt_out: bool=False)->list[dict]:
 if opt_out or type(guild_id) is not int or type(member_id) is not int or guild_id<=0 or member_id<=0:return []
 if type(limit) is not int or limit<1:return []
 if type(max_chars) is not int or max_chars<0:return []
 q=set(t.lower() for t in TOKEN.findall(str(query or "")))
 eligible=[]
 for n in notes:
  if not isinstance(n,Mapping):continue
  if n.get("guild_id")!=guild_id or n.get("member_id")!=member_id or n.get("active",True) is not True:continue
  text=str(n.get("text","")).strip()
  if not text:continue
  tokens=set(t.lower() for t in TOKEN.findall(text))
  score=len(q&tokens) if q else 1
  if score:eligible.append((score,str(n.get("note_id","")),text))
 eligible.sort(key=lambda x:(-x[0],x[1]))
 result=[];used=0
 for score,nid,text in eligible[:limit]:
  remaining=max_chars-used
  if remaining<=0:break
  clipped=text[:remaining]
  if clipped:result.append({"note_id":nid,"text":clipped,"relevance":score});used+=len(clipped)
 return result

def retrieve_memories(notes, *, guild_id:int, member_id:int, query:str, opted_out:bool=False, max_items:int=5):
 """Adapter for Cinnamon preference records; scope is verified before ranking."""
 if opted_out or type(guild_id) is not int or type(member_id) is not int:return []
 normalized=[]
 for note in notes or []:
  if not isinstance(note,Mapping):continue
  normalized.append({"guild_id":guild_id,"member_id":member_id,
   "note_id":str(note.get("id","")),"text":str(note.get("detail","")),
   "active":True})
 return retrieve_relevant_memories(query,normalized,guild_id=guild_id,
  member_id=member_id,limit=max(1,min(5,int(max_items))),max_chars=900)
