"""One-time script to set up chore exclusions.
Run AFTER all users have been added via /user add in Discord.
Logic: chores with specific people listed → everyone else is excluded.
"""

import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "data/chores.db")

# Chore → list of display name substrings who ARE allowed.
# Everyone not matched is excluded.
# Empty list = no restrictions (all users allowed).
ASSIGNMENTS = {
    "Clean Downstairs Bathroom Sink":       ["Rock Eater"],
    "Clean Downstairs Bathroom Toilet":     ["Rock Eater"],
    "Clean Pasqualle's bathroom sink":      ["Cal"],
    "Clean Pasqualle's bathroom toilet":    ["Cal"],
    "Clean Upstairs Bathroom Sink":         ["Morgy", "Patch"],
    "Clean Upstairs Bathroom Toilet":       ["Morgy", "Patch"],
    "Clean Upstairs Bathroom Tub":          ["Morgy", "Patch"],
    "Mop Alec's office":                    ["Rock Eater"],
    "Mop Cal's office":                     ["Morgy", "Patch", "Cal"],
    "Mop Entrance":                         [],
    "Mop Pasqualle's bathroom":             ["Cal"],
    "Mop kitchen":                          [],
    "Mop living room":                      [],
    "Mop upstairs hall and stairs":         [],
    "Replace Upstairs Bathroom Towels":     ["Morgy", "Patch"],
    "Sweep or Vacuum Entrance":             [],
    "Sweep or Vacuum Cal's Office":         ["Morgy", "Patch", "Cal"],
    "Sweep or vacuum Alec's office":        ["Rock Eater"],
    "Sweep or vacuum Pasqualle's bathroom": ["Cal"],
    "Sweep or vacuum kitchen":              [],
    "Sweep or vacuum living room":          [],
    "Sweep or vacuum upstairs hall and stairs": [],
    "Tidy Alec's office":                   ["Rock Eater"],
    "Tidy Cal's office":                    [],
    "Tidy Downstairs Bathroom":             ["Rock Eater"],
    "Tidy Entrance":                        [],
    "Tidy Pasqualle's bathroom":            ["Cal"],
    "Tidy Upstairs Bathroom":               ["Morgy", "Patch"],
    "Tidy kitchen":                         [],
    "Tidy living room":                     [],
    "Tidy upstairs hall and stairs":        [],
    "Wash dishes":                          ["Rock Eater", "Morgy", "Patch"],
}

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

users = conn.execute(
    "SELECT user_id, display_name FROM users WHERE is_removed = 0"
).fetchall()

if not users:
    print("ERROR: No users found. Add users via /user add in Discord first.")
    exit(1)

print("Found users:")
for u in users:
    print(f"  [{u['user_id']}] {u['display_name']}")
print()

def match_user(name_fragment, users):
    return [u for u in users if name_fragment.lower() in u["display_name"].lower()]

inserted = 0
skipped = 0
errors = []

for chore_name, allowed_fragments in ASSIGNMENTS.items():
    chore = conn.execute(
        "SELECT chore_id FROM chores WHERE chore_name = ? AND is_active = 1",
        (chore_name,)
    ).fetchone()

    if not chore:
        errors.append(f"Chore not found: '{chore_name}'")
        continue

    if not allowed_fragments:
        continue  # No restrictions

    # Resolve allowed users
    allowed_ids = set()
    for frag in allowed_fragments:
        matched = match_user(frag, users)
        if not matched:
            errors.append(f"No user matched '{frag}' for chore '{chore_name}'")
        for u in matched:
            allowed_ids.add(u["user_id"])

    # Exclude everyone not in allowed_ids
    for u in users:
        if u["user_id"] not in allowed_ids:
            existing = conn.execute(
                "SELECT 1 FROM chore_exclusions WHERE chore_id = ? AND user_id = ?",
                (chore["chore_id"], u["user_id"])
            ).fetchone()
            if existing:
                print(f"SKIP (already excluded): {u['display_name']} from '{chore_name}'")
                skipped += 1
            else:
                conn.execute(
                    "INSERT INTO chore_exclusions (chore_id, user_id) VALUES (?, ?)",
                    (chore["chore_id"], u["user_id"])
                )
                print(f"EXCLUDE: {u['display_name']} from '{chore_name}'")
                inserted += 1

conn.commit()
conn.close()

print(f"\nDone — {inserted} exclusion(s) added, {skipped} skipped.")
if errors:
    print("\nWARNINGS:")
    for e in errors:
        print(f"  ⚠ {e}")
