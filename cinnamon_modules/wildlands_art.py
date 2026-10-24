"""Cinnamon Wildlands artwork browser; standalone, no economy changes.

Existing Runway images can be copied to static/wildlands/ by the one-time
GitHub workflow or auto-cached in the background on deployment.
Images are never fetched by Discord from expiring Runway URLs.
This module does not invent item identities for the 46 unlabeled transparent
fish/rod/bait cutouts; the vault allows admins to review numbered originals.
"""
import io as _wl_io
import json as _wl_json
import textwrap as _wl_textwrap
import os as _wl_os
import sys as _wl_sys
import subprocess as _wl_subprocess
import threading as _wl_threading
from pathlib import Path as _WL_Path

from PIL import Image as _WL_Image, ImageDraw as _WL_Draw, ImageFont as _WL_Font, ImageOps as _WL_ImageOps

_WL_BASE = _WL_Path(__file__).resolve().parents[1] / 'static' / 'wildlands'
_WL_MANIFEST = _WL_BASE / 'manifest.json'

_WL_SPOT_DESCRIPTIONS = {
    'woodland_fishing_pier': 'Cast a line in the quiet waters beside the forest.',
    'moonlit_fishing_pool': 'Still waters glimmer under a silvery night sky.',
    'frostfall_fishing_spot': 'Follow the cold streams beneath the icy ridges.',
    'ruins_fishing_pool': 'An old pool, tucked among mysterious ruins.',
}
_WL_KIND_TITLES = {'fishing_place': 'Fishing spot', 'unmapped_cutout': 'Art vault'}
_WL_COLOR = 0xD99242
_wl_import_running = False
_wl_import_finished = False
_wl_import_error = False


def wildlands_art_items(category=None):
    """Read the stable local manifest, NEVER the source URL list."""
    try:
        data = _wl_json.loads(_WL_MANIFEST.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    entries = data.get('images', [])
    return [i for i in entries if isinstance(i, dict) and (
        category is None or i.get('kind') == category
    ) and isinstance(i.get('file'), str)]


def wildlands_local_asset(key):
    """Reusable integration hook for future fishing, merchant and item panels."""
    for item in wildlands_art_items():
        if item.get('key') != key:
            continue
        path = (_WL_BASE / item['file']).resolve()
        if not path.is_relative_to(_WL_BASE.resolve()):
            return None
        return path if path.is_file() else None
    return None


def _wl_font(size, bold=False):
    names = ('DejaVuSans-Bold.ttf', 'DejaVuSans.ttf') if bold else ('DejaVuSans.ttf',)
    for name in names:
        try:
            return _WL_Font.truetype(name, size)
        except OSError:
            continue
    return _WL_Font.load_default()


def _wl_wrap(draw, text, font, max_width, max_lines=3):
    """Wrap using actual pixel measurements; safe for Discord's small screens."""
    words = (text or '').split()
    lines, current = [], ''
    for word in words:
        candidate = (current + ' ' + word).strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while draw.textbbox((0, 0), lines[-1] + '…', font=font)[2] > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += '…'
    return lines


def _wl_card(path, title, summary, subtitle):
    """Create a real image-left/text-right card for mobile and desktop."""
    width, height = 860, 340
    canvas = _WL_Image.new('RGB', (width, height), '#F8F3EC')
    d = _WL_Draw.Draw(canvas)
    d.rounded_rectangle((9, 9, width-9, height-9), radius=22, fill='#F8F3EC', outline='#E8DBCB', width=3)
    d.rounded_rectangle((22, 22, 324, 318), radius=18, fill='#EBDED0')
    if path is not None:
        try:
            with _WL_Image.open(path) as original:
                image = _WL_ImageOps.exif_transpose(original).convert('RGBA')
                image.thumbnail((294, 286), _WL_Image.Resampling.LANCZOS)
                x = 22 + (302-image.width)//2
                y = 22 + (296-image.height)//2
                canvas.paste(image, (x, y), image)
        except (OSError, ValueError):
            path = None
    if path is None:
        d.text((86, 151), '🐾  Art pending', font=_wl_font(23, True), fill='#6E5443')
    d.rounded_rectangle((348, 34, 540, 70), radius=11, fill='#FFE2BB')
    d.text((360, 42), subtitle.upper()[:19], font=_wl_font(18, True), fill='#805327')
    title_font = _wl_font(37, True)
    title_lines = _wl_wrap(d, title, title_font, 465, 2)
    y = 91
    for line in title_lines:
        d.text((347, y), line, font=title_font, fill='#34271E')
        y += 47
    d.line((349, 201, 823, 201), fill='#E5CEAF', width=2)
    summary_font = _wl_font(23)
    for line in _wl_wrap(d, summary, summary_font, 467, 3):
        d.text((348, max(216, y+9)), line, font=summary_font, fill='#725642')
        y += 34
    out = _wl_io.BytesIO()
    canvas.save(out, format='PNG', optimize=True)
    out.seek(0)
    return out


class WildlandsArtView(discord.ui.View):
    def __init__(self, owner_id: int, category: str, selected: int = 0):
        super().__init__(timeout=240)
        self.owner_id = owner_id
        self.category = category
        self.items = wildlands_art_items(category)
        self.index = min(max(0, selected), max(0, len(self.items)-1))
        if not self.items:
            self.clear_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('🐾 This gallery belongs to the person who opened it. Use the command to open your own.', ephemeral=True)
            return False
        return True

    def make_message(self):
        if not self.items:
            return discord.Embed(title='🐈 Cinnamon Wildlands', description='The art registry is missing. Check that `static/wildlands/manifest.json` was deployed.', color=_WL_COLOR), None
        item = self.items[self.index]
        filename = item['file']
        path = wildlands_local_asset(item['key'])
        if self.category == 'fishing_place':
            summary = _WL_SPOT_DESCRIPTIONS.get(item['key'], 'A new corner of Cinnamon Wildlands.')
        else:
            summary = 'Background-free fish, fishing rod, or bait artwork. Item name not mapped yet.'
        title = item['label']
        footer = f'Wildlands • {self.index+1} of {len(self.items)}'
        embed = discord.Embed(title='🌿 ' + title, description=summary, color=_WL_COLOR)
        embed.set_footer(text=footer)
        if path:
            img = _wl_card(path, title, summary, _WL_KIND_TITLES.get(self.category, 'Artwork'))
            attached = discord.File(fp=img, filename='cinnamon_wildlands_card.png')
            embed.set_image(url='attachment://cinnamon_wildlands_card.png')
        else:
            attached = None
            embed.add_field(name='Image not yet saved', value='The existing artwork link must first be copied into the repository by the included GitHub workflow.', inline=False)
        return embed, attached

    async def show(self, interaction):
        embed, file = self.make_message()
        # Replaces the previous image attachment (no buildup across pages).
        await interaction.response.edit_message(embed=embed, attachments=[file] if file else [], view=self)

    @discord.ui.button(label='◀ Previous', style=discord.ButtonStyle.secondary, row=0)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index - 1) % len(self.items)
        await self.show(interaction)

    @discord.ui.button(label='Next ▶', style=discord.ButtonStyle.primary, row=0)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index + 1) % len(self.items)
        await self.show(interaction)

    async def on_error(self, interaction, error, item):
        log.exception('Wildlands gallery UI failed: %s', error)
        if not interaction.response.is_done():
            await interaction.response.send_message('🐈 Cinnamon dropped an art frame. Try the command again.', ephemeral=True)


wildlands_art_group = app_commands.Group(name='wildlands', description='Cinnamon Wildlands art and fishing locations')


@wildlands_art_group.command(name='places', description='Browse the four illustrated Wildlands fishing places')
@app_commands.guild_only()
async def wildlands_places(interaction: discord.Interaction):
    view = WildlandsArtView(interaction.user.id, 'fishing_place')
    embed, file = view.make_message()
    await interaction.response.send_message(embed=embed, file=file, view=view, ephemeral=False)


@wildlands_art_group.command(name='art-vault', description='Admin: review saved background-free Wildlands artwork')
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def wildlands_art_vault(interaction: discord.Interaction, number: app_commands.Range[int, 1, 46] = 1):
    view = WildlandsArtView(interaction.user.id, 'unmapped_cutout', number-1)
    embed, file = view.make_message()
    await interaction.response.send_message(embed=embed, file=file, view=view, ephemeral=True)


@wildlands_art_group.command(name='art-status', description='See whether the saved Runway artwork is installed')
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def wildlands_art_status(interaction: discord.Interaction):
    records = wildlands_art_items()
    found = sum(wildlands_local_asset(i.get('key')) is not None for i in records)
    complete = f'**{found} / {len(records)}** image files available' if records else 'Manifest not found'
    embed = discord.Embed(title='🖼️ Wildlands Art Status', description=complete + ('\n\n⏳ Missing artwork is currently downloading in the background.' if _wl_import_running else '') + '\n\nFour fishing places plus 46 background-free cutouts are included in the artwork importer. Individual cutout identities must be mapped to game data before using them as named fish, rods, or bait. Save downloaded art permanently with the bundled GitHub Action.', color=_WL_COLOR)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# Register precisely once; do not create any duplicated slash-command aliases.
bot.tree.add_command(wildlands_art_group)


# Best-effort deployment fallback: on Render or another online host, copy the
# existing Runway images in a background process if GitHub has not saved them.
# This is NOT a permanent substitute for the GitHub Action: Render free-tier
# disks are ephemeral and the signed source URLs expire on 25 Oct 2026.
def _wl_import_missing_assets():
    global _wl_import_running, _wl_import_finished, _wl_import_error
    _wl_import_running = True
    script = _WL_BASE.parents[1] / 'tools' / 'import_runway_art.py'
    try:
        proc = _wl_subprocess.run(
            [_wl_sys.executable, str(script)],
            stdout=_wl_subprocess.PIPE, stderr=_wl_subprocess.PIPE,
            text=True, timeout=720, cwd=str(script.parent.parent),
        )
        if proc.returncode:
            _wl_import_error = True
            log.warning('Wildlands artwork auto-cache incomplete (%d). %s',
                        proc.returncode, (proc.stderr or '')[-900:])
        else:
            log.info('Wildlands artwork auto-cache complete: %s',
                     (proc.stdout or '').splitlines()[-1:])
    except Exception as exc:
        _wl_import_error = True
        log.warning('Wildlands artwork auto-cache failed: %s', type(exc).__name__)
    finally:
        _wl_import_running = False
        _wl_import_finished = True

if _wl_os.environ.get('CINNAMON_WILDLANDS_AUTO_FETCH', '1').strip().lower() not in ('0', 'false', 'no'):
    _wl_source_list = _WL_BASE.parents[1] / 'tools' / 'runway_art_urls.txt'
    if _wl_source_list.is_file() and any(
        wildlands_local_asset(_item.get('key')) is None for _item in wildlands_art_items()
    ):
        _wl_threading.Thread(target=_wl_import_missing_assets,
                             name='CinnamonWildlandsArtImport', daemon=True).start()
