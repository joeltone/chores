# Chore Bot

A self-hosted Discord bot that rotates household chores among a group of people, tracks completion, escalates overdue chores, and publishes a per-person calendar feed.

Managed entirely through Discord slash commands — no web dashboard required.

## Features

- Rotation engine that assigns chores fairly across active users, with support for per-user exclusions
- Persistent completion buttons on each assignment (survive bot restarts)
- Per-user Discord threads bundling all of that person's pending chores
- Daily automation: new assignments posted at 8:00 AM, overdue chores escalated at 9:00 AM (Manitoba time — see [Timezone](#timezone))
- On-demand one-time reminders (`/chore remind-me`) — pick a time later today and the bot pings you then with whatever's still open
- Pause/reinstate users (e.g. while traveling) with automatic reassignment of their open chores
- Per-user calendar subscription (`webcal`/`.ics`) showing chores as all-day events, plus one-off `.ics` export
- Rotatable per-user calendar tokens for revoking a compromised link
- Audit log of assignments and command usage

See [GUIDE.md](GUIDE.md) for the full command reference and day-to-day usage, or [HOUSE_GUIDE.md](HOUSE_GUIDE.md) for a plain-language walkthrough written for non-technical household members.

## Stack

- Python 3.13, [discord.py](https://discordpy.readthedocs.io/), APScheduler, SQLAlchemy, aiohttp, SQLite
- systemd for process supervision
- Cloudflare Tunnel to expose only the calendar endpoint publicly

## Project layout

```
bot.py               # Entry point: loads cogs, scheduler, calendar server
cal_server.py        # aiohttp server serving per-user .ics calendar feeds
clock.py              # App-wide timezone (Manitoba) + now()/today() helpers
db.py                 # Schema + connection helper
rotation.py           # Chore assignment/rotation engine
scheduler_jobs.py     # Daily assignment + escalation jobs + one-time reminders
ical.py               # iCalendar (.ics) generation
views.py              # Persistent Discord button components
cogs/
  users.py            # /user commands
  chores.py           # /chore commands
  admin.py             # /admin commands
seed_chores.py        # Bulk-load chores from a script instead of one by one
seed_exclusions.py    # Bulk-load user/chore exclusions
backup.py             # Database backup script (used by chore-backup.timer)
data/                 # SQLite databases (chores.db, jobs.db) — gitignored
```

## Local setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the values below
python bot.py
```

### Environment variables (`.env`)

| Variable | Purpose |
|---|---|
| `DISCORD_BOT_TOKEN` | Bot token from the Discord Developer Portal |
| `DISCORD_CHANNEL_ID` | Channel where daily assignment threads are posted |
| `ADMIN_DISCORD_ID` | User pinged for escalations |
| `DB_PATH` | Path to the SQLite database (defaults to `data/chores.db`) |
| `CAL_PORT` | Local port for the calendar HTTP server (default `8080`) |
| `CAL_BASE_URL` | Public base URL for calendar links (your Cloudflare Tunnel hostname) |

### Timezone

All "what day is it" and scheduling logic — due dates, daily thread labels, the 8 AM/9 AM cron jobs, and `/chore remind-me` — reads the current date/time through [clock.py](clock.py), which is hardcoded to `America/Winnipeg` (Manitoba) regardless of the host machine's own system timezone. To run this for a different household, change `TZ` in `clock.py`.

### Seeding initial data

Either use the slash commands (`/user add`, `/chore add`, `/chore exclude`, `/chore seed` — see [GUIDE.md](GUIDE.md)), or bulk-load with `python seed_chores.py` / `python seed_exclusions.py` if you're migrating a large list.

## Production deployment

The bot is designed to run under systemd with a Cloudflare Tunnel exposing only the calendar endpoint:

- `chore-bot.service` — runs `bot.py`, restarts on failure
- `chore-cloudflared.service` — tunnels `cal.<yourdomain>` to the local calendar server; see `cloudflared.yml` for the full tunnel setup steps (create tunnel, DNS route, credentials file)
- `chore-backup.service` + `chore-backup.timer` — nightly SQLite backup via `backup.py`

To install:

```bash
sudo cp chore-bot.service chore-cloudflared.service chore-backup.service chore-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chore-bot chore-cloudflared chore-backup.timer
```

Adjust `WorkingDirectory`/`ExecStart` paths in the `.service` files if your deployment directory differs from `/opt/chore-bot`.

### Updating

`/opt/chore-bot` is a plain file copy, not a git checkout, so there's no `git pull` on the deployment side. After making changes in this repo, copy the changed files over and restart the service:

```bash
cp cogs/chores.py /opt/chore-bot/cogs/chores.py   # repeat for each changed file
sudo systemctl restart chore-bot
```

### Calendar endpoint security

The calendar server binds to `127.0.0.1` only; the Cloudflare Tunnel forwards just the `/cal/*.ics` path. Each user gets a unique 256-bit token in their URL, requests are rate-limited, and the origin IP/User-Agent are checked against Google's published ranges (since calendar polling comes from Google Calendar's servers). Rotate a token with `/user rotate-token @user` if a link leaks.

## History

See [SESSION.md](SESSION.md) for the build log, bugs fixed, and features added beyond the original spec.
