"""Shared delivery helpers for every Cinnamon interactive story.

Narration is sent as ordinary Discord message content (Markdown supported).
Story controls are a separate embed with buttons/selects, and the delivery
channel is always the player's DM. Story modules keep their own state/routes.
"""

async def cinnamon_story_send_dm(user, narration, control_embed, view=None):
    """Send formatted story narration as a normal DM, then a separate control card."""
    text = str(narration or "").strip()
    if text:
        await user.send(content=text[:2000],
                        allowed_mentions=discord.AllowedMentions.none())
    return await user.send(embed=control_embed, view=view,
                           allowed_mentions=discord.AllowedMentions.none())


def cinnamon_story_controls_embed(title, description, *, color=0xD97732, footer="Cinnamon Stories • Choices save automatically"):
    """Build the separate, story-text-free control embed."""
    embed = discord.Embed(title=("📖 " + str(title))[:256],
                          description=str(description or "Choose an option below.")[:3500],
                          color=color)
    embed.set_author(name="🐈 CINNAMON • INTERACTIVE STORIES")
    embed.set_footer(text=footer[:2048])
    return embed
