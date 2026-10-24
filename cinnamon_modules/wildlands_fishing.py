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
    return list(_WLF_MERCHANTS.values()) + [f['role_name'] for f in _WLF_FISH.values() if f['role_name']]


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


def _wlf_merchant_open(guild_id, kind):
    return bool(_wlf_server(guild_id)['merchants'].get(kind))


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
    bonus = min(5, max(0, float(rarity_bonus)))
    shift = bonus * 3.0
    weights[0] -= shift
    weights[2] += shift * .25
    weights[3] += shift * .33
    weights[4] += shift * .29
    weights[5] += shift * .13
    return _wlf_random.choices(range(6), weights=weights, k=1)[0]


async def _wlf_attempt_merchant(guild):
    # Exactly one potential merchant unlock per completed encounter.
    s = _wlf_server(guild.id)
    locked = [k for k in _WLF_MERCHANTS if not s['merchants'].get(k)]
    if locked and _wlf_random.random() < .035:
        kind = _wlf_random.choice(locked)
        s['merchants'][kind] = True
        await bd_save_data()
        return f"\n🎉 **Server-wide discovery!** Everyone can now visit the **{_WLF_MERCHANTS[kind]}** using `/fishing merchants`."
    return ''


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
    desc += await _wlf_attempt_merchant(interaction.guild)
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
    idx = _wlf_roll(rod['bonus'] + bait['bonus'])
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


@_wlf_group.command(name='merchants', description='Check the server-wide rod and bait merchant discoveries')
@app_commands.guild_only()
async def fishing_merchants(interaction: discord.Interaction):
    g = interaction.guild.id
    lines = [f'{"✅ Discovered" if _wlf_merchant_open(g, k) else "🔒 Not discovered"} — **{name}**'
             for k, name in _WLF_MERCHANTS.items()]
    await interaction.response.send_message(embed=_wlf_embed('🏪 Wildlands Merchants',
        '\n'.join(lines) + '\n\nComplete Gather encounters to discover merchants server-wide (3.5% chance per encounter while merchants remain locked). '
        'Every member can use a merchant after discovery. To browse prices, use `/wildlands rods` or `/wildlands bait`.', interaction=interaction), ephemeral=True)


async def _wlf_rod_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=r['name'], value=r['id']) for r in _WLF_RODS if current.casefold() in r['name'].casefold() or current.casefold() in r['id']][:25]


async def _wlf_bait_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=b['name'], value=b['id']) for b in _WLF_BAIT if current.casefold() in b['name'].casefold() or current.casefold() in b['id']][:25]


@_wlf_group.command(name='buy-rod', description='Buy and equip a rod after discovering its merchant')
@app_commands.autocomplete(rod=_wlf_rod_autocomplete)
@app_commands.guild_only()
async def fishing_buy_rod(interaction: discord.Interaction, rod: str):
    g, u = interaction.guild.id, interaction.user.id
    item = next((r for r in _WLF_RODS if r['id'] == rod or r['name'].casefold() == rod.casefold()), None)
    if not item:
        return await interaction.response.send_message('🐾 Unknown rod. Check `/wildlands rods`.', ephemeral=True)
    p = _wlf_player(g, u)
    if item['id'] in p['rods']:
        p['rod'] = item['id']
        await bd_save_data()
        return await interaction.response.send_message(f'🎣 Equipped **{item["name"]}**.', ephemeral=True)
    if not _wlf_merchant_open(g, 'rod'):
        return await interaction.response.send_message('🔒 The Fishing Rod Merchant has not been discovered server-wide yet. Try `/wildlands gather`.', ephemeral=True)
    balance = economy_balance(g, u)
    if balance < item['price']:
        return await interaction.response.send_message(f'🌿 **{item["name"]}** costs {item["price"]:,} Catnip, but you have {balance:,}.', ephemeral=True)
    economy_balances[(g,u)] = balance - item['price']
    p['rods'].append(item['id'])
    p['rod'] = item['id']
    await bd_save_data()
    await economy_log(g, title='🎣 Wildlands rod purchased', fields=[('Member ID', u), ('Rod', item['name']), ('Price', item['price']), ('Balance after', economy_balances[(g,u)])])
    await interaction.response.send_message(f'🎣 Bought and equipped **{item["name"]}** for **{item["price"]:,} Catnip**.', ephemeral=True)


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


@_wlf_group.command(name='buy-bait', description='Purchase bait using Catnip; normal bait costs 100 for 10')
@app_commands.autocomplete(bait=_wlf_bait_autocomplete)
@app_commands.guild_only()
async def fishing_buy_bait(interaction: discord.Interaction, bait: str, quantity: app_commands.Range[int,1,100] = 10):
    item = next((b for b in _WLF_BAIT if b['id'] == bait or b['name'].casefold() == bait.casefold()), None)
    if not item:
        return await interaction.response.send_message('🐾 Unknown bait. Check `/wildlands bait`.', ephemeral=True)
    g,u = interaction.guild.id, interaction.user.id
    if item['id'] != 'normal' and not _wlf_merchant_open(g, 'bait'):
        return await interaction.response.send_message('🔒 Specialist bait becomes available after the Fishing Bait Merchant is discovered.', ephemeral=True)
    price = item['price'] * quantity
    balance = economy_balance(g,u)
    if balance < price:
        return await interaction.response.send_message(f'🌿 {quantity}× {item["name"]} costs **{price:,} Catnip**, but you have **{balance:,}**.', ephemeral=True)
    p = _wlf_player(g,u)
    economy_balances[(g,u)] = balance - price
    p['bait'][item['id']] = int(p['bait'].get(item['id'], 0)) + quantity
    await bd_save_data()
    await economy_log(g, title='🪱 Wildlands bait purchased', fields=[('Member ID', u), ('Bait', item['name']), ('Quantity', quantity), ('Cost', price), ('Balance after', economy_balances[(g,u)])])
    await interaction.response.send_message(f'🪱 Bought **{quantity} × {item["name"]}** for **{price:,} Catnip**.', ephemeral=True)


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
            text = f'**Price:** {item["price"]:,} Catnip\n**Rarity boost:** +{item["bonus"]:.1f}\n\n{item["description"]}'
            title = '🎣 ' + item['name']
        else:
            text = f'**Price:** {item["price"]:,} Catnip each\n**Rarity boost:** +{item["bonus"]:.1f}\n\n{item["description"]}'
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
            return await interaction.response.send_message('🐾 Browse the fish collection here; use `/fishing cast` to catch fish.', ephemeral=True)
        _, item = self.entries()[self.index]
        g,u = interaction.guild.id, interaction.user.id
        if self.kind == 'rod':
            p = _wlf_player(g,u)
            if item['id'] in p['rods']:
                p['rod'] = item['id']
                await bd_save_data()
                return await interaction.response.send_message(f'🎣 Equipped **{item["name"]}**.', ephemeral=True)
            if not _wlf_merchant_open(g,'rod'):
                return await interaction.response.send_message('🔒 Discover the Fishing Rod Merchant first.', ephemeral=True)
            cost = item['price']
        else:
            if item['id'] != 'normal' and not _wlf_merchant_open(g,'bait'):
                return await interaction.response.send_message('🔒 Discover the Fishing Bait Merchant first.', ephemeral=True)
            cost = item['price']*10
        bal = economy_balance(g,u)
        if bal < cost:
            return await interaction.response.send_message(f'🌿 Need {cost:,} Catnip; balance {bal:,}.', ephemeral=True)
        p = _wlf_player(g,u)
        economy_balances[(g,u)] = bal-cost
        if self.kind == 'rod':
            p['rods'].append(item['id'])
            p['rod'] = item['id']
        else:
            p['bait'][item['id']] = int(p['bait'].get(item['id'],0))+10
        await bd_save_data()
        await economy_log(g, title='🛒 Wildlands catalogue purchase', fields=[('User ID',u),('Item',item['name']),('Cost',cost),('Balance after',economy_balances[(g,u)])])
        await interaction.response.send_message(f'✅ Purchased **{item["name"]}** for **{cost:,} Catnip**.', ephemeral=True)

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
            f'**Ready:** {len(_wlf_required_roles()) - len(failed)}/14\n'
            f'**Newly created:** {len(created)}\n'
            f'**Failed:** {", ".join(failed) if failed else "None"}\n\n'
            'Rare fish titles are granted automatically when someone catches '
            'the matching Legendary or Mythical fish. Cinnamon’s role must '
            'be above these roles to award them.', interaction=interaction), ephemeral=True)


# Only one /fishing slash group. /wildlands subgroup commands are appended to
# the already registered /wildlands group and will be synced on next startup.
bot.tree.add_command(_wlf_group)
