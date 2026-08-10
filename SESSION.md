# Chore Bot — Build Session Summary

## What Was Built

A self-hosted household chore rotation bot, managed entirely through Discord slash commands. Started from a spec and shipped a working production deployment.

---

## Stack

- **Python 3.13** — discord.py, APScheduler, aiohttp, SQLite
- **Systemd** — auto-restart on failure, starts on boot
- **Cloudflare Tunnel** — secure public endpoint for calendar subscriptions

---

## Session Log

### Core Bot
- Implemented full DB schema (users, chores, exclusions, assignments, audit log, command log)
- Rotation engine with exclusion support
- Persistent Discord button views (survive bot restarts)
- All slash commands: `/user`, `/chore`, `/admin`

### Documentation
- Added `HOUSE_GUIDE.md` — a plain-language walkthrough of the rotation, daily automation, and every command, written for non-technical household members (as opposed to `GUIDE.md`, which is the terse admin/dev command reference)
- Linked it from `README.md` alongside `GUIDE.md`

### Scheduler Misfire Bug (2026-08-10)
- Daily 8am assignment job silently didn't run — no threads posted, log showed `WARNING ... Run time of job "run_daily_assignments" ... was missed by 0:00:15`
- Root cause: `bot.py` passed `misfire_grace_time=600` as a flat kwarg to `AsyncIOScheduler(...)`; APScheduler only honors that setting when nested under `job_defaults`, so the real grace time silently fell back to the library default of **1 second** — any event-loop delay past ~1s (Discord gateway RESUME churn, in this case) caused the job to be skipped entirely instead of just running late
- Fixed by changing to `job_defaults={"misfire_grace_time": 600}`; verified against the installed APScheduler package directly (`scheduler._job_defaults`) before and after
- Restarted `chore-bot.service` to deploy; backfilled the missed run via the existing `/admin run-assignments` command
- Follow-up check: Morgy got no thread in the backfilled run — confirmed via DB query this was correct (no incomplete or newly-due chores for her that day), not a second bug

### Bugs Fixed
- APScheduler pickle error — Discord bot object isn't serialisable; fixed by storing bot reference in module scope instead of passing as job argument
- `DB_PATH` pointed to `/opt/chore-bot` before directory existed — moved databases to `data/` subfolder
- Entire `/opt/chore-bot` directory owned by root — `chown -R joel:joel` fixed write errors
- `cp -r` nested the project into a subdirectory — switched to `rsync --exclude` for all subsequent deploys
- Seed command always assigned to the first eligible user — rewrote to track per-user counts across the seed run for even distribution

### Features Added Beyond Spec
| Feature | Command |
|---|---|
| Rename a chore | `/chore rename` |
| Per-user assignment matrix | `/chore matrix` |
| Export chores as `.ics` file | `/chore export @user` |
| Per-user threads instead of individual messages | automatic |
| Staggered due dates by frequency | automatic on seed |
| Live webcal subscription URL | `/user calendar` |
| Token rotation | `/user rotate-token @user` |

### Data Recovery
- Production database lost twice during deployment (overwritten by `cp -r`)
- Recovered via `seed_chores.py` bulk insert script
- Exclusions restored via `seed_exclusions.py` (46 exclusions across 4 users and 32 chores)
- Root cause: switched to `rsync --exclude='data/'` to prevent future overwrites

### Security (Calendar Endpoint)
- aiohttp server binds to `127.0.0.1` only
- Cloudflare Tunnel exposes only `/cal/*.ics` via path regex
- `CF-Connecting-IP` validated against Google's published IP ranges, refreshed daily
- User-Agent must contain "Google"
- Per-user 256-bit secret token in URL
- Rate limited to 20 requests/hour per token
- Tokens rotatable on demand

---

## Deployment

```
/opt/chore-bot/
├── bot.py              # Entry point
├── cal_server.py       # Webcal aiohttp server
├── db.py               # Schema + migrations
├── rotation.py         # Assignment engine
├── scheduler_jobs.py   # Daily assign + escalation
├── views.py            # Discord button components
├── ical.py             # iCalendar generation
├── cogs/
│   ├── users.py
│   ├── chores.py
│   └── admin.py
├── data/
│   ├── chores.db
│   └── jobs.db
└── .env
```

Two systemd services: `chore-bot` and `chore-cloudflared`, both enabled and running.

---

## Git Log

```
437fb90  Add secure webcal subscription endpoint via Cloudflare Tunnel
5a473aa  Add /chore export command to download .ics calendar file
652e5bd  Stagger seed due dates across each chore's frequency window
71e8fd0  Group daily assignments into per-user Discord threads
62f0dab  Add seed_exclusions.py for bulk chore exclusion setup
50f2d00  Fix APScheduler pickling error and add /chore rename command
78fbee5  Store databases in data/ subfolder for easy backups
a24ece4  Add Discord chore rotation bot (initial implementation)
```
