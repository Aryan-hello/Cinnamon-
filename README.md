# Cinnamon Discord Bot + Dashboard

## Contents
- `main.py`: Cinnamon bot and Flask host integration.
- `dashboard.py`: OAuth2 login and initial dashboard pages.
- `static/cinnamon_mascot.jpg`: selected Cinnamon mascot.
- `requirements.txt`: Python packages.
- `.env.example`: local environment variable template (no secrets).
- `render.yaml`: optional Render Blueprint configuration.

## GitHub safety
Never commit `.env`, bot tokens, API keys, OAuth client secrets, or real user data. `.gitignore` excludes common secret and generated files. If a secret is accidentally committed, revoke/rotate it in its provider; deleting the commit alone is not enough.

## Render deployment
Set the start command to `python main.py` and build command to `pip install -r requirements.txt`. Add the required secrets in Render Environment: `DISCORD_TOKEN`, `GEMINI_API_KEY`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, and `DASHBOARD_SECRET_KEY`. Set `DASHBOARD_REDIRECT_URI` to `https://cinnamon-c328.onrender.com/oauth/callback` (or the matching URL for your service). The same exact redirect URI must be registered in Discord Developer Portal under OAuth2 Redirects.

The bot requires Message Content Intent and Server Members Intent enabled in Discord Developer Portal. Invite/role permissions should be configured for the existing bot features.

## Local run
Use Python 3.11+; create a virtual environment, install `requirements.txt`, copy `.env.example` to `.env`, fill in values privately, then run `python main.py`. Never upload `.env`.

## Dashboard status
The included dashboard supports the initial OAuth2 login and server listing. Dashboard controls for moderation, economy, quests, achievements, and other bot settings are not yet wired to the bot. Test in a private test server before enabling for others.
