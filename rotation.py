import sqlite3
from datetime import date, timedelta
from typing import Optional
import json

from db import get_db


def get_eligible_users(chore_id: int) -> list[sqlite3.Row]:
    db = get_db()
    return db.execute("""
        SELECT user_id, rotation_order, discord_id, display_name
        FROM users
        WHERE is_active = 1
          AND is_removed = 0
          AND user_id NOT IN (
              SELECT user_id FROM chore_exclusions WHERE chore_id = ?
          )
        ORDER BY rotation_order
    """, (chore_id,)).fetchall()


def get_next_user(chore_id: int, last_user_id: Optional[int]) -> sqlite3.Row:
    eligible = get_eligible_users(chore_id)
    if not eligible:
        raise ValueError(f"No eligible users for chore {chore_id}")

    ids = [r["user_id"] for r in eligible]
    if last_user_id is None or last_user_id not in ids:
        return eligible[0]

    idx = ids.index(last_user_id)
    return eligible[(idx + 1) % len(ids)]


def create_assignment(chore_id: int, user_id: int, today: Optional[date] = None,
                      date_due: Optional[date] = None) -> int:
    db = get_db()
    if today is None:
        today = date.today()
    due = date_due if date_due is not None else today + timedelta(days=1)

    cur = db.execute("""
        INSERT INTO active_assignments
            (chore_id, assigned_user_id, date_assigned, date_due, is_completed, is_escalated)
        VALUES (?, ?, ?, ?, 0, 0)
    """, (chore_id, user_id, today.isoformat(), due.isoformat()))
    assignment_id = cur.lastrowid

    db.execute("UPDATE chores SET last_assigned_user_id = ? WHERE chore_id = ?",
               (user_id, chore_id))

    _audit(assignment_id, chore_id, user_id, "assigned")
    db.commit()
    return assignment_id


def complete_assignment(assignment_id: int, completing_user_id: int) -> None:
    db = get_db()
    row = db.execute(
        "SELECT chore_id, assigned_user_id FROM active_assignments WHERE assignment_id = ?",
        (assignment_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Assignment {assignment_id} not found")

    db.execute("""
        UPDATE active_assignments
        SET is_completed = 1, is_escalated = 0
        WHERE assignment_id = ?
    """, (assignment_id,))

    _audit(assignment_id, row["chore_id"], completing_user_id, "completed")
    db.commit()


def reassign_open_assignments(from_user_id: int, reason: str = "reassigned") -> list[dict]:
    """Reassign all open assignments from a user. Returns list of reassignment info."""
    db = get_db()
    open_assignments = db.execute("""
        SELECT a.assignment_id, a.chore_id, a.discord_message_id
        FROM active_assignments a
        WHERE a.assigned_user_id = ? AND a.is_completed = 0
    """, (from_user_id,)).fetchall()

    results = []
    for row in open_assignments:
        chore_id = row["chore_id"]
        try:
            next_user = get_next_user(chore_id, from_user_id)
        except ValueError:
            continue

        new_id = create_assignment(chore_id, next_user["user_id"])
        _audit(row["assignment_id"], chore_id, from_user_id, reason,
               notes=f"reassigned to user_id={next_user['user_id']}")

        # Mark old assignment as completed so it doesn't escalate further
        db.execute("UPDATE active_assignments SET is_completed = 1 WHERE assignment_id = ?",
                   (row["assignment_id"],))
        db.commit()

        results.append({
            "old_assignment_id": row["assignment_id"],
            "new_assignment_id": new_id,
            "chore_id": chore_id,
            "new_user": dict(next_user),
            "old_message_id": row["discord_message_id"],
        })

    return results


def _audit(assignment_id: int, chore_id: int, user_id: int,
           event_type: str, notes: str = None) -> None:
    from datetime import datetime, timezone
    db = get_db()
    db.execute("""
        INSERT INTO assignment_audit
            (assignment_id, chore_id, user_id, event_type, event_time, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (assignment_id, chore_id, user_id, event_type,
          datetime.now(timezone.utc).isoformat(), notes))


def log_command(discord_id: str, display_name: str, command: str, args: dict = None) -> None:
    from datetime import datetime, timezone
    import json
    db = get_db()
    db.execute("""
        INSERT INTO command_log (discord_id, display_name, command, args, invoked_at)
        VALUES (?, ?, ?, ?, ?)
    """, (discord_id, display_name, command,
          json.dumps(args) if args else None,
          datetime.now(timezone.utc).isoformat()))
    db.commit()
