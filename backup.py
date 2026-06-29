"""Back up production SQLite databases to a timestamped local folder.

Handles WAL-mode databases correctly via Python's sqlite3 backup API.
Keeps the most recent KEEP_DAYS daily backups and removes older ones.
"""

import sqlite3
import shutil
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

SRC_DIR = Path("/opt/chore-bot/data")
DEST_DIR = Path("/home/joel/projects/chores/backups")
KEEP_DAYS = 14
DBS = ["chores.db", "jobs.db"]


def backup_db(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(dest)
    with dst_conn:
        src_conn.backup(dst_conn)
    src_conn.close()
    dst_conn.close()


def prune_old_backups() -> int:
    cutoff = date.today() - timedelta(days=KEEP_DAYS)
    removed = 0
    for d in sorted(DEST_DIR.iterdir()):
        if not d.is_dir():
            continue
        try:
            folder_date = date.fromisoformat(d.name)
        except ValueError:
            continue
        if folder_date < cutoff:
            shutil.rmtree(d)
            removed += 1
    return removed


def main() -> None:
    today = date.today().isoformat()
    dest_dir = DEST_DIR / today

    errors = []
    for db_name in DBS:
        src = SRC_DIR / db_name
        if not src.exists():
            print(f"SKIP: {src} does not exist")
            continue
        dest = dest_dir / db_name
        try:
            backup_db(src, dest)
            size = dest.stat().st_size
            print(f"OK: {db_name} → {dest} ({size:,} bytes)")
        except Exception as exc:
            print(f"ERROR: {db_name}: {exc}", file=sys.stderr)
            errors.append(db_name)

    removed = prune_old_backups()
    if removed:
        print(f"Pruned {removed} backup(s) older than {KEEP_DAYS} days")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
