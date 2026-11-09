"""A real timed fishing mini-game, loaded after Wildlands fishing.
Shared globals deliberately come from main.py's modular loader.
"""
import asyncio as _fg_asyncio
import time as _fg_time

_FG_STARTED = _fg_time.time()
_FG_LOCKS = {}
_FG_HOOK_WINDOW = 12
_FG_TURN_WINDOW = 25
_FG_MOVES = (
    ("dives straight down", "give"),
    ("swims closer and the line falls slack", "reel"),
    ("thrashes violently sideways", "steady"),
)


def _fg_move(tension, progress, move, action):
    """Pure deterministic action consequences, for repeatable tests."""
    effects = (
        {"give": (-20, 1), "steady": (10, 1), "reel": (37, 1)},
        {"give": (-29, 0), "steady": (-10, 1), "reel": (19, 2)},
        {"give": (-12, 1), "steady": (-17, 2), "reel": (32, 1)},
    )
    delta, points = effects[move][action]
    return int(tension) + delta, int(progress) + points


class _FGView(discord.ui.View):
    """Prepare, cast, wait for bite, hook, then make several fishing decisions."""

    def __init__(self, guild_id, user_id):
        super().__init__(timeout=180)
        self.gid, self.uid = guild_id, user_id
        self.phase = 'prepare'
        self.bait = None
        self.session_id = None
        self.message = None
        self.configure()

    def lock(self):
        return _FG_LOCKS.setdefault((self.gid, self.uid), _fg_asyncio.Lock())

    def player(self):
        return _wlf_player(self.gid, self.uid)

    def session(self):
        state = self.player().get('fishing_session')
        return state if state and state.get('id') == self.session_id else None

    async def interaction_check(self, interaction):
        if not interaction.guild or interaction.guild.id != self.gid or interaction.user.id != self.uid:
            await interaction.response.send_message(
                '🐈 This rod belongs to a different adventurer. Start your own fishing game.', ephemeral=True)
            return False
        return True

    def configure(self):
        self.clear_items()
        if self.phase == 'prepare':
            baits = [b for b in _WLF_BAIT if int(self.player()['bait'].get(b['id'], 0)) > 0]
            if not baits:
                return
            if self.bait not in [b['id'] for b in baits]:
                self.bait = baits[0]['id']
            select = discord.ui.Select(placeholder='Choose fishing bait',
                options=[discord.SelectOption(label=b['name'], value=b['id'],
                    description=f"{self.player()['bait'][b['id']]} in bag; luck +{b['bonus']}",
                    default=self.bait == b['id']) for b in baits])
            async def choose(interaction):
                self.bait = select.values[0]
                self.configure()
                await interaction.response.edit_message(embed=self.render(), view=self)
            select.callback = choose
            self.add_item(select)
            button = discord.ui.Button(label='Cast the line', emoji='🎣',
                                       style=discord.ButtonStyle.success, row=1)
            button.callback = self.cast
            self.add_item(button)
        elif self.phase == 'bite':
            button = discord.ui.Button(label='HOOK IT!', emoji='⚡',
                                       style=discord.ButtonStyle.danger)
            button.callback = self.hook
            self.add_item(button)
        elif self.phase == 'fight':
            for name, emoji, action in (
                ('Give line', '↩️', 'give'),
                ('Hold steady', '🎣', 'steady'),
                ('Reel hard', '⚡', 'reel'),
            ):
                button = discord.ui.Button(label=name, emoji=emoji,
                                           style=discord.ButtonStyle.primary)
                async def act(interaction, chosen=action):
                    await self.fight(interaction, chosen)
                button.callback = act
                self.add_item(button)

    def render(self):
        p = self.player()
        if self.phase == 'prepare':
            rod = next((r for r in _WLF_RODS if r['id'] == p['rod']), _WLF_RODS[0])
            bait = next((b for b in _WLF_BAIT if b['id'] == self.bait), _WLF_BAIT[0])
            return _wlf_embed('🎣 Prepare your cast',
                f"**Water:** {_wlf_area(p['area'])[1]}\n"
                f"**Rod:** {rod['name']}\n"
                f"**Bait:** {bait['name']} × {p['bait'].get(self.bait, 0)}\n"
                f"**Cinnamon:** {_cm_tier(self.gid).title()}\n\n"
                "Choose your bait, cast into the water, wait 10–20 seconds, "
                "then hook and reel in the fish. Your actions affect success!")
        state = self.session() or {}
        if self.phase == 'waiting':
            return _wlf_embed('🌊 The bobber is floating...',
                "Your fishing line lands with a tiny plop.\n"
                "Cinnamon watches intently. \"NOBODY MOVE.\"\n\n"
                "🐟 Waiting **10–20 seconds** for something to bite...")
        if self.phase == 'bite':
            return _wlf_embed('❗ SOMETHING BITES!',
                "The rod JERKS! Cinnamon's eyes widen.\n"
                "\"THAT IS NOT A LEAF! HOOK IT!\"\n\n"
                f"Press **HOOK IT** within {_FG_HOOK_WINDOW} seconds!")
        if self.phase == 'fight':
            move = state['moves'][state['turn']]
            tension = max(0, min(100, int(state['tension'])))
            line_status = ('⚠️ Critical' if tension <= 20 or tension >= 80
                           else 'Stable' if 35 <= tension <= 65 else 'Unsteady')
            return _wlf_embed('🐟 Fish on the line!',
                f"**Fish movement**\n{_FG_MOVES[move][0].capitalize()}.\n\n"
                f"**Line tension**  ·  {line_status}\n"
                f"{cinnamon_ui_progress(tension, 100, 10)}\n\n"
                f"**Catch progress**\n"
                f"{cinnamon_ui_progress(state['progress'], state['goal'], 10)}\n\n"
                f"**Choose your move**  ·  {_FG_TURN_WINDOW}s to respond\n"
                "Give line, hold steady, or reel hard. Extreme tension breaks the line; "
                "too little lets the fish escape.")
        return _wlf_embed('🎣 Fishing is over', 'Cast again for another fish.')

    async def cast(self, interaction):
        await interaction.response.defer()
        async with self.lock():
            p = self.player()
            if self.phase != 'prepare' or p.get('fishing_session'):
                return await interaction.edit_original_response(
                    content='🐟 A cast is already in progress.', view=None)
            if int(p['bait'].get(self.bait, 0)) < 1:
                self.configure()
                return await interaction.edit_original_response(embed=self.render(), view=self)
            rod = next((r for r in _WLF_RODS if r['id'] == p['rod']), _WLF_RODS[0])
            bait = next(b for b in _WLF_BAIT if b['id'] == self.bait)
            rarity = _wlf_roll(rod['bonus'] + bait['bonus'] + _cm_fishing_bonus(self.gid))
            delay = _wlf_random.randint(10, 20)
            now = _fg_time.time()
            self.session_id = f'{self.gid}-{self.uid}-{_fg_time.time_ns()}'
            p['bait'][self.bait] -= 1
            p['fishing_session'] = {
                'id': self.session_id, 'phase': 'waiting', 'bait': self.bait,
                'area': p['area'], 'fish': f'{p["area"]}:{rarity}', 'cast_at': now,
                'tension': 48, 'progress': 0, 'turn': 0, 'moves': [], 'goal': 0,
            }
            self.phase = 'waiting'
            self.configure()
            await bd_save_data()
        await interaction.edit_original_response(embed=self.render(), view=self)
        _fg_asyncio.create_task(self.bite_after(delay))

    async def bite_after(self, seconds):
        await _fg_asyncio.sleep(seconds)
        async with self.lock():
            state = self.session()
            if not state or state['phase'] != 'waiting':
                return
            state['phase'] = self.phase = 'bite'
            self.configure()
            await bd_save_data()
        if self.message:
            try:
                await self.message.edit(embed=self.render(), view=self)
            except discord.HTTPException:
                log.exception('Could not update fishing bite')
        _fg_asyncio.create_task(self.deadline('bite', 0, _FG_HOOK_WINDOW))

    async def hook(self, interaction):
        await interaction.response.defer()
        async with self.lock():
            state = self.session()
            if not state or state['phase'] != 'bite':
                return await interaction.edit_original_response(
                    content='🐟 You missed the bite! Try another cast.', view=None)
            rarity = _WLF_FISH[state['fish']]['rarity']
            rounds = 4 if rarity in ('Legendary', 'Mythical') else 3 if rarity in ('Rare', 'Epic') else 2
            state['goal'] = rounds + 1
            state['moves'] = [_wlf_random.randrange(3) for _ in range(rounds + 2)]
            state['phase'] = self.phase = 'fight'
            self.configure()
            await bd_save_data()
        await interaction.edit_original_response(embed=self.render(), view=self)
        _fg_asyncio.create_task(self.deadline('fight', 0, _FG_TURN_WINDOW))

    async def deadline(self, phase, turn, seconds):
        await _fg_asyncio.sleep(seconds)
        async with self.lock():
            state = self.session()
            if not state or state['phase'] != phase or int(state['turn']) != turn:
                return
            self.player()['fishing_session'] = None
            self.phase = 'lost'
            self.clear_items()
            await bd_save_data()
        if self.message:
            try:
                await self.message.edit(embed=_wlf_embed('💨 The fish got away!',
                    'Your fishing line went still. Cinnamon stares at the water.\n'
                    '"THE FISH SAW YOU HESITATE. UNBELIEVABLE."'), view=None)
            except discord.HTTPException:
                pass
        self.stop()

    async def fight(self, interaction, action):
        await interaction.response.defer()
        catch = None
        async with self.lock():
            state = self.session()
            if not state or state['phase'] != 'fight':
                return await interaction.edit_original_response(
                    content='🐟 That fishing battle has ended.', view=None)
            move = state['moves'][state['turn']]
            state['tension'], state['progress'] = _fg_move(
                state['tension'], state['progress'], move, action)
            state['turn'] += 1
            if state['tension'] <= 8 or state['tension'] >= 90 or state['turn'] >= len(state['moves']):
                self.phase = 'lost'
            elif state['progress'] >= state['goal']:
                self.phase = 'caught'
                catch = state['fish']
            if self.phase != 'fight':
                self.player()['fishing_session'] = None
                if not catch and state['tension'] >= 90:
                    self.player()['rod_broken'] = True
                self.clear_items()
                if catch:
                    p = self.player()
                    p['fish'][catch] = int(p['fish'].get(catch, 0)) + 1
                    if catch not in p['seen']:
                        p['seen'].append(catch)
            else:
                state['phase'] = 'fight'
            await bd_save_data()
            next_turn = state['turn']
        if self.phase == 'fight':
            await interaction.edit_original_response(embed=self.render(), view=self)
            _fg_asyncio.create_task(self.deadline('fight', next_turn, _FG_TURN_WINDOW))
            return
        self.stop()
        if not catch:
            return await interaction.edit_original_response(
                embed=_wlf_embed('💨 The fish escaped!',
                    'Your line snapped or fell slack. Cinnamon stamps her paw.\n'
                    '"READ HOW IT MOVES NEXT TIME!"'), view=None)
        fish = _WLF_FISH[catch]
        p = self.player()
        bonus = await _wlf_award_rare_role(interaction, fish)
        await interaction.edit_original_response(embed=_wlf_embed('🏆 Fish landed!',
            f"🐟 **{fish['name']}**\n**Rarity:** {fish['rarity']}\n"
            f"**Value:** {fish['value']:,} Catnip\n"
            f"**Owned:** {p['fish'][catch]}\n"
            f"**Region:** {_wlf_area(fish['area'])[1]}\n"
            "Cinnamon yells: WE ACTUALLY DID IT!\n"
            + ('📓 NEW SPECIES!\n' if p['fish'][catch] == 1 else '') + bonus), view=None)
        if fish['rarity'] in ('Legendary', 'Mythical'):
            try:
                await _cp_good_event(interaction.guild, interaction.user, 'Rare Wildlands fish caught', points=2)
                await _cp_react(interaction.guild, interaction.user, interaction.channel,
                                'rare_fish', detail=fish['name'])
            except Exception:
                log.exception('Optional fishing rare reaction failed')

    async def on_timeout(self):
        async with self.lock():
            state = self.session()
            if state:
                p = self.player()
                if state['phase'] == 'waiting':
                    p['bait'][state['bait']] = int(p['bait'].get(state['bait'], 0)) + 1
                p['fishing_session'] = None
                await bd_save_data()
        self.stop()


# The deprecated cosmetic fishing_cast helper is deliberately not registered;
# this is the only slash command with the name /fishing cast.
@_wlf_group.command(name='cast', description='Cast, wait for a bite, hook and fight your fish')
@app_commands.guild_only()
async def fishing_cast_game(interaction: discord.Interaction):
    gid, uid = interaction.guild.id, interaction.user.id
    p = _wlf_player(gid, uid)
    now = _fg_time.time()
    old = p.get('fishing_session')
    if old:
        if float(old.get('cast_at', 0)) < _FG_STARTED or now - float(old.get('cast_at', 0)) > 180:
            # A Render restart destroys ephemeral views. Refund bait only if
            # the fish had not yet bitten when the process stopped.
            if old.get('phase') == 'waiting' and old.get('bait') in p['bait']:
                b = old['bait']
                p['bait'][b] = int(p['bait'][b]) + 1
            p['fishing_session'] = None
            await bd_save_data()
        else:
            return await interaction.response.send_message(
                '🐟 You already have a fishing line in the water. Finish that panel first.',
                ephemeral=True)
    if p['area'] not in p['areas']:
        p['area'] = 'whispering_woods'
    if not any(int(p['bait'].get(b['id'], 0)) > 0 for b in _WLF_BAIT):
        return await interaction.response.send_message(
            '🐟 You need bait first. Visit the Fishing Bait Merchant or use `/fishing buy-bait`.',
            ephemeral=True)
    view = _FGView(gid, uid)
    await interaction.response.send_message(embed=view.render(), view=view, ephemeral=True)
    view.message = await interaction.original_response()
