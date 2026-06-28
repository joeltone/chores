"""APScheduler jobs: daily assignment creation and escalation checks."""

import os
import logging
from datetime import date, datetime, timezone

import discord

log = logging.getLogger(__name__)


async def run_daily_assignments(bot: discord.Client) -> None:
    """Create new assignments for chores due today."""
    from db import get_db
    from rotation import get_next_user, create_assignment
    from views import ChoreCompleteView, build_assignment_embed

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

    for chore in chores:
        chore_id = chore["chore_id"]

        # Check if there's an open escalated assignment — skip new cycle
        escalated = db.execute("""
            SELECT 1 FROM active_assignments
            WHERE chore_id = ? AND is_completed = 0 AND is_escalated = 1
        """, (chore_id,)).fetchone()
        if escalated:
            log.info("Skipping chore %s — has open escalated assignment", chore_id)
            continue

        last_date_str = chore["last_assigned_date"]
        if last_date_str:
            last_date = date.fromisoformat(last_date_str)
            days_since = (today - last_date).days
            if days_since < chore["frequency_days"]:
                continue

        try:
            next_user = get_next_user(chore_id, chore["last_assigned_user_id"])
        except ValueError as e:
            log.warning("Cannot assign chore %s: %s", chore_id, e)
            continue

        assignment_id = create_assignment(chore_id, next_user["user_id"], today)

        due_date = (today.replace(day=today.day + 1)
                    if today.day < 28 else date(today.year, today.month + 1, 1))
        # Simpler: already computed in create_assignment; fetch it
        row = db.execute(
            "SELECT date_due FROM active_assignments WHERE assignment_id = ?",
            (assignment_id,)).fetchone()
        date_due = row["date_due"] if row else str(today)

        embed = build_assignment_embed(
            chore["chore_name"], chore["description"],
            next_user["discord_id"], date_due, chore["frequency_days"]
        )
        view = ChoreCompleteView(assignment_id=assignment_id)
        msg = await channel.send(embed=embed, view=view)

        db.execute("UPDATE active_assignments SET discord_message_id = ? WHERE assignment_id = ?",
                   (str(msg.id), assignment_id))
        db.commit()

        log.info("Assigned chore %s to %s (assignment %s)",
                 chore["chore_name"], next_user["display_name"], assignment_id)


async def run_escalation_check(bot: discord.Client) -> None:
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
