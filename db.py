import sqlite3
from pathlib import Path
import os

_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = os.getenv("DB_PATH", "chores.db")
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id     TEXT    NOT NULL UNIQUE,
            display_name   TEXT    NOT NULL,
            rotation_order INTEGER NOT NULL,
            is_active      INTEGER NOT NULL DEFAULT 1,
            is_removed     INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS chores (
            chore_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            chore_name            TEXT    NOT NULL,
            description           TEXT,
            frequency_days        INTEGER NOT NULL,
            last_assigned_user_id INTEGER,
            is_active             INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(last_assigned_user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS chore_exclusions (
            chore_id INTEGER NOT NULL,
            user_id  INTEGER NOT NULL,
            reason   TEXT,
            PRIMARY KEY (chore_id, user_id),
            FOREIGN KEY(chore_id) REFERENCES chores(chore_id),
            FOREIGN KEY(user_id)  REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS active_assignments (
            assignment_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            chore_id         INTEGER NOT NULL,
            assigned_user_id INTEGER NOT NULL,
            date_assigned    TEXT    NOT NULL,
            date_due         TEXT    NOT NULL,
            is_completed     INTEGER NOT NULL DEFAULT 0,
            is_escalated     INTEGER NOT NULL DEFAULT 0,
            discord_message_id TEXT,
            FOREIGN KEY(chore_id)         REFERENCES chores(chore_id),
            FOREIGN KEY(assigned_user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS assignment_audit (
            audit_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            chore_id      INTEGER NOT NULL,
            user_id       INTEGER NOT NULL,
            event_type    TEXT    NOT NULL,
            event_time    TEXT    NOT NULL,
            notes         TEXT,
            FOREIGN KEY(assignment_id) REFERENCES active_assignments(assignment_id),
            FOREIGN KEY(chore_id)      REFERENCES chores(chore_id),
            FOREIGN KEY(user_id)       REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS command_log (
            log_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id   TEXT NOT NULL,
            display_name TEXT NOT NULL,
            command      TEXT NOT NULL,
            args         TEXT,
            invoked_at   TEXT NOT NULL
        );
    """)
    conn.commit()
