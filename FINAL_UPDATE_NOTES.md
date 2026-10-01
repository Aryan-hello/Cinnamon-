# Cinnamon final update notes

## Included in this package
- Question mark (`?`) is the primary text prefix; `!` remains accepted for compatibility.
- Prefix commands added for help, balance, inventory, shop, buy, daily, work, warn, warnings, clearwarnings, kick, ban, unban, mute/timeout, unmute, and purge.
- Existing slash commands, including `/economy buy`, are retained.
- Catnip shop now has an interactive item selector and a Buy 1 button in both `/economy shop` and `?shop`.
- Prefix moderation commands use Discord permission checks and include role-hierarchy checks for member actions.

## Setup / deploy
1. Keep `DISCORD_TOKEN`, `GEMINI_API_KEY`, and dashboard OAuth environment variables private; never paste them into chat or commit them.
2. Ensure Message Content Intent and Server Members Intent are enabled in the Discord Developer Portal.
3. Install dependencies with `pip install -r requirements.txt` and run `python main.py`.
4. Commit/push this package to the connected GitHub repository and deploy/redeploy through Render.

The code was syntax-compiled and the archive contents verified locally. Live Discord interactions and Render deployment have not been tested or performed by this package build.
