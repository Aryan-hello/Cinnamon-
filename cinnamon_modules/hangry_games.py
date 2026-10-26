"""Cinnamon feature module.

Loaded by main.py into Cinnamon's shared runtime namespace. This is still
one Discord bot and one process; this file is not a separate bot.
Do not run this file directly.
"""

def _hg_decode(raw: dict) -> dict:
    pair = lambda d: {tuple(map(int, k.split(":"))): v for k, v in d.items()}
    return {
        "game_counts": {int(k): v for k, v in raw.get("game_counts", {}).items()},
        "win_counts": pair(raw.get("win_counts", {})),
        "kill_counts": pair(raw.get("kill_counts", {})),
        "played_counts": pair(raw.get("played_counts", {})),
        "log_channels": {int(k): v for k, v in raw.get("log_channels", {}).items()},
        "log_enabled": {int(k): v for k, v in raw.get("log_enabled", {}).items()},
        "budget_records": pair(raw.get("budget_records", {})),
        "host_records": pair(raw.get("host_records", {})),
    }


def _hg_encode(state: dict) -> dict:
    pair = lambda d: {f"{g}:{m}": v for (g, m), v in d.items()}
    return {
        "game_counts": {str(k): v for k, v in state["game_counts"].items()},
        "win_counts": pair(state["win_counts"]),
        "kill_counts": pair(state["kill_counts"]),
        "played_counts": pair(state["played_counts"]),
        "log_channels": {str(k): v for k, v in state["log_channels"].items()},
        "log_enabled": {str(k): v for k, v in state["log_enabled"].items()},
        "budget_records": pair(state.get("budget_records", {})),
        "host_records": pair(state.get("host_records", {})),
    }


async def hg_load_data() -> dict:
    """Load persisted game/win counts and the dedicated Hangry Games log channel.
    Uses Upstash Redis (survives redeploys on hosts with no persistent disk, e.g.
    Render free tier) when UPSTASH_REDIS_REST_URL/UPSTASH_REDIS_REST_TOKEN are
    set; otherwise falls back to a local JSON file (only survives plain
    restarts, not redeploys, on most free hosts). Never raises — a missing/
    corrupt/unreachable store just means we start fresh."""
    empty = _hg_decode({})
    if HG_UPSTASH_URL and HG_UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    HG_UPSTASH_URL, json=["GET", HG_REDIS_KEY],
                    headers={"Authorization": f"Bearer {HG_UPSTASH_TOKEN}"},
                ) as resp:
                    result = (await resp.json()).get("result")
            return _hg_decode(json.loads(result)) if result else empty
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, ValueError) as e:
            log.error(f"Failed to load Hangry Games data from Upstash: {e}")
            return empty
    try:
        with open(HG_DATA_FILE, "r") as f:
            return _hg_decode(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return empty


async def hg_save_data(state: dict):
    """Persist Hangry Games state (counts, stats, log settings). See hg_load_data
    for storage choice. Never raises — a failed save shouldn't crash a game."""
    encoded = _hg_encode(state)
    if HG_UPSTASH_URL and HG_UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    HG_UPSTASH_URL, json=["SET", HG_REDIS_KEY, json.dumps(encoded)],
                    headers={"Authorization": f"Bearer {HG_UPSTASH_TOKEN}"},
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.error(f"Failed to save Hangry Games data to Upstash: {e}")
        return
    try:
        with open(HG_DATA_FILE, "w") as f:
            json.dump(encoded, f)
    except OSError as e:
        log.error(f"Failed to save Hangry Games data: {e}")


class HGLobbyView(discord.ui.View):
    def __init__(self, cog: "HangryGamesCog", host: discord.Member, prize: str | None = None,
                 winner_role: discord.Role | None = None, catnip_prize: int = 0,
                 sponsor: discord.Member | None = None):
        super().__init__(timeout=600)
        self.cog = cog
        self.host = host
        self.prize = prize
        self.winner_role = winner_role
        self.catnip_prize = catnip_prize
        self.sponsor = sponsor or host
        self.players: dict[int, discord.Member] = {}
        self.started = False
        self.message: discord.Message | None = None

    def embed(self) -> discord.Embed:
        auto = getattr(self, "auto_managed", False)
        title = "🍖 CINNAMON'S SURPRISE HANGRY GAMES" if auto else (
            "🍖 Hangry Games · Giveaway" if self.prize or self.catnip_prize else "🍖 Hangry Games")
        names = "\n".join("• " + m.display_name[:70] for m in list(self.players.values())[:15]) or "Nobody yet. *Cinnamon looks offended.*"
        e = discord.Embed(title=title,
            description="**Tap Join 🐾 to enter** — Cinnamon will handle the chaos.\n\n" + names[:2000],
            color=0xD89138)
        e.add_field(name="👥 Joined", value=f"{len(self.players)} cats", inline=True)
        if self.catnip_prize:
            e.add_field(name="🌿 Winner's Catnip", value=f"**{self.catnip_prize:,}**", inline=True)
        if self.prize:
            e.add_field(name="🏆 Other prize", value=str(self.prize)[:1024], inline=False)
        e.add_field(name="⏳ Lobby", value="2 minutes to join" if auto else "Host starts when ready", inline=True)
        e.set_footer(text="Cinnamon Hangry Games • One champion • Cheer responsibly 🐈")
        return e

    @discord.ui.button(label="Join 🐾", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.started:
            return await cinnamon_send(interaction, "Already started!", ephemeral=True)
        if interaction.user.id in self.players:
            return await cinnamon_send(interaction, "You're already in — no backing out!", ephemeral=True)
        self.players[interaction.user.id] = interaction.user
        await interaction.response.edit_message(embed=self.embed(), view=self)
        await self.cog._log(interaction.guild.id, title="🐾 Hangry Games player joined",
                            fields=[("Channel", interaction.channel.mention), ("Player", f"{interaction.user} ({interaction.user.id})"),
                                    ("Players", str(len(self.players)))])

    @discord.ui.button(label="Start 🔴", style=discord.ButtonStyle.danger)
    async def start(self, interaction: discord.Interaction, _: discord.ui.Button):
        if getattr(self, "auto_managed", False):
            return await cinnamon_send(interaction, "🐈 I start this one myself after 2 minutes!", ephemeral=True)
        perms = interaction.user.guild_permissions
        if not (perms.manage_messages or perms.moderate_members or perms.administrator):
            return await cinnamon_send(interaction, "Need Manage Messages or Moderate Members to start.", ephemeral=True)
        if len(self.players) < 2:
            return await cinnamon_send(interaction, "Need at least 2 players.", ephemeral=True)
        if self.catnip_prize and interaction.user.id != self.sponsor.id:
            return await cinnamon_send(interaction, "🐾 The person sponsoring Catnip must start this game.", ephemeral=True)
        if self.catnip_prize:
            error = await self.cog._reserve_budget(interaction.guild, self.sponsor, self.catnip_prize)
            if error:
                return await cinnamon_send(interaction, error, ephemeral=True)
        self.started = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(embed=self.embed(), view=self)
        self.stop()
        self.cog.lobbies.pop(interaction.channel.id, None)
        await self.cog.launch(interaction.channel, self.players, self.host, self.prize, self.winner_role,
                              catnip_prize=self.catnip_prize, sponsor=self.sponsor)

    async def on_timeout(self):
        if self.started or not self.message:
            return
        for c in self.children:
            c.disabled = True
        self.cog.lobbies.pop(self.message.channel.id, None)
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass
        await self.cog._log(
            self.host.guild.id, title="⏰ Hangry Games lobby timed out", color=discord.Color.orange(),
            fields=[("Channel", self.message.channel.mention), ("Host", f"{self.host} ({self.host.id})"),
                    ("Players signed up", str(len(self.players)))],
        )


class HGRematchView(discord.ui.View):
    """Button under the winner embed: the host (or a mod) restarts with the same cats."""

    def __init__(self, cog: "HangryGamesCog", players: dict[int, discord.Member], host: discord.Member):
        super().__init__(timeout=300)
        self.cog, self.players, self.host = cog, players, host
        self.message: discord.Message | None = None

    @discord.ui.button(label="Rematch 🔁", style=discord.ButtonStyle.primary)
    async def rematch(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.host.id and not interaction.user.guild_permissions.manage_messages:
            return await cinnamon_send(interaction, "Only the host or a mod can start a rematch.", ephemeral=True)
        if self.cog._busy(interaction.channel.id):
            return await cinnamon_send(interaction, "A game's already running here!", ephemeral=True)
        for c in self.children:
            c.disabled = True
        self.stop()
        await interaction.response.edit_message(view=self)
        await self.cog.launch(interaction.channel, dict(self.players), self.host, None, None)

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class HangryGamesCog(commands.GroupCog, group_name="hangrygames"):
    """Play a cat-themed elimination minigame"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active: dict[int, asyncio.Task] = {}
        self.lobbies: dict[int, "HGLobbyView"] = {}  # channel_id -> lobby not yet started
        self.game_counts: dict[int, int] = {}  # guild_id -> total games run
        self.win_counts: dict[tuple[int, int], int] = {}  # (guild_id, member_id) -> total wins
        self.kill_counts: dict[tuple[int, int], int] = {}  # (guild_id, member_id) -> total kills (completed games)
        self.played_counts: dict[tuple[int, int], int] = {}  # (guild_id, member_id) -> completed games played
        self.hg_log_channels: dict[int, int] = {}  # guild_id -> dedicated Hangry Games log channel_id
        self.log_enabled: dict[int, bool] = {}  # guild_id -> whether HG activity is logged (default: on once a channel is set)
        self.budget_records = {}  # (guild, sponsor) -> {week, spent}
        self.host_records = {}  # (guild, sponsor) -> {week, completed, bonus}
        self.budget_lock = asyncio.Lock()

    async def async_init(self):
        """Load persisted counts. Call once, before add_cog, since __init__ can't await."""
        data = await hg_load_data()
        self.game_counts = data["game_counts"]
        self.win_counts = data["win_counts"]
        self.kill_counts = data["kill_counts"]
        self.played_counts = data["played_counts"]
        self.hg_log_channels = data["log_channels"]
        self.log_enabled = data["log_enabled"]
        self.budget_records = data["budget_records"]
        self.host_records = data["host_records"]

    async def _save(self):
        await hg_save_data({
            "game_counts": self.game_counts, "win_counts": self.win_counts,
            "kill_counts": self.kill_counts, "played_counts": self.played_counts,
            "log_channels": self.hg_log_channels, "log_enabled": self.log_enabled,
            "budget_records": self.budget_records, "host_records": self.host_records,
        })

    @staticmethod
    def _week():
        iso = datetime.datetime.now(datetime.timezone.utc).isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    @staticmethod
    def _budget_limit(member):
        permissions = member.guild_permissions
        if permissions.administrator:
            return None  # Admins have unlimited weekly hosting budget.
        if permissions.moderate_members:
            return 30000
        if permissions.manage_messages:
            return 20000
        return 0

    def _budget_record(self, guild_id, user_id):
        rec = self.budget_records.setdefault((guild_id, user_id), {})
        if rec.get("week") != self._week():
            rec.clear()
            rec.update({"week": self._week(), "spent": 0})
        return rec

    def _host_record(self, guild_id, user_id):
        rec = self.host_records.setdefault((guild_id, user_id), {})
        if rec.get("week") != self._week():
            rec.clear()
            rec.update({"week": self._week(), "completed": 0, "bonus": 0})
        return rec

    async def _reserve_budget(self, guild, sponsor, prize):
        """Charge weekly host budget before starting, guarded against races."""
        if prize <= 0:
            return None
        if prize > 200000:
            return "🐈 Maximum prize is 200,000 Catnip per game, even for admins."
        async with self.budget_lock:
            limit = self._budget_limit(sponsor)
            if limit == 0:
                return "🐈 To sponsor Catnip, you need Manage Messages, Moderate Members, or Administrator."
            rec = self._budget_record(guild.id, sponsor.id)
            if limit is not None and int(rec.get("spent", 0)) + prize > limit:
                left = max(0, limit - int(rec.get("spent", 0)))
                return f"😾 You have only **{left:,} Catnip** left in this week's hosting budget."
            rec["spent"] = int(rec.get("spent", 0)) + prize
            await self._save()
        return None

    async def _refund_budget(self, guild_id, sponsor_id, prize, week):
        if not prize:
            return
        async with self.budget_lock:
            rec = self.budget_records.get((guild_id, sponsor_id))
            if rec and rec.get("week") == week:
                rec["spent"] = max(0, int(rec.get("spent", 0)) - prize)
                await self._save()

    async def _host_completed(self, guild_id, host_id):
        """Rare, capped appreciation reward for repeat hosts, not per-match farming."""
        async with self.budget_lock:
            rec = self._host_record(guild_id, host_id)
            rec["completed"] = int(rec.get("completed", 0)) + 1
            bonus = 0
            if (rec["completed"] % 5 == 0
                    and int(rec.get("bonus", 0)) < 1500
                    and random.random() < 0.30):
                bonus = min(random.randint(250, 600), 1500 - int(rec.get("bonus", 0)))
                rec["bonus"] = int(rec.get("bonus", 0)) + bonus
            await self._save()
            return rec["completed"], bonus

    async def _log(self, guild_id: int, *, title: str, color: discord.Color = discord.Color.blurple(),
                    fields: list[tuple[str, str]] | None = None):
        """Post a Hangry Games event to this guild's dedicated log channel
        (set via /hangrygames logchannel), unless logging's been turned off."""
        if not self.log_enabled.get(guild_id, True):
            return
        channel_id = self.hg_log_channels.get(guild_id)
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return
        embed = discord.Embed(title=title, color=color, timestamp=datetime.datetime.now(datetime.timezone.utc))
        for name, value in (fields or []):
            embed.add_field(name=name, value=value, inline=True)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            log.warning(f"Failed to post Hangry Games log: {e}")

    async def recover_from_log(self, guild: discord.Guild, limit: int = 2000) -> tuple[int, int]:
        """Rebuild this guild's game count and win totals from its Hangry Games
        log channel's message history — used when the persisted store comes back
        empty for a guild that has a log channel configured. Best-effort, bounded
        by `limit` messages and Discord's own retention. Returns
        (reconstructed_game_count, wins_reconstructed)."""
        channel_id = self.hg_log_channels.get(guild.id)
        if channel_id is None:
            return (0, 0)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.HTTPException, discord.NotFound, discord.Forbidden) as exc:
                log.warning(f"Cannot access Hangry Games log channel {channel_id} for recovery: {type(exc).__name__}")
                return (0, 0)

        max_game_num = 0
        wins: list[int] = []  # winner_id per win found
        game_num_re = re.compile(r"Hangry Games #(\d+)")
        id_re = re.compile(r"\((\d+)\)\s*$")
        try:
            async for message in channel.history(limit=limit):
                for embed in message.embeds:
                    if not embed.title:
                        continue
                    m = game_num_re.search(embed.title)
                    if not m:
                        continue
                    max_game_num = max(max_game_num, int(m.group(1)))
                    if embed.title.startswith("🏆 Hangry Games"):
                        fields = {f.name: f.value for f in embed.fields}
                        wm = id_re.search(fields.get("Winner", ""))
                        if wm:
                            wins.append(int(wm.group(1)))
        except discord.HTTPException as e:
            log.error(f"Failed to scan Hangry Games log channel for recovery in guild {guild.id}: {e}")
            return (0, 0)

        if max_game_num:
            self.game_counts[guild.id] = max_game_num
        wins_by_member = defaultdict(int)
        for winner_id in wins:
            wins_by_member[winner_id] += 1
        for winner_id, recovered_total in wins_by_member.items():
            key = (guild.id, winner_id)
            self.win_counts[key] = max(self.win_counts.get(key, 0), recovered_total)
        if max_game_num or wins:
            await self._save()
        return (max_game_num, len(wins))

    async def launch(self, channel: discord.abc.Messageable, players: dict[int, discord.Member],
                      host: discord.Member, prize: str | None, winner_role: discord.Role | None = None,
                      *, catnip_prize: int = 0, sponsor: discord.Member | None = None):
        self.game_counts[channel.guild.id] = self.game_counts.get(channel.guild.id, 0) + 1
        game_num = self.game_counts[channel.guild.id]
        await self._save()
        sponsor = sponsor or host
        task = asyncio.create_task(self.run_game(channel, players, host, prize, game_num, winner_role,
                                                catnip_prize=catnip_prize, sponsor_id=sponsor.id,
                                                prize_week=self._week()))
        self.active[channel.id] = task

        fields = [
            ("Channel", channel.mention), ("Host", f"{host} ({host.id})"),
            ("Players", str(len(players))),
        ]
        if prize:
            fields.append(("Prize", prize))
        if winner_role:
            fields.append(("Winner role", winner_role.name))
        if catnip_prize:
            limit = self._budget_limit(sponsor)
            rec = self._budget_record(channel.guild.id, sponsor.id)
            remain = "Unlimited" if limit is None else f"{max(0, limit - rec['spent']):,}"
            fields.extend([("Catnip prize", f"{catnip_prize:,}"), ("Budget sponsor", f"{sponsor} ({sponsor.id})"),
                           ("Weekly budget left", remain), ("Budget week (UTC)", self._week())])
        await self._log(
            channel.guild.id, title=f"🐾 Hangry Games #{game_num} started", color=discord.Color.gold(),
            fields=fields,
        )

    async def run_game(self, channel: discord.abc.Messageable, players: dict[int, discord.Member],
                        host: discord.Member, prize: str | None, game_num: int,
                        winner_role: discord.Role | None = None, *, catnip_prize: int = 0,
                        sponsor_id: int | None = None, prize_week: str | None = None):
        alive = dict(players)
        kills: dict[int, int] = {pid: 0 for pid in alive}
        start = time.monotonic()
        rnd = 0
        completed = False
        try:
            await channel.send(f"🐾 **Hangry Games #{game_num}** begins with **{len(alive)}** cats in the arena, hosted by {host.mention}!")
            while len(alive) > 1:
                rnd += 1
                await asyncio.sleep(5)
                ids = list(alive.keys())
                embed = discord.Embed(color=0xFFB02E)
                embed.set_footer(text=f"Game #{game_num} · Round {rnd}")
                roll = random.random()

                if roll < 0.85:
                    p1_id, p2_id = random.sample(ids, 2)
                    p1, p2 = alive[p1_id], alive[p2_id]
                    content = f"{p1.mention} {p2.mention}"
                    embed.description = f"⚔️ {random.choice(HG_DUO_DEATHS).format(p1=p1.display_name, p2=p2.display_name)}"
                    embed.set_thumbnail(url=p1.display_avatar.url)
                    embed.set_image(url=p2.display_avatar.url)
                    kills[p2_id] = kills.get(p2_id, 0) + 1
                    del alive[p1_id]
                elif roll < 0.925:
                    p1_id = random.choice(ids)
                    p1 = alive[p1_id]
                    content = p1.mention
                    embed.title = "🐾 A cat-astrophe occurred! 🙀"
                    embed.description = f"👉 {random.choice(HG_SOLO_DEATHS).format(p1=p1.display_name)}"
                    embed.set_image(url=p1.display_avatar.url)
                    del alive[p1_id]
                else:
                    p1_id = random.choice(ids)
                    p1 = alive[p1_id]
                    content = p1.mention
                    embed.title = "🐾 A cat-astrophe occurred! 🙀"
                    embed.description = f"👉 {random.choice(HG_SURVIVALS).format(p1=p1.display_name)}"
                    embed.set_image(url=p1.display_avatar.url)

                if rnd % 5 == 0:
                    survivors = "\n".join(m.display_name for m in alive.values()) or "None"
                    embed.add_field(name="Survivors", value=survivors, inline=False)

                await channel.send(content=content, embed=embed)

            winner_id, winner = next(iter(alive.items())) if alive else (None, None)
            winner_kills = kills.get(winner_id, 0)
            elapsed = int(time.monotonic() - start)
            mm, ss = divmod(elapsed, 60)

            win_key = (channel.guild.id, winner_id)
            self.win_counts[win_key] = self.win_counts.get(win_key, 0) + 1
            total_wins = self.win_counts[win_key]
            for pid, k in kills.items():
                pkey = (channel.guild.id, pid)
                self.played_counts[pkey] = self.played_counts.get(pkey, 0) + 1
                if k:
                    self.kill_counts[pkey] = self.kill_counts.get(pkey, 0) + k
                try:
                    await achievement_record(channel.guild.id, pid, "hangry", 1, kills=k, win=1 if pid == winner_id else 0)
                    await quest_event(channel.guild.id, pid, "hangry", 1)
                except Exception:
                    log.exception("Achievement tracking failed for Hangry Games participant %s", pid)
            await self._save()
            if catnip_prize and winner_id is not None:
                economy_balances[(channel.guild.id, winner_id)] = (
                    economy_balance(channel.guild.id, winner_id) + catnip_prize
                )
                await bd_save_data()
                completed = True
                await self._log(channel.guild.id, title=f"💰 Hangry Games #{game_num} Catnip awarded",
                                fields=[("Winner", f"{winner} ({winner_id})"),
                                        ("Catnip", f"+{catnip_prize:,}"), ("Sponsor ID", str(sponsor_id))])
            elif not catnip_prize:
                completed = True
            runner_id = sponsor_id if sponsor_id is not None else host.id
            runner = channel.guild.get_member(runner_id) or host
            # Surprise games are Cinnamon-hosted; never credit the bot its own hosting bonus.
            if self.bot.user and runner_id == self.bot.user.id:
                finished_games, appreciation = 0, 0
            else:
                finished_games, appreciation = await self._host_completed(channel.guild.id, runner_id)
            if appreciation:
                economy_balances[(channel.guild.id, runner_id)] = economy_balance(channel.guild.id, runner_id) + appreciation
                await bd_save_data()
                await self._log(channel.guild.id, title="🐈 Cinnamon rewards a dedicated Hangry Games host",
                                fields=[("Runner", f"{runner} ({runner_id})"), ("Completed games this week", str(finished_games)),
                                        ("Surprise bonus", f"{appreciation:,} Catnip")])

            desc = f"🎉 **{winner.display_name}** won **{host.display_name}**'s Hangry Games"
            if prize:
                desc += f" and **{prize}**"
            desc += "!\n"
            desc += f"💀 **Total kills:** {winner_kills}\n"
            desc += f"⏱️ **Time survived:** {mm}m {ss}s\n"
            desc += f"🏆 **Total wins in server:** {total_wins}"
            if catnip_prize:
                desc += f"\n🌿 **Hangry Games Catnip prize:** {catnip_prize:,} awarded!"
            if appreciation:
                desc += f"\n🐈 Cinnamon awarded runner {runner.display_name} a {appreciation:,} Catnip thank-you!"

            if winner_role:
                try:
                    await winner.add_roles(winner_role, reason=f"Won Hangry Games #{game_num}")
                    desc += f"\n🎗️ **{winner.display_name}** was crowned with the **{winner_role.name}** role!"
                except discord.HTTPException:
                    pass

            winner_embed = discord.Embed(title="🏆 Winner!", color=0xFEE75C, description=desc)
            winner_embed.set_image(url=winner.display_avatar.url)
            winner_embed.set_footer(text=f"Game #{game_num}")
            rematch = HGRematchView(self, players, host)
            rematch.message = await channel.send(
                content=winner.mention, embed=winner_embed, view=rematch,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False),
            )
            try:
                await _cp_good_event(channel.guild, winner, "Hangry Games winner", points=2)
                await _cp_react(channel.guild, winner, channel, "hangry_win")
            except Exception:
                log.exception("Optional Cinnamon victory reaction failed")

            log_fields = [
                ("Channel", channel.mention), ("Host", f"{host} ({host.id})"),
                ("Winner", f"{winner} ({winner.id})"), ("Kills", str(winner_kills)),
                ("Time survived", f"{mm}m {ss}s"), ("Total wins (server)", str(total_wins)),
            ]
            if prize:
                log_fields.append(("Prize", prize))
            if winner_role:
                log_fields.append(("Winner role", winner_role.name))
            if catnip_prize:
                log_fields.extend([("Catnip prize paid", f"{catnip_prize:,}"),
                                   ("Sponsor ID", str(sponsor_id))])
            runner_budget = self.budget_records.get((channel.guild.id, runner_id), {})
            runner_limit = self._budget_limit(runner)
            runner_spent = int(runner_budget.get("spent", 0))
            runner_left = "Unlimited" if runner_limit is None else f"{max(0, runner_limit - runner_spent):,}"
            log_fields.extend([("Runner ID", str(runner_id)),
                               ("Prize budget spent this week", f"{runner_spent:,}"),
                               ("Weekly budget remaining", runner_left),
                               ("Runner games completed this week", str(finished_games)),
                               ("Host bonus Catnip", str(appreciation))])
            await self._log(
                channel.guild.id, title=f"🏆 Hangry Games #{game_num} ended", color=discord.Color.gold(),
                fields=log_fields,
            )
        except asyncio.CancelledError:
            await channel.send(
                f"🙀 *the arena collapses mid-brawl!* Hangry Games #{game_num} was cancelled — "
                f"no winner this time, you scaredy-cats."
            )
            await self._log(
                channel.guild.id, title=f"🚫 Hangry Games #{game_num} cancelled mid-game",
                color=discord.Color.red(),
                fields=[("Channel", channel.mention), ("Host", f"{host} ({host.id})"),
                        ("Players remaining", str(len(alive)))],
            )
        finally:
            if catnip_prize and not completed and sponsor_id is not None:
                await self._refund_budget(channel.guild.id, sponsor_id, catnip_prize, prize_week)
                await self._log(channel.guild.id, title=f"↩️ Hangry Games #{game_num} prize refunded",
                                fields=[("Sponsor ID", str(sponsor_id)), ("Amount", str(catnip_prize)),
                                        ("Reason", "No winner payout")])
            self.active.pop(channel.id, None)

    def _busy(self, channel_id: int) -> bool:
        return channel_id in self.active or channel_id in self.lobbies

    @app_commands.command(name="new", description="Start a Hangry Games lobby")
    @app_commands.describe(host="Who's hosting (defaults to you)",
                           catnip_prize="Optional Catnip award for the winner, funded by your weekly budget")
    @app_commands.guild_only()
    async def new(self, interaction: discord.Interaction, host: discord.Member = None,
                  catnip_prize: app_commands.Range[int, 0, 200000] = 0):
        if self._busy(interaction.channel.id):
            return await cinnamon_send(interaction, "A game's already running here!", ephemeral=True)
        if catnip_prize and not self._budget_limit(interaction.user) and self._budget_limit(interaction.user) is not None:
            return await cinnamon_send(interaction, "🐾 You need Manage Messages, Moderate Members, or Administrator to fund a Catnip prize.", ephemeral=True)
        view = HGLobbyView(self, host or interaction.user, catnip_prize=catnip_prize, sponsor=interaction.user)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()
        self.lobbies[interaction.channel.id] = view
        await self._log(interaction.guild.id, title="🐾 Hangry Games lobby created",
                        fields=[("Channel", interaction.channel.mention), ("Host", f"{view.host} ({view.host.id})"), ("Mode", "Normal")])

    @app_commands.command(name="giveaway", description="Run a Hangry Games giveaway")
    @app_commands.describe(prize="What the winner takes home (optional)", host="Who's hosting (defaults to you)",
                            winner_role="Role to give the winner (optional)",
                            catnip_prize="Winner Catnip paid from your weekly hosting budget")
    @app_commands.guild_only()
    async def giveaway(self, interaction: discord.Interaction, prize: str = None, host: discord.Member = None,
                        winner_role: discord.Role = None, catnip_prize: app_commands.Range[int, 0, 200000] = 0):
        if self._busy(interaction.channel.id):
            return await cinnamon_send(interaction, "A game's already running here!", ephemeral=True)
        if catnip_prize and self._budget_limit(interaction.user) == 0:
            return await cinnamon_send(interaction, "🐾 Need Manage Messages, Moderate Members or Administrator to sponsor Catnip.", ephemeral=True)
        view = HGLobbyView(self, host or interaction.user, prize=prize, winner_role=winner_role,
                           catnip_prize=catnip_prize, sponsor=interaction.user)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()
        self.lobbies[interaction.channel.id] = view
        await self._log(interaction.guild.id, title="🐾 Hangry Games giveaway lobby created",
                        fields=[("Channel", interaction.channel.mention), ("Host", f"{view.host} ({view.host.id})"),
                                ("Prize", str(prize)[:900] if prize else "None"),
                                ("Winner role", winner_role.name if winner_role else "None")])

    @app_commands.command(name="role", description="Auto-start a game with everyone who has a role")
    @app_commands.describe(role="The role to pull players from", prize="What the winner takes home (optional)",
                            host="Who's hosting (defaults to you)", winner_role="Role to give the winner (optional)",
                            catnip_prize="Winner Catnip paid from your weekly hosting budget")
    @app_commands.guild_only()
    async def role_cmd(self, interaction: discord.Interaction, role: discord.Role, prize: str = None,
                        host: discord.Member = None, winner_role: discord.Role = None,
                        catnip_prize: app_commands.Range[int, 0, 200000] = 0):
        if self._busy(interaction.channel.id):
            return await cinnamon_send(interaction, "A game's already running here!", ephemeral=True)
        players = {m.id: m for m in role.members if not m.bot}
        if len(players) < 2:
            return await cinnamon_send(interaction, 
                "Need at least 2 non-bot members with that role.", ephemeral=True
            )
        host = host or interaction.user
        error = await self._reserve_budget(interaction.guild, interaction.user, catnip_prize)
        if error:
            return await cinnamon_send(interaction, error, ephemeral=True)
        await cinnamon_send(interaction, 
            f"🐾 **{len(players)}** cats from **{role.name}** enter the arena, hosted by {host.mention}!",
            allowed_mentions=discord.AllowedMentions(roles=False),
        )
        await self._log(interaction.guild.id, title="🐾 Hangry Games role launch",
                        fields=[("Channel", interaction.channel.mention), ("Role", f"{role.name} ({role.id})"),
                                ("Players", str(len(players))), ("Host", f"{host} ({host.id})")])
        await self.launch(interaction.channel, players, host, prize, winner_role,
                          catnip_prize=catnip_prize, sponsor=interaction.user)

    @app_commands.command(name="budget", description="See your weekly Hangry Games prize budget and hosting stats")
    @app_commands.guild_only()
    async def budget(self, interaction: discord.Interaction):
        limit = self._budget_limit(interaction.user)
        rec = self._budget_record(interaction.guild.id, interaction.user.id)
        host = self._host_record(interaction.guild.id, interaction.user.id)
        remaining = ("Unlimited" if limit is None else f"{max(0, limit - int(rec.get('spent',0))):,}")
        allowance = "Unlimited" if limit is None else f"{limit:,}"
        embed = discord.Embed(title="🍔 Cinnamon's Hangry Games Budget", color=0xFFB02E)
        embed.add_field(name="Weekly allowance", value=f"{allowance} Catnip")
        embed.add_field(name="Used", value=f"{int(rec.get('spent',0)):,} Catnip")
        embed.add_field(name="Remaining", value=f"{remaining} Catnip")
        embed.add_field(name="Games completed this week", value=str(host.get("completed", 0)))
        embed.add_field(name="Host bonuses this week", value=f"{int(host.get('bonus',0)):,} Catnip")
        embed.set_footer(text=f"UTC week {self._week()} • budgets reset every Monday (UTC)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="Top Hangry Games winners in this server")
    @app_commands.guild_only()
    async def hg_leaderboard(self, interaction: discord.Interaction):
        gid = interaction.guild.id
        top = sorted(((m, w) for (g, m), w in self.win_counts.items() if g == gid), key=lambda e: e[1], reverse=True)[:10]
        if not top:
            return await cinnamon_send(interaction, "No Hangry Games winners yet. 🐾", ephemeral=True)
        lines = []
        for i, (uid, wins) in enumerate(top, 1):
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"
            kills = self.kill_counts.get((gid, uid), 0)
            lines.append(f"**#{i}** {name} — {wins} win(s), {kills} kill(s)")
        embed = discord.Embed(title="🏆 Hangry Games Leaderboard", description="\n".join(lines), color=0xFEE75C)
        await interaction.response.send_message(embed=cinnamon_polish_embed(embed), allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="stats", description="A member's Hangry Games stats")
    @app_commands.describe(member="Who to check (defaults to you)")
    @app_commands.guild_only()
    async def hg_stats(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        gid, key = interaction.guild.id, (interaction.guild.id, member.id)
        wins, kills = self.win_counts.get(key, 0), self.kill_counts.get(key, 0)
        played = self.played_counts.get(key, 0)
        ranked = sorted({m: w for (g, m), w in self.win_counts.items() if g == gid}.items(), key=lambda e: e[1], reverse=True)
        place = next((i for i, (m, _) in enumerate(ranked, 1) if m == member.id), None)
        embed = discord.Embed(title=f"🐾 {member.display_name}'s Hangry Games stats", color=0xFFB02E)
        embed.add_field(name="Wins", value=str(wins), inline=True)
        embed.add_field(name="Kills", value=str(kills), inline=True)
        embed.add_field(name="Games played", value=str(played) if played else "—", inline=True)
        embed.add_field(name="Win rate", value=f"{wins / played:.0%}" if played else "—", inline=True)
        embed.add_field(name="Server rank", value=f"#{place}" if place else "Unranked", inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Kills and games played count from completed games since stats tracking began.")
        await interaction.response.send_message(embed=cinnamon_polish_embed(embed), allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="cancel", description="Cancel the Hangry Games running in this channel")
    @app_commands.guild_only()
    async def cancel(self, interaction: discord.Interaction):
        task = self.active.pop(interaction.channel.id, None)
        if task:
            task.cancel()
            return await cinnamon_send(interaction, 
                "🐾 *pulls the emergency lever* Calling off the Hangry Games mid-fight!"
            )

        lobby = self.lobbies.pop(interaction.channel.id, None)
        if lobby:
            lobby.started = True  # blocks a stray Join/Start click racing the cancel
            for c in lobby.children:
                c.disabled = True
            lobby.stop()
            if lobby.message:
                try:
                    await lobby.message.edit(view=lobby)
                except discord.HTTPException:
                    pass
            await self._log(
                interaction.guild.id, title="🚫 Hangry Games lobby cancelled", color=discord.Color.red(),
                fields=[("Channel", interaction.channel.mention), ("Host", f"{lobby.host} ({lobby.host.id})"),
                        ("Cancelled by", f"{interaction.user} ({interaction.user.id})"),
                        ("Players signed up", str(len(lobby.players)))],
            )
            return await cinnamon_send(interaction, 
                "🐾 *knocks the lobby sign-up sheet off the table* The Hangry Games were cancelled before they even began!"
            )

        await cinnamon_send(interaction, "No game running here.", ephemeral=True)

    @app_commands.command(name="logchannel", description="Set (or reset) this channel as Hangry Games' dedicated log channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def hg_logchannel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        target = channel or interaction.channel
        guild_id = interaction.guild.id

        self.hg_log_channels[guild_id] = target.id
        self.log_enabled[guild_id] = True
        await secure_log_channel(target)

        # Fresh start: reset this server's game number back to 1 and wipe its win totals.
        self.game_counts.pop(guild_id, None)
        self.win_counts = {k: v for k, v in self.win_counts.items() if k[0] != guild_id}
        await self._save()

        await cinnamon_send(interaction, 
            f"🐾 Hangry Games will now log to {target.mention}. Game numbers and win totals for this "
            f"server have been reset — the next game will be **Game #1**.",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self._log(
            guild_id, title="🐾 Hangry Games log channel set", color=discord.Color.gold(),
            fields=[("Channel", target.mention), ("Set by", f"{interaction.user} ({interaction.user.id})")],
        )

    @app_commands.command(name="disablelogchannel", description="Stop Hangry Games from posting logs anywhere in this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def hg_disablelogchannel(self, interaction: discord.Interaction):
        removed = self.hg_log_channels.pop(interaction.guild.id, None)
        self.log_enabled.pop(interaction.guild.id, None)
        await self._save()
        if removed is None:
            return await cinnamon_send(interaction, "No Hangry Games log channel was set.", ephemeral=True)
        await cinnamon_send(interaction, "🐾 Hangry Games log channel disabled. Game numbers and win totals are unaffected.")

    @app_commands.command(name="log", description="Turn Hangry Games activity logging on/off without changing the channel")
    @app_commands.describe(enabled="On: log game starts, winners, and cancellations to the log channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def log_toggle(self, interaction: discord.Interaction, enabled: bool):
        if interaction.guild.id not in self.hg_log_channels:
            return await cinnamon_send(interaction, 
                "Set a Hangry Games log channel first with `/hangrygames logchannel`, then toggle this.",
                ephemeral=True,
            )
        self.log_enabled[interaction.guild.id] = enabled
        await self._save()
        state = "on" if enabled else "off"
        await cinnamon_send(interaction, f"🐾 Hangry Games logging turned **{state}**.", ephemeral=True)


