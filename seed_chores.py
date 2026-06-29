"""One-time script to restore chores into the database."""

import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "data/chores.db")

CHORES = [
    # (name, frequency_days)
    ("Clean Downstairs Bathroom Sink", 7),
    ("Clean Downstairs Bathroom Toilet", 7),
    ("Clean Pasqualle's bathroom sink", 7),
    ("Clean Pasqualle's bathroom toilet", 7),
    ("Clean Upstairs Bathroom Sink", 7),
    ("Clean Upstairs Bathroom Toilet", 7),
    ("Clean Upstairs Bathroom Tub", 7),
    ("Mop Alec's office", 28),
    ("Mop Cal's office", 28),
    ("Mop Entrance", 28),
    ("Mop Pasqualle's bathroom", 28),
    ("Mop kitchen", 14),
    ("Mop living room", 28),
    ("Mop upstairs hall and stairs", 28),
    ("Replace Upstairs Bathroom Towels", 7),
    ("Sweep or Vacuum Cal's Office", 7),
    ("Sweep or vacuum Alec's office", 7),
    ("Sweep or vacuum Pasqualle's bathroom", 7),
    ("Sweep or vacuum kitchen", 3),
    ("Sweep or vacuum living room", 7),
    ("Sweep or vacuum upstairs hall and stairs", 7),
    ("Tidy Alec's office", 3),
    ("Tidy Cal's office", 3),
    ("Tidy Downstairs Bathroom", 3),
    ("Tidy Entrance", 7),
    ("Tidy Pasqualle's bathroom", 3),
    ("Tidy Upstairs Bathroom", 7),
    ("Tidy kitchen", 2),
    ("Tidy living room", 3),
    ("Tidy upstairs hall and stairs", 3),
    ("Vacuum or Sweep Entrance", 7),
    ("Wash dishes", 1),
]

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

existing = {r["chore_name"] for r in conn.execute("SELECT chore_name FROM chores WHERE is_active=1")}

inserted = 0
for name, freq in CHORES:
    if name in existing:
        print(f"SKIP (already exists): {name}")
        continue
    conn.execute(
        "INSERT INTO chores (chore_name, frequency_days, is_active) VALUES (?, ?, 1)",
        (name, freq)
    )
    print(f"INSERT: {name} (every {freq}d)")
    inserted += 1

conn.commit()
conn.close()
print(f"\nDone — inserted {inserted} chore(s), skipped {len(CHORES) - inserted}.")
