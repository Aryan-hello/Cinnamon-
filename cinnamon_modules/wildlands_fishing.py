"""Cinnamon Wildlands fishing gameplay.

Loaded by main.py into the same namespace as Cinnamon's economy and storage.
No second bot, database, or slash-command tree. Wildlands state is serialized
inside advanced_features_data by the existing bd_save_data implementation.
"""
import random as _wlf_random
import time as _wlf_time
import math as _wlf_math

_WLF_AREAS = (
    ('whispering_woods', 'Whispering Woods', 'Woodland Fishing Pier', 'woodland_fishing_pier'),
    ('quiet_shore', 'Quiet Shore', 'Sunlit Fishing Shore', None),
    ('stoneback_highlands', 'Stoneback Highlands', 'Highland Riverbend', None),
    ('moonlit_marsh', 'Moonlit Marsh', 'Moonlit Fishing Pool', 'moonlit_fishing_pool'),
    ('frostfall_pass', 'Frostfall Pass', 'Frostfall Fishing Spot', 'frostfall_fishing_spot'),
    ('forgotten_ruins', 'Forgotten Ruins', 'Ruins Fishing Pool', 'ruins_fishing_pool'),
)
_WLF_RARITIES = ('Common', 'Uncommon', 'Rare', 'Epic', 'Legendary', 'Mythical')
_WLF_CHANCES = (54, 25, 12, 6, 2.5, .5)
_WLF_FISH_NAMES = (
    ('Moss Minnow', 'Fern Perch', 'Willow Trout', 'Bramble Koi', 'Aurora Salmon', 'Forest Spirit Koi'),
    ('Sand Darter', 'Coral Carp', 'Pearl Snapper', 'Tidecrest Ray', 'Crown Tuna', 'Celestial Whale'),
    ('Stone Loach', 'Mountain Sprat', 'Silverfin Pike', 'Cliffscale Bass', 'Sunspire Sturgeon', 'Abyssal Dragonfish'),
    ('Mist Guppy', 'Lunar Eel', 'Glowfin Tetra', 'Marsh Phantom', 'Starlight Jellyfish', 'Moonveil Leviathan'),
    ('Frost Smelt', 'Snowtail Trout', 'Iceglass Char', 'Glacier Koi', 'Winterking Salmon', 'Polar Phoenixfish'),
    ('Relic Minnow', 'Mosaic Bream', 'Ancient Gar', 'Runeshell Catfish', 'Golden Ruins Arowana', "Cinnamon's Golden Fish"),
)
_WLF_VALUES = {'Common': 35, 'Uncommon': 75, 'Rare': 150, 'Epic': 400, 'Legendary': 1500, 'Mythical': 5000}
_WLF_COLOR = 0xD89138
_WLF_RODS = (
    {'id':'twig','name':'Woodland Rod','price':0,'bonus':0,'description':'A sturdy first rod. Every explorer starts with one.'},
    {'id':'silver','name':'Silverstream Rod','price':1250,'bonus':1.8,'description':'Improves the odds of uncommon and rarer catches.'},
    {'id':'starlit','name':'Starlit Rod','price':5500,'bonus':4.5,'description':'An enchanted rod that favors rare catches.'},
)
_WLF_BAIT = (
    {'id':'normal','name':'Normal Bait','price':10,'bonus':0,'description':'Basic bait. 10 cost 100 Catnip.'},
    {'id':'glow','name':'Glowworm Bait','price':35,'bonus':1.4,'description':'Specialist bait for rare catches.'},
    {'id':'tide','name':'Tide Pearl Bait','price':55,'bonus':2.0,'description':'Specialist bait favored by powerful fish.'},
    {'id':'moon','name':'Moonblossom Bait','price':85,'bonus':2.8,'description':'Premium bait with the highest rarity boost.'},
)
_WLF_MERCHANTS = {'rod':'Fishing Rod Merchant','bait':'Fishing Bait Merchant'}
_WLF_TREASURE_ROLE = 'Wildlands • Treasure Hunter'
_WLF_SHOP_SECONDS = 2 * 60 * 60
_WLF_PURCHASE_LOCKS = {}
_WLF_SHOP_NAMES = {'rod': 'fishing-rod-merchant', 'bait': 'fishing-bait-merchant'}
_WLF_FISH = {}
for _wlf_idx, _wlf_area in enumerate(_WLF_AREAS):
    for _wlf_ri, _wlf_fish_name in enumerate(_WLF_FISH_NAMES[_wlf_idx]):
        _wlf_key = f'{_wlf_area[0]}:{_wlf_ri}'
        _WLF_FISH[_wlf_key] = {
            'name':_wlf_fish_name,'rarity':_WLF_RARITIES[_wlf_ri],
            'area':_wlf_area[0], 'value':_WLF_VALUES[_WLF_RARITIES[_wlf_ri]],
            'role_name':(f'{_WLF_RARITIES[_wlf_ri]} Fish • {_wlf_fish_name}' if _wlf_ri >= 4 else None),
        }


def _wlf_required_roles():
    """All role names /setup should create, no duplicates on re-runs."""
    return list(_WLF_MERCHANTS.values()) + [_WLF_TREASURE_ROLE] + [f['role_name'] for f in _WLF_FISH.values() if f['role_name']]


def _wlf_root():
    # This dict is the same object as advanced_features_data, kept in place
    # by dashboard_runtime._bd_decode; it is included in existing snapshots.
    root = advanced_features_data.setdefault('wildlands_fishing_v1', {})
    return root


def _wlf_server(guild_id):
    s = _wlf_root().setdefault(str(guild_id), {})
    s.setdefault('merchants', {'rod':False,'bait':False})
    s.setdefault('members', {})
    return s


def _wlf_player(guild_id, user_id):
    p = _wlf_server(guild_id)['members'].setdefault(str(user_id), {})
    p.setdefault('areas', ['whispering_woods'])
    p.setdefault('area', 'whispering_woods')
    p.setdefault('rod', 'twig')
    p.setdefault('rods', ['twig'])
    p.setdefault('bait', {'normal': 10})
    p.setdefault('fish', {})
    p.setdefault('seen', [])
    p.setdefault('next_gather', 0)
    p.setdefault('next_cast', 0)
    return p


def _wlf_area(area_id):
    return next((a for a in _WLF_AREAS if a[0] == area_id), _WLF_AREAS[0])


def _wlf_embed(title, description='', *, interaction=None):
    e = discord.Embed(title=title, description=description, color=_WLF_COLOR)
    if interaction is not None:
        e.set_footer(text=f'Cinnamon Wildlands • {interaction.guild.name}')
    return e


def _wlf_story_complete(guild_id, user_id):
    return bool(advanced_features_data.get('wildlands_story_v2', {}).get(str(guild_id), {}).get(str(user_id), {}).get('complete'))


def _wlf_window(guild_id, kind):
    return _wlf_server(guild_id).setdefault('merchant_windows', {}).get(kind, {})


def _wlf_active(guild_id, kind):
    return float(_wlf_window(guild_id, kind).get('ends_at', 0)) > _wlf_time.time()


def _wlf_merchant_open(guild_id, kind, user_id=None):
    return _wlf_active(guild_id, kind) or (user_id is not None and _wlf_story_complete(guild_id, user_id))


def _wlf_channel(guild, kind):
    raw = _wlf_window(guild.id, kind)
    saved_id = raw.get('channel_id')
    ch = guild.get_channel(int(saved_id)) if saved_id else None
    return ch or discord.utils.get(guild.text_channels, name=_WLF_SHOP_NAMES[kind])


async def _wlf_ensure_role(guild, name):
    role = discord.utils.get(guild.roles, name=name)
    if role:
        return role
    if not (guild.me and guild.me.guild_permissions.manage_roles):
        raise PermissionError('Cinnamon needs Manage Roles to create merchant and treasure roles.')
    return await guild.create_role(name=name, reason='Cinnamon Wildlands shop access')


async def _wlf_refresh_channel(guild, kind):
    """Create once, then alter @everyone visibility according to the current timer.

    Finished-story role is permanently allowed to see it, regardless of the window.
    """
    if not (guild.me and guild.me.guild_permissions.manage_channels):
        raise PermissionError('Cinnamon needs Manage Channels to open merchant shops.')
    treasure = await _wlf_ensure_role(guild, _WLF_TREASURE_ROLE)
    channel = _wlf_channel(guild, kind)
    if channel is None:
        channel = await guild.create_text_channel(
            _WLF_SHOP_NAMES[kind],
            topic='Cinnamon Wildlands: temporary server-wide merchant, permanent for story finishers.',
            overwrites={guild.default_role: discord.PermissionOverwrite(view_channel=False),
                        treasure: discord.PermissionOverwrite(view_channel=True, send_messages=True)},
            reason='Cinnamon merchant discovered')
    live = _wlf_active(guild.id, kind)
    everyone = channel.overwrites_for(guild.default_role)
    if everyone.view_channel is not live:
        everyone.view_channel = live
        await channel.set_permissions(guild.default_role, overwrite=everyone, reason='Wildlands merchant timed access')
    always = channel.overwrites_for(treasure)
    if always.view_channel is not True:
        always.view_channel = True
        always.send_messages = True
        await channel.set_permissions(treasure, overwrite=always, reason='Permanent access for treasure hunters')
    _wlf_window(guild.id, kind)['channel_id'] = channel.id
    return channel


async def _wlf_award_story_access(interaction):
    guild, member = interaction.guild, interaction.user
    problem = []
    try:
        role = await _wlf_ensure_role(guild, _WLF_TREASURE_ROLE)
        if role not in member.roles:
            if role >= guild.me.top_role:
                raise PermissionError('Place Cinnamon’s role above Wildlands • Treasure Hunter.')
            await member.add_roles(role, reason='Completed Cinnamon Wildlands treasure story')
    except (discord.HTTPException, PermissionError, AttributeError) as exc:
        problem.append(str(exc))
    for kind in _WLF_MERCHANTS:
        try:
            channel = await _wlf_refresh_channel(guild, kind)
            if not (discord.utils.get(member.roles, name=_WLF_TREASURE_ROLE)):
                await channel.set_permissions(member, view_channel=True, reason='Wildlands story completion fallback access')
        except (discord.HTTPException, PermissionError, AttributeError) as exc:
            problem.append(f'{kind}: {exc}')
    if problem:
        return '\n⚠️ Your story completion was saved, but Cinnamon could not set all Discord shop permissions. Ask an admin to check Manage Roles / Manage Channels: ' + '; '.join(problem)[:450]
    return '\n🏅 You now have **permanent access** to both merchant channels!'


class _WLFShopPanel(discord.ui.View):
    def __init__(self, kind):
        super().__init__(timeout=None)
        self.kind = kind
        button = discord.ui.Button(label='Browse & buy ' + ('rods' if kind == 'rod' else 'bait'),
                                   style=discord.ButtonStyle.success,
                                   custom_id=f'cinnamon:wildlands:merchant:{kind}:shop')
        button.callback = self.shop
        self.add_item(button)

    async def shop(self, interaction):
        if not interaction.guild or not _wlf_merchant_open(interaction.guild.id, self.kind, interaction.user.id):
            return await interaction.response.send_message('🐈 This shop is closed! Find the merchant again, or finish the story for permanent access.', ephemeral=True)
        view = _WLFCatalog(interaction.user.id, 'rod' if self.kind == 'rod' else 'bait', interaction.guild.id)
        await interaction.response.send_message(embed=view.render(), view=view, ephemeral=True)


async def _wlf_purchase(interaction, kind, item, quantity=1):
    """One purchase path for slash commands, catalog buttons, and shop buttons.

    10% of a sale is newly credited to the discoverer ONLY when bought from
    that merchant's channel while its two-hour window is active.
    """
    if not interaction.guild:
        return 'Use this in a server.'
    g, u = interaction.guild.id, interaction.user.id
    lock = _WLF_PURCHASE_LOCKS.setdefault(g, asyncio.Lock())
    async with lock:
        p = _wlf_player(g, u)
        if kind == 'rod':
            if item['id'] in p['rods']:
                p['rod'] = item['id']
                await bd_save_data()
                return f'🎣 Equipped **{item["name"]}** (already owned).'
            if not _wlf_merchant_open(g, kind, u):
                return '🔒 Find the Rod Merchant, or complete the Wildlands story for permanent shop access.'
            quantity = 1
        elif item['id'] != 'normal' and not _wlf_merchant_open(g, kind, u):
            return '🔒 Find the Bait Merchant, or finish the story for permanent shop access.'
        cost = _cm_price(g, u, item['id'], item['price']) * quantity
        balance = economy_balance(g, u)
        if balance < cost:
            return f'🌿 **{item["name"]}** costs {cost:,} Catnip; you have {balance:,}.'
        window = _wlf_window(g, kind)
        finder = int(window.get('finder_id', 0) or 0)
        shop_channel = _wlf_channel(interaction.guild, kind)
        eligible = (cost > 0 and _wlf_active(g,kind) and finder > 0
                    and finder != u and shop_channel is not None
                    and interaction.channel_id == shop_channel.id)
        commission = cost // 10 if eligible else 0
        economy_balances[(g,u)] = balance - cost
        if kind == 'rod':
            p['rods'].append(item['id'])
            p['rod'] = item['id']
        else:
            p['bait'][item['id']] = int(p['bait'].get(item['id'],0)) + quantity
        if commission:
            economy_balances[(g,finder)] = economy_balance(g,finder) + commission
        await bd_save_data()
        try:
            await economy_log(g, title='🛒 Wildlands merchant purchase', fields=[
                ('Member ID', u), ('Item', item['name']), ('Quantity', quantity),
                ('Cost', cost), ('Balance after', economy_balances[(g,u)]),
                ('Finder commission recipient', finder if commission else 'None'),
                ('Finder bonus Catnip', commission)])
        except Exception:
            log.exception('Wildlands merchant sale saved but economy log failed')
        text = f'✅ Purchased **{quantity} × {item["name"]}** for **{cost:,} Catnip**.'
        if commission:
            text += f' 🐾 The shop discoverer earned **{commission:,} Catnip** (10% bonus).'
        return text


def _wlf_npc_role(guild, name):
    return discord.utils.get(guild.roles, name=name)


async def _wlf_award_rare_role(interaction, fish):
    name = fish.get('role_name')
    if not name:
        return ''
    guild = interaction.guild
    role = _wlf_npc_role(guild, name)
    member = interaction.user
    if role is None:
        return f'\n⚠️ Role **{name}** missing. Ask an admin to run `/setup`.'
    if not getattr(guild.me.guild_permissions, 'manage_roles', False):
        return '\n⚠️ Catch recorded, but Cinnamon needs **Manage Roles** to award its title.'
    if role in member.roles:
        return ''
    if role >= guild.me.top_role:
        return '\n⚠️ Catch recorded, but move Cinnamon’s role above the fish title.'
    try:
        await member.add_roles(role, reason='Cinnamon Wildlands fish catch')
        return f'\n🏅 New title unlocked: {role.mention}!'
    except discord.HTTPException:
        log.exception('Could not award Wildlands fish title %s', name)
        return f'\n⚠️ Could not assign **{name}** yet. Catch saved.'


def _wlf_roll(rarity_bonus):
    # Weighted rare uplift without allowing chance weights to go negative.
    weights = list(_WLF_CHANCES)
    bonus = min(5, max(-1.5, float(rarity_bonus)))
    shift = bonus * 3.0
    weights[0] -= shift
    weights[2] += shift * .25
    weights[3] += shift * .33
    weights[4] += shift * .29
    weights[5] += shift * .13
    return _wlf_random.choices(range(6), weights=weights, k=1)[0]


async def _wlf_attempt_merchant(guild, *, finder=None, announce_channel=None, chance=.12):
    """A discovery opens a two-hour server-wide shop; re-discovery after expiry
    rotates the commission beneficiary. Failures leave the shop locked.
    """
    if finder is None:
        return ''
    options = [kind for kind in _WLF_MERCHANTS if not _wlf_active(guild.id, kind)]
    if not options or _wlf_random.random() >= chance:
        return ''
    kind = _wlf_random.choice(options)
    now = _wlf_time.time()
    window = _wlf_server(guild.id).setdefault('merchant_windows', {}).setdefault(kind, {})
    old = dict(window)
    window.update({'finder_id': finder.id, 'ends_at': now + _WLF_SHOP_SECONDS, 'started_at': now, 'closed_notice': False})
    try:
        role = await _wlf_ensure_role(guild, _WLF_MERCHANTS[kind])
        ch = await _wlf_refresh_channel(guild, kind)
        await bd_save_data()
        mention = role.mention if role else _WLF_MERCHANTS[kind]
        await ch.send(f'🐈 **CINNAMON NEWS!** {mention} has been discovered by {finder.mention}! '
                      f'The shop is open for **2 hours** to the entire server. '
                      f'Use the button below to shop. The finder earns **10% of purchases made '
                      f'by other people in this channel** before closing.',
                      view=_WLFShopPanel(kind),
                      allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False))
        if announce_channel and announce_channel.id != ch.id:
            try:
                await announce_channel.send(f'📣 **Cinnamon announces a discovery!** {finder.mention} found '
                    f'**{_WLF_MERCHANTS[kind]}**! The entire server can visit {ch.mention} for **2 hours**. '
                    'The finder earns **10%** of other customers’ purchases in that channel!',
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
            except discord.HTTPException:
                pass
        return f'\n🏪 **SERVER-WIDE DISCOVERY!** Visit {ch.mention}. You receive 10% of other players’ purchases in that shop for **2 hours**!'
    except (discord.HTTPException, PermissionError, AttributeError) as exc:
        window.clear()
        window.update(old)
        try:
            await _wlf_refresh_channel(guild, kind)  # Undo public access if announcing failed.
        except (discord.HTTPException, PermissionError):
            pass
        log.warning('Wildlands merchant discovery could not open shop: %s', exc)
        return f'\n⚠️ Merchant sighted, but Cinnamon cannot open the shop: {str(exc)[:150]}. An admin should check Manage Channels / Manage Roles.'


@bot.listen('on_ready')
async def _wlf_shop_ready():
    if not getattr(bot, '_wlf_persistent_views_added', False):
        for kind in _WLF_MERCHANTS:
            bot.add_view(_WLFShopPanel(kind))
        bot._wlf_persistent_views_added = True
    if not getattr(bot, '_wlf_shop_reaper_running', False):
        bot._wlf_shop_reaper_running = True
        asyncio.create_task(_wlf_expire_shops())
    # Restore visibility at startup; a timed window may have expired while offline.
    for guild in bot.guilds:
        for kind in _WLF_MERCHANTS:
            if _wlf_channel(guild, kind):
                try:
                    await _wlf_refresh_channel(guild, kind)
                except (discord.HTTPException, PermissionError) as exc:
                    log.warning('Wildlands shop restore failed (%s/%s): %s', guild.id, kind, exc)


async def _wlf_expire_shops():
    try:
        while not bot.is_closed():
            for guild in bot.guilds:
                for kind in _WLF_MERCHANTS:
                    rec = _wlf_window(guild.id, kind)
                    expires = float(rec.get('ends_at', 0))
                    if expires and expires <= _wlf_time.time() and not rec.get('closed_notice'):
                        try:
                            ch = await _wlf_refresh_channel(guild, kind)
                            rec['closed_notice'] = True
                            await bd_save_data()
                            await ch.send('🐈 The merchant packed up! Shop closed to visitors. '
                                          'Treasure Hunters who finished the story can still shop here forever.')
                        except (discord.HTTPException, PermissionError) as exc:
                            log.warning('Could not close shop %s/%s: %s',guild.id,kind,exc)
            await asyncio.sleep(60)
    finally:
        bot._wlf_shop_reaper_running = False


@wildlands_art_group.command(name='gather', description='Search Wildlands for supplies, fishing spots, and merchants')
@app_commands.guild_only()
async def wildlands_gather(interaction: discord.Interaction):
    g, u = interaction.guild.id, interaction.user.id
    p = _wlf_player(g, u)
    remaining = max(0, int(p['next_gather'] - _wlf_time.time()))
    if remaining:
        return await interaction.response.send_message(f'🌿 Cinnamon is still gathering! Try again in **{remaining}s**.', ephemeral=True)
    # Complete encounter, then roll once for a permanent new area (12%)
    p['next_gather'] = _wlf_time.time() + 60
    supplies = _wlf_random.randint(2, 5)
    p['bait']['normal'] = int(p['bait'].get('normal', 0)) + supplies
    desc = f'🐾 Collected **{supplies} Normal Bait** while exploring.'
    undiscovered = [a for a in _WLF_AREAS if a[0] not in p['areas']]
    if undiscovered and _wlf_random.random() < .12:
        area = _wlf_random.choice(undiscovered)
        p['areas'].append(area[0])
        desc += f'\n🗺️ **New fishing area permanently discovered:** **{area[1]}**! Use `/fishing travel` to visit.'
    desc += await _wlf_attempt_merchant(interaction.guild, finder=interaction.user, announce_channel=interaction.channel)
    await bd_save_data()
    await interaction.response.send_message(embed=_wlf_embed('🍃 Wildlands Gathering', desc, interaction=interaction))


@wildlands_art_group.command(name='fish', description='Browse all Wildlands fish by rarity and location')
@app_commands.guild_only()
async def wildlands_fish_catalog(interaction: discord.Interaction):
    view = _WLFCatalog(interaction.user.id, 'fish', interaction.guild.id)
    await interaction.response.send_message(embed=view.render(), view=view)


@wildlands_art_group.command(name='rods', description='Browse fishing rods and their stats')
@app_commands.guild_only()
async def wildlands_rod_catalog(interaction: discord.Interaction):
    view = _WLFCatalog(interaction.user.id, 'rod', interaction.guild.id)
    await interaction.response.send_message(embed=view.render(), view=view)


@wildlands_art_group.command(name='bait', description='Browse fishing bait and their prices')
@app_commands.guild_only()
async def wildlands_bait_catalog(interaction: discord.Interaction):
    view = _WLFCatalog(interaction.user.id, 'bait', interaction.guild.id)
    await interaction.response.send_message(embed=view.render(), view=view)


_wlf_group = app_commands.Group(name='fishing', description='Cinnamon Wildlands fishing game')


@_wlf_group.command(name='start', description='Get your starter rod and 10 bait; see how fishing works')
@app_commands.guild_only()
async def fishing_start(interaction: discord.Interaction):
    p = _wlf_player(interaction.guild.id, interaction.user.id)
    await bd_save_data()
    e = _wlf_embed('🎣 Welcome to Wildlands Fishing',
        '**Starter gear:** Woodland Rod + 10 Normal Bait\n'
        f'**Location:** {_wlf_area(p["area"])[1]}\n\n'
        'Use `/fishing cast` to catch fish, `/wildlands gather` to find new areas and merchants, '
        '`/fishing journal` to view discoveries, `/fishing sell` for Catnip, and `/fishing travel` to change areas. '
        'Gather permanently unlocks new areas at a 12% chance.', interaction=interaction)
    await interaction.response.send_message(embed=e, ephemeral=True)


@_wlf_group.command(name='cast', description='Use your rod and bait to catch a local fish')
@app_commands.guild_only()
async def fishing_cast(interaction: discord.Interaction):
    g, u = interaction.guild.id, interaction.user.id
    p = _wlf_player(g, u)
    if p['area'] not in p['areas']:
        p['area'] = 'whispering_woods'
    remaining = max(0, _wlf_math.ceil(p['next_cast'] - _wlf_time.time()))
    if remaining:
        return await interaction.response.send_message(f'🎣 Give the water a moment! Cast again in **{remaining}s**.', ephemeral=True)
    bait_id = next((b['id'] for b in reversed(_WLF_BAIT) if int(p['bait'].get(b['id'], 0)) > 0), None)
    if bait_id is None:
        return await interaction.response.send_message('🐟 Out of bait! Gather with `/wildlands gather`, or buy bait using `/fishing buy-bait`.', ephemeral=True)
    bait = next(b for b in _WLF_BAIT if b['id'] == bait_id)
    rod = next((r for r in _WLF_RODS if r['id'] == p['rod']), _WLF_RODS[0])
    idx = _wlf_roll(rod['bonus'] + bait['bonus'] + _cm_fishing_bonus(g))
    fish_key = f'{p["area"]}:{idx}'
    fish = _WLF_FISH[fish_key]
    # Commit state *before* role granting so a missing Manage Roles permission
    # never loses the fish catch.
    p['bait'][bait_id] -= 1
    p['fish'][fish_key] = int(p['fish'].get(fish_key, 0)) + 1
    if fish_key not in p['seen']:
        p['seen'].append(fish_key)
        discovery = '\n📖 **New journal entry!**'
    else:
        discovery = ''
    p['next_cast'] = _wlf_time.time() + 30
    await bd_save_data()
    extra = await _wlf_award_rare_role(interaction, fish)
    desc = (f'You caught **{fish["name"]}**!\n'
            f'**Rarity:** {fish["rarity"]} • **Value:** {fish["value"]:,} Catnip\n'
            f'**Area:** {_wlf_area(p["area"])[1]} • **Bait:** {bait["name"]}\n'
            f'**Owned:** {p["fish"][fish_key]}{discovery}{extra}')
    await interaction.response.send_message(embed=_wlf_embed('🎣 A Bite!', desc, interaction=interaction))


@_wlf_group.command(name='locations', description='Show discovered and locked fishing locations')
@app_commands.guild_only()
async def fishing_locations(interaction: discord.Interaction):
    p = _wlf_player(interaction.guild.id, interaction.user.id)
    lines = [f'{"✅" if a[0] in p["areas"] else "🔒"} **{a[1]}**'
             + (' • Current' if a[0] == p['area'] else '') for a in _WLF_AREAS]
    await interaction.response.send_message(embed=_wlf_embed('🗺️ Your Fishing Areas',
        '\n'.join(lines) + '\n\nExplore using `/wildlands gather` to unlock new fishing spots permanently.', interaction=interaction), ephemeral=True)


async def _wlf_area_autocomplete(interaction: discord.Interaction, current: str):
    p = _wlf_player(interaction.guild.id, interaction.user.id) if interaction.guild else {'areas': []}
    return [app_commands.Choice(name=a[1], value=a[0]) for a in _WLF_AREAS
            if a[0] in p['areas'] and (current.lower() in a[1].lower() or current.lower() in a[0])][:25]


@_wlf_group.command(name='travel', description='Travel to a discovered fishing location')
@app_commands.autocomplete(location=_wlf_area_autocomplete)
@app_commands.guild_only()
async def fishing_travel(interaction: discord.Interaction, location: str):
    p = _wlf_player(interaction.guild.id, interaction.user.id)
    area = next((a for a in _WLF_AREAS if a[0] == location or a[1].casefold() == location.casefold()), None)
    if not area:
        return await interaction.response.send_message('🐾 Location unknown. Use `/fishing locations`.', ephemeral=True)
    if area[0] not in p['areas']:
        return await interaction.response.send_message('🔒 Discover this area with `/wildlands gather` before travelling.', ephemeral=True)
    p['area'] = area[0]
    await bd_save_data()
    await interaction.response.send_message(embed=_wlf_embed('🗺️ Fishing Location Updated', f'Now fishing at **{area[1]}**! Each area has its own six fish.', interaction=interaction))


@_wlf_group.command(name='journal', description='View all your discovered fish and progress')
@app_commands.guild_only()
async def fishing_journal(interaction: discord.Interaction):
    p = _wlf_player(interaction.guild.id, interaction.user.id)
    viewed = len(set(p['seen']))
    lines = []
    for area in _WLF_AREAS:
        discovered = [f['name'] for key, f in _WLF_FISH.items() if key in p['seen'] and f['area'] == area[0]]
        lines.append(f'**{area[1]}** — {len(discovered)}/6\n' + (', '.join(discovered) if discovered else 'Not caught yet'))
    await interaction.response.send_message(embed=_wlf_embed(f'📖 Fishing Journal • {viewed}/36', '\n\n'.join(lines), interaction=interaction), ephemeral=True)


@_wlf_group.command(name='inventory', description='View your caught fish and bait')
@app_commands.guild_only()
async def fishing_inventory(interaction: discord.Interaction):
    p = _wlf_player(interaction.guild.id, interaction.user.id)
    caught = [(key, int(n)) for key, n in p['fish'].items() if int(n) > 0 and key in _WLF_FISH]
    caught.sort(key=lambda x:(_WLF_FISH[x[0]]['value'], x[0]), reverse=True)
    lines = [f'{_WLF_FISH[k]["name"]} × **{n}** ({_WLF_FISH[k]["rarity"]})' for k, n in caught]
    if len(lines) > 20:
        lines = lines[:20] + [f'…and {len(caught)-20} more types']
    bait_text = ', '.join(f'{b["name"]} ×{p["bait"].get(b["id"], 0)}' for b in _WLF_BAIT)
    e = _wlf_embed('🎒 Fishing Backpack', '\n'.join(lines) or 'No fish caught yet.', interaction=interaction)
    e.add_field(name='Rod', value=next((r['name'] for r in _WLF_RODS if r['id'] == p['rod']), 'Woodland Rod'), inline=False)
    e.add_field(name='Bait', value=bait_text, inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)


@_wlf_group.command(name='merchants', description='See which two-hour merchant shops are open and who found them')
@app_commands.guild_only()
async def fishing_merchants(interaction: discord.Interaction):
    guild = interaction.guild
    lines=[]
    for kind, name in _WLF_MERCHANTS.items():
        window=_wlf_window(guild.id,kind)
        if _wlf_active(guild.id,kind):
            left=max(0,int(window['ends_at']-_wlf_time.time()))
            ch=_wlf_channel(guild,kind)
            lines.append(f'🏪 **{name}** — OPEN for {left//60}m {left%60}s • '+(ch.mention if ch else 'Channel unavailable'))
        elif _wlf_story_complete(guild.id,interaction.user.id):
            ch=_wlf_channel(guild,kind)
            lines.append(f'🏅 **{name}** — permanently unlocked for you • '+(ch.mention if ch else 'Ask an admin to check channels'))
        else:
            lines.append(f'🔒 **{name}** — closed until the next discovery')
    await interaction.response.send_message(embed=_wlf_embed('🏪 Wildlands Merchant Watch',
        '\n'.join(lines)+'\n\nA lucky `/wildlands gather` or story encounter can open a shop server-wide for 2 hours. '
        'The discoverer receives 10% of other people’s purchases **inside that shop channel**. '
        'Finish the Wildlands story to access both shops permanently.', interaction=interaction),ephemeral=True)


async def _wlf_rod_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=r['name'], value=r['id']) for r in _WLF_RODS if current.casefold() in r['name'].casefold() or current.casefold() in r['id']][:25]


async def _wlf_bait_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=b['name'], value=b['id']) for b in _WLF_BAIT if current.casefold() in b['name'].casefold() or current.casefold() in b['id']][:25]


@_wlf_group.command(name='buy-rod', description='Buy a fishing rod from an open or permanent merchant')
@app_commands.autocomplete(rod=_wlf_rod_autocomplete)
@app_commands.guild_only()
async def fishing_buy_rod(interaction: discord.Interaction, rod: str):
    item=next((r for r in _WLF_RODS if r['id']==rod or r['name'].casefold()==rod.casefold()),None)
    if not item:
        return await interaction.response.send_message('Unknown rod; use `/wildlands rods`.',ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    message=await _wlf_purchase(interaction,'rod',item)
    await interaction.followup.send(message,ephemeral=True)


@_wlf_group.command(name='equip', description='Equip a purchased rod by searchable name')
@app_commands.autocomplete(rod=_wlf_rod_autocomplete)
@app_commands.guild_only()
async def fishing_equip(interaction: discord.Interaction, rod: str):
    p = _wlf_player(interaction.guild.id, interaction.user.id)
    item = next((r for r in _WLF_RODS if r['id'] == rod or r['name'].casefold() == rod.casefold()), None)
    if not item or item['id'] not in p['rods']:
        return await interaction.response.send_message('🐾 That rod is not in your collection. Visit the Rod Merchant.', ephemeral=True)
    p['rod'] = item['id']
    await bd_save_data()
    await interaction.response.send_message(f'🎣 Equipped **{item["name"]}**!', ephemeral=True)


@_wlf_group.command(name='buy-bait', description='Buy bait from an open or permanent merchant')
@app_commands.autocomplete(bait=_wlf_bait_autocomplete)
@app_commands.guild_only()
async def fishing_buy_bait(interaction: discord.Interaction, bait: str, quantity: app_commands.Range[int,1,100]=10):
    item=next((b for b in _WLF_BAIT if b['id']==bait or b['name'].casefold()==bait.casefold()),None)
    if not item:
        return await interaction.response.send_message('Unknown bait; use `/wildlands bait`.',ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    message=await _wlf_purchase(interaction,'bait',item,quantity)
    await interaction.followup.send(message,ephemeral=True)


async def _wlf_fish_autocomplete(interaction: discord.Interaction, current: str):
    if not interaction.guild:
        return []
    p = _wlf_player(interaction.guild.id, interaction.user.id)
    return [app_commands.Choice(name=f['name'][:100], value=k) for k,f in _WLF_FISH.items()
            if int(p['fish'].get(k, 0)) > 0 and (current.casefold() in f['name'].casefold() or current.casefold() in k)][:25]


@_wlf_group.command(name='sell', description='Sell a named fish to earn Catnip')
@app_commands.autocomplete(fish=_wlf_fish_autocomplete)
@app_commands.guild_only()
async def fishing_sell(interaction: discord.Interaction, fish: str, quantity: app_commands.Range[int,1,100] = 1):
    g,u = interaction.guild.id, interaction.user.id
    p = _wlf_player(g,u)
    key = next((k for k,f in _WLF_FISH.items() if k == fish or f['name'].casefold() == fish.casefold()), None)
    if key is None:
        return await interaction.response.send_message('🐾 Fish not found; choose one from autocomplete.', ephemeral=True)
    owned = int(p['fish'].get(key, 0))
    if owned < quantity:
        return await interaction.response.send_message(f'🐟 You have **{owned}× {_WLF_FISH[key]["name"]}**; cannot sell {quantity}.', ephemeral=True)
    payout = quantity * _WLF_FISH[key]['value']
    p['fish'][key] = owned - quantity
    before = economy_balance(g,u)
    economy_balances[(g,u)] = before + payout
    await bd_save_data()
    await economy_log(g, title='🐟 Wildlands fish sold', fields=[('Member ID', u), ('Fish', _WLF_FISH[key]['name']), ('Quantity', quantity), ('Catnip earned', payout), ('Balance before', before), ('Balance after', economy_balances[(g,u)])])
    await interaction.response.send_message(f'🌿 Sold **{quantity} × {_WLF_FISH[key]["name"]}** for **{payout:,} Catnip**. New balance: **{economy_balances[(g,u)]:,}**.', ephemeral=True)


class _WLFRarity(discord.ui.Select):
    def __init__(self, parent):
        self.parent_catalog = parent
        options = [discord.SelectOption(label='All rarities',value='all')] + [discord.SelectOption(label=r, value=r) for r in _WLF_RARITIES]
        super().__init__(placeholder='Filter fish by rarity', options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.parent_catalog.rarity = self.values[0]
        self.parent_catalog.index = 0
        await interaction.response.edit_message(embed=self.parent_catalog.render(), view=self.parent_catalog)


class _WLFCatalog(discord.ui.View):
    def __init__(self, user_id, kind, guild_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.kind = kind
        self.guild_id = guild_id
        self.index = 0
        self.rarity = 'all'
        if kind == 'fish':
            self.add_item(_WLFRarity(self))
        self._update_buy_state()

    def entries(self):
        if self.kind == 'fish':
            return [(k,f) for k,f in _WLF_FISH.items() if self.rarity == 'all' or f['rarity'] == self.rarity]
        return [(i['id'], i) for i in (_WLF_RODS if self.kind == 'rod' else _WLF_BAIT)]

    def _update_buy_state(self):
        self.buy_item.disabled = (self.kind == 'fish')
        self.buy_item.label = 'Buy rod' if self.kind == 'rod' else 'Buy 10 bait'

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('🐾 This browser belongs to someone else; run the command yourself.', ephemeral=True)
            return False
        return True

    def render(self):
        items = self.entries()
        self.index %= len(items)
        key, item = items[self.index]
        if self.kind == 'fish':
            text = f'**Rarity:** {item["rarity"]}\n**Home:** {_wlf_area(item["area"])[1]}\n**Sell value:** {item["value"]:,} Catnip\n'
            if item['role_name']:
                text += f'**Title:** {item["role_name"]}\n'
            text += '\nEach area has six exclusive fish. Use `/fishing cast` to discover them.'
            title = '🐟 ' + item['name']
        elif self.kind == 'rod':
            text = f'**Price:** {_cm_price(self.guild_id, self.user_id, item["id"], item["price"]):,} Catnip\n**Rarity boost:** +{item["bonus"]:.1f}\n\n{item["description"]}'
            title = '🎣 ' + item['name']
        else:
            text = f'**Price:** {_cm_price(self.guild_id, self.user_id, item["id"], item["price"]):,} Catnip each\n**Rarity boost:** +{item["bonus"]:.1f}\n\n{item["description"]}'
            title = '🪱 ' + item['name']
        e = _wlf_embed(title, text)
        e.set_footer(text=f'Cinnamon Wildlands • {self.index+1}/{len(items)} • {self.rarity if self.kind == "fish" else self.kind.title()}')
        # Cutout filenames in the Runway import are anonymous: never show a
        # random fish/rod/bait image as if its identity were confirmed.
        return e

    @discord.ui.button(label='◀ Previous', style=discord.ButtonStyle.secondary, row=1)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index-1) % len(self.entries())
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label='Buy 10 bait', style=discord.ButtonStyle.success, row=1)
    async def buy_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.kind == 'fish':
            return await interaction.response.send_message('🐟 Browse the collection here; catch fish with `/fishing cast`.',ephemeral=True)
        _,item=self.entries()[self.index]
        await interaction.response.defer(ephemeral=True)
        message=await _wlf_purchase(interaction, 'rod' if self.kind=='rod' else 'bait', item,
                                     1 if self.kind=='rod' else 10)
        await interaction.followup.send(message,ephemeral=True)


    @discord.ui.button(label='Next ▶', style=discord.ButtonStyle.primary, row=1)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index+1) % len(self.entries())
        await interaction.response.edit_message(embed=self.render(), view=self)


@_wlf_group.command(name='setup-roles', description='Admin: create or repair all Fishing Merchant and rare fish roles')
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def fishing_setup_roles(interaction: discord.Interaction):
    guild = interaction.guild
    if not (guild.me and guild.me.guild_permissions.manage_roles):
        return await interaction.response.send_message(
            '⚠️ Cinnamon needs **Manage Roles** to create fishing titles. '
            'Give her the permission and run this again.', ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    created, failed = [], []
    existing = {r.name for r in guild.roles if not r.managed}
    for name in _wlf_required_roles():
        if name in existing:
            continue
        try:
            await guild.create_role(name=name, reason='Cinnamon Wildlands fishing role setup')
            existing.add(name)
            created.append(name)
        except discord.HTTPException as exc:
            failed.append(name)
            log.warning('Wildlands role %s creation failed: %s', name, exc)
    await interaction.followup.send(
        embed=_wlf_embed('🏷️ Wildlands Roles',
            f'**Ready:** {len(_wlf_required_roles()) - len(failed)}/{len(_wlf_required_roles())}\n'
            f'**Newly created:** {len(created)}\n'
            f'**Failed:** {", ".join(failed) if failed else "None"}\n\n'
            'Rare fish titles are granted automatically when someone catches '
            'the matching Legendary or Mythical fish. Cinnamon’s role must '
            'be above these roles to award them.', interaction=interaction), ephemeral=True)


# Only one /fishing slash group. /wildlands subgroup commands are appended to
# the already registered /wildlands group and will be synced on next startup.
bot.tree.add_command(_wlf_group)