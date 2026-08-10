import asyncio
import logging
import os

import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from dotenv import load_dotenv

import scheduler_jobs
from scheduler_jobs import SCHEDULER_TZ

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("chore-bot")

COGS = [
    "cogs.users",
    "cogs.chores",
    "cogs.admin",
]

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

db_path = os.getenv("DB_PATH", "data/chores.db")
_jobs_db = os.path.join(os.path.dirname(db_path), "jobs.db")
jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{_jobs_db}")}
scheduler = AsyncIOScheduler(
    jobstores=jobstores,
    timezone=SCHEDULER_TZ,
    job_defaults={"misfire_grace_time": 600},
)
scheduler_jobs.set_scheduler(scheduler)


@bot.event
async def on_ready():
    log.info("Logged in as %s (id=%s)", bot.user, bot.user.id)

    # Re-register persistent views for all incomplete assignments
    from db import get_db
    from views import ChoreCompleteView

    db = get_db()
    incomplete = db.execute("""
        SELECT assignment_id, discord_message_id FROM active_assignments
        WHERE is_completed = 0 AND discord_message_id IS NOT NULL
    """).fetchall()

    for row in incomplete:
        view = ChoreCompleteView(assignment_id=row["assignment_id"])
        try:
            bot.add_view(view, message_id=int(row["discord_message_id"]))
        except Exception as e:
            log.warning("Could not re-register view for message %s: %s",
                        row["discord_message_id"], e)

    log.info("Re-registered %d persistent view(s)", len(incomplete))

    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        log.info("Synced %d slash command(s)", len(synced))
    except Exception as e:
        log.error("Failed to sync commands: %s", e)

    # Schedule daily jobs (idempotent: replace_existing=True)
    from scheduler_jobs import run_daily_assignments, run_escalation_check

    scheduler_jobs.set_bot(bot)

    scheduler.add_job(
        run_daily_assignments,
        trigger="cron",
        hour=8,
        minute=0,
        id="daily_assignments",
        replace_existing=True,
    )
    scheduler.add_job(
        run_escalation_check,
        trigger="cron",
        hour=9,
        minute=0,
        id="daily_escalation",
        replace_existing=True,
    )

    if not scheduler.running:
        scheduler.start()
        log.info("Scheduler started")


async def main():
    async with bot:
        for cog in COGS:
            await bot.load_extension(cog)
            log.info("Loaded cog: %s", cog)

        # Start calendar server in the same event loop
        import cal_server
        cal_port = int(os.getenv("CAL_PORT", "8080"))
        await cal_server.start(host="127.0.0.1", port=cal_port)

        token = os.environ["DISCORD_BOT_TOKEN"]
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
