"""Natural-language shortcuts for Cinnamon's existing prefix commands.

This is intentionally a deterministic, narrow adapter: it maps a clear request
onto an existing command and never invents a capability or bypasses command
checks. Ambiguous requests fall through to ordinary Cinnamon chat.
"""
import re as _ccr_re
import json as _ccr_json

_CCR_ITEM_ALIASES = {
    "tuna": ("tuna", "🐟"),
    "cat treat": ("treat", "🍪"),
    "treat": ("treat", "🍪"),
    "churu": ("churu", "🥫"),
    "catnip ball": ("catnip_ball", "🧶"),
    "fancy fish": ("fish", "🐠"),
    "fish": ("fish", "🐠"),
}

def _ccr_clean(text):
    text = str(text or "").strip()
    text = _ccr_re.sub(r"^(?:hey\s+)?cinnamon\b[\s,:-]*", "", text, flags=_ccr_re.I)
    text = _ccr_re.sub(r"^(?:please\s+)?", "", text, flags=_ccr_re.I)
    return text.strip(" .,!?:;")

def _ccr_command(text):
    """Return a prefix command string for only unambiguous, low-risk requests."""
    t = _ccr_clean(text).lower()
    if not t:
        return None
    if _ccr_re.search(r"\b(?:balance|wallet|how much (?:catnip|money)|my catnip|how much do i have)\b", t):
        return "balance"
    if _ccr_re.fullmatch(r"(?:work|work please|can i work|let me work|earn catnip|earn some catnip|make (?:some )?money|i want to work)", t):
        return "work"
    if _ccr_re.fullmatch(r"(?:daily|claim daily|daily reward|claim my daily|claim my reward|collect daily reward)", t):
        return "daily"
    if _ccr_re.fullmatch(r"(?:shop|show (?:me )?(?:the )?shop|open (?:the )?shop)", t):
        return "shop"
    if _ccr_re.fullmatch(r"(?:inventory|inv|what do i own|show (?:me )?(?:my )?inventory)", t):
        return "inventory"
    m = _ccr_re.fullmatch(r"(?:buy\s+(?:me\s+)?|get me\s+|purchase\s+)(?:(\d+)\s+)?(.+?)(?:\s+(?:please|pls))?", t)
    if m:
        qty = int(m.group(1) or 1)
        item_text = m.group(2).strip()
        item = next((key for alias,(key,_) in _CCR_ITEM_ALIASES.items() if alias == item_text),None)
        if item and 1 <= qty <= 25:
            return f"buy {item} {qty}"
    return None



async def _ccr_invoke(message, command_line):
    original=message.content
    try:
        message.content='?'+command_line.strip()
        ctx=await bot.get_context(message)
        if not ctx.valid:return False
        await bot.invoke(ctx)
        return True
    finally:message.content=original

async def _ccr_ai_route(message, text):
    """Map a clear request to one existing prefix command via Gemini."""
    if not message.guild or message.author.bot: return False
    rows=[]
    def add_commands(commands):
        for command in commands:
            if command.hidden: continue
            rows.append(f"?{command.qualified_name} {command.signature} - {(command.help or command.brief or '')[:140]}")
            children=getattr(command,'commands',None)
            if children: add_commands(children)
    add_commands(bot.commands)
    catalog='\n'.join(rows[:180])
    prompt=("Map this request to ONE command from this catalog, or null. Never invent commands. "
      'Return JSON only: {"command": string|null, "arguments": string}. Arguments omit command/prefix. '
      "No multi-command plans. Names/targets must be literal from request. For moderation/server changes, route only if user explicitly requests that exact action.\nCATALOG:\n"+catalog+"\nREQUEST: "+_ccr_clean(text))
    try:
        response=await asyncio.to_thread(gemini_client.models.generate_content, model=GEMINI_MODEL, contents=prompt,
          config=types.GenerateContentConfig(response_mime_type="application/json", max_output_tokens=180, temperature=0))
        data=_ccr_json.loads((response.text or '').strip().strip('`'))
        name=str(data.get('command') or '').strip().lower(); args=str(data.get('arguments') or '').strip()
    except Exception:
        log.debug('Command intent parse failed', exc_info=True); return False
    command=bot.get_command(name.split()[0]) if name else None
    if not command or command.hidden or len(args)>500 or '?' in args or '\n' in args: return False
    if _ccr_re.search(r'@(?:everyone|here)',args,re.I): return False
    return await _ccr_invoke(message,(name+' '+args).strip())
async def _ccr_maybe_route(message, raw_text):
    """Dispatch explicit Cinnamon-directed shorthand through the normal prefix command."""
    if not message.guild or message.author.bot:
        return False
    command = _ccr_command(raw_text)
    if not command:
        return await _ccr_ai_route(message, raw_text)
    # Reuse the exact existing command callback, converters, checks and cooldowns.
    original = message.content
    try:
        message.content = "?" + command
        ctx = await bot.get_context(message)
        if not ctx.valid:
            return False
        await bot.invoke(ctx)
        return True
    finally:
        message.content = original
