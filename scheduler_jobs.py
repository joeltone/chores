"""APScheduler jobs: daily assignment creation and escalation checks."""

import os
import logging
from datetime import date, datetime, timezone

import discord

log = logging.getLogger(__name__)

_bot: discord.Client | None = None


def set_bot(bot: discord.Client) -> None:
    global _bot
    _bot = bot


async def run_daily_assignments() -> None:
    """Create new assignments for chores due today, grouped into per-user threads."""
    bot = _bot
    from db import get_db
    from rotation import get_next_user, create_assignment
    from views import post_chores_thread

    db = get_db()
    today = date.today()
    channel_id = int(os.environ["DISCORD_CHANNEL_ID"])
    channel = bot.get_channel(channel_id)
    if channel is None:
        log.error("Could not find channel %s", channel_id)
        return

    chores = db.execute("""
        SELECT c.chore_id, c.chore_name, c.description, c.frequency_days,
               c.last_assigned_user_id,
               MAX(a.date_assigned) AS last_assigned_date
        FROM chores c
        LEFT JOIN active_assignments a ON a.chore_id = c.chore_id
        WHERE c.is_active = 1
        GROUP BY c.chore_id
    """).fetchall()

    # Collect assignments grouped by user before posting
    user_chores: dict[int, dict] = {}

    for chore in chores:
        chore_id = chore["chore_id"]

        open_assignment = db.execute("""
            SELECT 1 FROM active_assignments
            WHERE chore_id = ? AND is_completed = 0
        """, (chore_id,)).fetchone()
        if open_assignment:
            log.info("Skipping chore %s — has open incomplete assignment", chore_id)
            continue

        last_date_str = chore["last_assigned_date"]
        if last_date_str:
            last_date = date.fromisoformat(last_date_str)
            if (today - last_date).days < chore["frequency_days"]:
                continue

        try:
            next_user = get_next_user(chore_id, chore["last_assigned_user_id"])
        except ValueError as e:
            log.warning("Cannot assign chore %s: %s", chore_id, e)
            continue

        assignment_id = create_assignment(chore_id, next_user["user_id"], today)
        row = db.execute(
            "SELECT date_due FROM active_assignments WHERE assignment_id = ?",
            (assignment_id,)).fetchone()

        uid = next_user["user_id"]
        if uid not in user_chores:
            user_chores[uid] = {"user": dict(next_user), "chores": []}
        user_chores[uid]["chores"].append({
            "assignment_id": assignment_id,
            "chore_name": chore["chore_name"],
            "description": chore["description"],
            "frequency_days": chore["frequency_days"],
            "date_due": row["date_due"] if row else str(today),
        })

    # Post one thread per user
    for uid, data in user_chores.items():
        await post_chores_thread(
            channel,
            data["user"]["discord_id"],
            data["user"]["display_name"],
            data["chores"],
            db,
        )
        log.info("Posted thread for %s with %d chore(s)",
                 data["user"]["display_name"], len(data["chores"]))


async def run_due_today_reminder() -> None:
    """Remind users about open assignments due today (no new assignment yet, not overdue)."""
    bot = _bot
    from db import get_db

    db = get_db()
    today = date.today().isoformat()
    channel_id = int(os.environ["DISCORD_CHANNEL_ID"])
    channel = bot.get_channel(channel_id)
    if channel is None:
        log.error("Could not find channel %s", channel_id)
        return

    due_today = db.execute("""
        SELECT c.chore_name, u.discord_id, u.display_name
        FROM active_assignments a
        JOIN chores c ON c.chore_id = a.chore_id
        JOIN users u ON u.user_id = a.assigned_user_id
        WHERE a.is_completed = 0 AND a.date_due = ?
        ORDER BY u.display_name, c.chore_name
    """, (today,)).fetchall()

    user_chores: dict[str, dict] = {}
    for row in due_today:
        discord_id = row["discord_id"]
        if discord_id not in user_chores:
            user_chores[discord_id] = {"display_name": row["display_name"], "chores": []}
        user_chores[discord_id]["chores"].append(row["chore_name"])

    for discord_id, data in user_chores.items():
        chore_list = ", ".join(f"**{name}**" for name in data["chores"])
        await channel.send(
            f"⏰ <@{discord_id}> reminder — due today ({today}): {chore_list}"
        )
        log.info("Sent due-today reminder to %s for %d chore(s)",
                 data["display_name"], len(data["chores"]))


async def run_escalation_check() -> None:
    bot = _bot
    """Escalate overdue assignments and ping admin."""
    from db import get_db

    db = get_db()
    today = date.today().isoformat()
    admin_id = os.environ.get("ADMIN_DISCORD_ID", "")
    channel_id = int(os.environ["DISCORD_CHANNEL_ID"])
    channel = bot.get_channel(channel_id)

    overdue = db.execute("""
        SELECT a.assignment_id, a.chore_id, a.assigned_user_id,
               a.date_due, c.chore_name, u.discord_id, u.display_name
        FROM active_assignments a
        JOIN chores c ON c.chore_id = a.chore_id
        JOIN users u ON u.user_id = a.assigned_user_id
        WHERE a.is_completed = 0
          AND a.date_due < ?
    """, (today,)).fetchall()

    for row in overdue:
        assignment_id = row["assignment_id"]

        db.execute("UPDATE active_assignments SET is_escalated = 1 WHERE assignment_id = ?",
                   (assignment_id,))

        # Audit: only write escalated event if not already escalated this cycle
        already = db.execute("""
            SELECT 1 FROM assignment_audit
            WHERE assignment_id = ? AND event_type = 'escalated'
              AND date(event_time) = date('now')
        """, (assignment_id,)).fetchone()

        if not already:
            db.execute("""
                INSERT INTO assignment_audit
                    (assignment_id, chore_id, user_id, event_type, event_time)
                VALUES (?, ?, ?, 'escalated', ?)
            """, (assignment_id, row["chore_id"], row["assigned_user_id"],
                  datetime.now(timezone.utc).isoformat()))

        db.commit()

        if channel and admin_id:
            await channel.send(
                f"⚠️ <@{admin_id}> — **{row['chore_name']}** assigned to "
                f"<@{row['discord_id']}> was due {row['date_due']} and is still incomplete."
            )

        log.info("Escalated assignment %s for chore %s", assignment_id, row["chore_name"])
