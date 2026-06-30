import os
from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from db import get_db
from rotation import get_next_user, create_assignment, log_command
from views import ChoreCompleteView, build_assignment_embed, post_chores_thread


def _is_admin(interaction: discord.Interaction) -> bool:
    return str(interaction.user.id) == os.environ.get("ADMIN_DISCORD_ID", "")


class ChoresCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    chore_group = app_commands.Group(name="chore", description="Chore management commands")

    @chore_group.command(name="add", description="Add a new chore")
    @app_commands.describe(
        name="Chore name",
        description="What needs to be done",
        frequency_days="How often (in days) to assign this chore",
    )
    async def chore_add(self, interaction: discord.Interaction,
                        name: str, frequency_days: int,
                        description: str = ""):
        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/chore add", {"name": name, "frequency_days": frequency_days})

        db = get_db()

        existing = db.execute(
            "SELECT 1 FROM chores WHERE is_active = 1 AND LOWER(chore_name) = LOWER(?)",
            (name,)
        ).fetchone()
        if existing:
            await interaction.response.send_message(
                f"A chore named **{name}** already exists.", ephemeral=True)
            return

        db.execute("""
            INSERT INTO chores (chore_name, description, frequency_days, is_active)
            VALUES (?, ?, ?, 1)
        """, (name, description, frequency_days))
        db.commit()

        await interaction.response.send_message(
            f"Chore **{name}** added (every {frequency_days} day(s)).")

    @chore_group.command(name="remove", description="Deactivate a chore")
    @app_commands.describe(chore_name="Name of the chore to remove")
    async def chore_remove(self, interaction: discord.Interaction, chore_name: str):
        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/chore remove", {"chore_name": chore_name})

        db = get_db()
        row = db.execute(
            "SELECT chore_id FROM chores WHERE chore_name = ? AND is_active = 1",
            (chore_name,)).fetchone()

        if not row:
            await interaction.response.send_message(
                f"No active chore named **{chore_name}**.", ephemeral=True)
            return

        db.execute("UPDATE chores SET is_active = 0 WHERE chore_id = ?", (row["chore_id"],))
        db.commit()
        await interaction.response.send_message(f"Chore **{chore_name}** deactivated.")

    @chore_group.command(name="reassign", description="[Admin] Reassign an open chore to the next person in rotation")
    @app_commands.describe(chore_name="Name of the chore to reassign")
    async def chore_reassign(self, interaction: discord.Interaction, chore_name: str):
        if not _is_admin(interaction):
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return

        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/chore reassign", {"chore_name": chore_name})

        db = get_db()
        chore = db.execute(
            "SELECT chore_id FROM chores WHERE chore_name = ? AND is_active = 1",
            (chore_name,)).fetchone()

        if not chore:
            await interaction.response.send_message(
                f"No active chore named **{chore_name}**.", ephemeral=True)
            return

        assignment = db.execute("""
            SELECT a.assignment_id, a.assigned_user_id, u.display_name
            FROM active_assignments a
            JOIN users u ON u.user_id = a.assigned_user_id
            WHERE a.chore_id = ? AND a.is_completed = 0
            ORDER BY a.assignment_id DESC
            LIMIT 1
        """, (chore["chore_id"],)).fetchone()

        if not assignment:
            await interaction.response.send_message(
                f"No open assignment found for **{chore_name}**.", ephemeral=True)
            return

        from rotation import get_next_user, create_assignment
        try:
            next_user = get_next_user(chore["chore_id"], assignment["assigned_user_id"])
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        # Close the old assignment
        db.execute("""
            UPDATE active_assignments SET is_completed = 1, is_escalated = 0
            WHERE assignment_id = ?
        """, (assignment["assignment_id"],))
        db.execute("""
            INSERT INTO assignment_audit
                (assignment_id, chore_id, user_id, event_type, event_time, notes)
            VALUES (?, ?, ?, 'reassigned', datetime('now'), ?)
        """, (assignment["assignment_id"], chore["chore_id"],
              assignment["assigned_user_id"],
              f"manually reassigned to {next_user['display_name']}"))
        db.commit()

        new_assignment_id = create_assignment(chore["chore_id"], next_user["user_id"])

        # Post to channel
        await interaction.response.defer()
        channel_id = int(os.environ["DISCORD_CHANNEL_ID"])
        channel = self.bot.get_channel(channel_id)
        if channel:
            row = db.execute(
                "SELECT date_due FROM active_assignments WHERE assignment_id = ?",
                (new_assignment_id,)).fetchone()
            chore_row = db.execute(
                "SELECT chore_name, description, frequency_days FROM chores WHERE chore_id = ?",
                (chore["chore_id"],)).fetchone()
            embed = build_assignment_embed(
                chore_row["chore_name"], chore_row["description"],
                next_user["discord_id"], row["date_due"], chore_row["frequency_days"],
            )
            view = ChoreCompleteView(assignment_id=new_assignment_id)
            msg = await channel.send(embed=embed, view=view)
            db.execute("UPDATE active_assignments SET discord_message_id = ? WHERE assignment_id = ?",
                       (str(msg.id), new_assignment_id))
            db.commit()

        await interaction.followup.send(
            f"**{chore_name}** reassigned from **{assignment['display_name']}** "
            f"to **{next_user['display_name']}**.", ephemeral=True)

    @chore_group.command(name="rename", description="Rename a chore")
    @app_commands.describe(old_name="Current chore name", new_name="New chore name")
    async def chore_rename(self, interaction: discord.Interaction,
                            old_name: str, new_name: str):
        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/chore rename", {"old_name": old_name, "new_name": new_name})

        db = get_db()
        row = db.execute(
            "SELECT chore_id FROM chores WHERE chore_name = ? AND is_active = 1",
            (old_name,)).fetchone()

        if not row:
            await interaction.response.send_message(
                f"No active chore named **{old_name}**.", ephemeral=True)
            return

        db.execute("UPDATE chores SET chore_name = ? WHERE chore_id = ?",
                   (new_name, row["chore_id"]))
        db.commit()
        await interaction.response.send_message(
            f"Renamed **{old_name}** to **{new_name}**.")

    @chore_group.command(name="exclude", description="Exclude a user from a specific chore")
    @app_commands.describe(member="The user to exclude", chore_name="The chore name")
    async def chore_exclude(self, interaction: discord.Interaction,
                             member: discord.Member, chore_name: str):
        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/chore exclude", {"member": str(member.id), "chore_name": chore_name})

        db = get_db()
        chore = db.execute(
            "SELECT chore_id FROM chores WHERE chore_name = ? AND is_active = 1",
            (chore_name,)).fetchone()
        user = db.execute(
            "SELECT user_id FROM users WHERE discord_id = ? AND is_removed = 0",
            (str(member.id),)).fetchone()

        if not chore:
            await interaction.response.send_message(
                f"No active chore **{chore_name}**.", ephemeral=True)
            return
        if not user:
            await interaction.response.send_message(
                f"{member.display_name} is not in the rotation.", ephemeral=True)
            return

        db.execute("""
            INSERT OR IGNORE INTO chore_exclusions (chore_id, user_id)
            VALUES (?, ?)
        """, (chore["chore_id"], user["user_id"]))
        db.commit()

        await interaction.response.send_message(
            f"**{member.display_name}** excluded from **{chore_name}**.")

    @chore_group.command(name="include", description="Remove a chore exclusion for a user")
    @app_commands.describe(member="The user", chore_name="The chore name")
    async def chore_include(self, interaction: discord.Interaction,
                             member: discord.Member, chore_name: str):
        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/chore include", {"member": str(member.id), "chore_name": chore_name})

        db = get_db()
        chore = db.execute(
            "SELECT chore_id FROM chores WHERE chore_name = ? AND is_active = 1",
            (chore_name,)).fetchone()
        user = db.execute(
            "SELECT user_id FROM users WHERE discord_id = ? AND is_removed = 0",
            (str(member.id),)).fetchone()

        if not chore or not user:
            await interaction.response.send_message("Chore or user not found.", ephemeral=True)
            return

        db.execute("""
            DELETE FROM chore_exclusions WHERE chore_id = ? AND user_id = ?
        """, (chore["chore_id"], user["user_id"]))
        db.commit()

        await interaction.response.send_message(
            f"**{member.display_name}** can now be assigned **{chore_name}**.")

    @chore_group.command(name="list", description="List all active chores")
    async def chore_list(self, interaction: discord.Interaction):
        log_command(str(interaction.user.id), interaction.user.display_name, "/chore list")

        db = get_db()
        rows = db.execute("""
            SELECT c.chore_name, c.frequency_days, u.display_name AS assignee
            FROM chores c
            LEFT JOIN users u ON u.user_id = c.last_assigned_user_id
            WHERE c.is_active = 1
            ORDER BY c.chore_name
        """).fetchall()

        if not rows:
            await interaction.response.send_message("No active chores.", ephemeral=True)
            return

        lines = []
        for r in rows:
            freq = "daily" if r["frequency_days"] == 1 else f"every {r['frequency_days']}d"
            assignee = r["assignee"] or "unassigned"
            lines.append(f"**{r['chore_name']}** ({freq}) — last: {assignee}")

        embed = discord.Embed(title="📋 Active Chores",
                              description="\n".join(lines),
                              color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

    @chore_group.command(name="matrix", description="Show which chores each user is in the rotation for")
    async def chore_matrix(self, interaction: discord.Interaction):
        log_command(str(interaction.user.id), interaction.user.display_name, "/chore matrix")

        db = get_db()
        users = db.execute("""
            SELECT user_id, discord_id, display_name, rotation_order, is_active
            FROM users WHERE is_removed = 0
            ORDER BY rotation_order
        """).fetchall()

        chores = db.execute("""
            SELECT chore_id, chore_name FROM chores WHERE is_active = 1 ORDER BY chore_name
        """).fetchall()

        if not users:
            await interaction.response.send_message("No users in the rotation.", ephemeral=True)
            return
        if not chores:
            await interaction.response.send_message("No active chores.", ephemeral=True)
            return

        total = len(chores)
        embed = discord.Embed(title="🗂️ Chore Matrix", color=discord.Color.blurple())

        for u in users:
            excluded_ids = {
                r["chore_id"] for r in db.execute(
                    "SELECT chore_id FROM chore_exclusions WHERE user_id = ?",
                    (u["user_id"],)
                ).fetchall()
            }
            excluded_names = [c["chore_name"] for c in chores if c["chore_id"] in excluded_ids]
            eligible_count = total - len(excluded_names)
            status = "⏸ " if not u["is_active"] else ""

            if excluded_names:
                exclusion_str = "\n*Excluded: " + ", ".join(excluded_names) + "*"
            else:
                exclusion_str = ""

            embed.add_field(
                name=f"{status}{u['display_name']} ({eligible_count}/{total} chores)",
                value=f"Position {u['rotation_order']}{exclusion_str}" or "​",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @chore_group.command(name="mine", description="Show your pending assignments")
    async def chore_mine(self, interaction: discord.Interaction):
        log_command(str(interaction.user.id), interaction.user.display_name, "/chore mine")

        db = get_db()
        user = db.execute(
            "SELECT user_id FROM users WHERE discord_id = ? AND is_removed = 0",
            (str(interaction.user.id),)).fetchone()

        if not user:
            await interaction.response.send_message(
                "You're not in the rotation.", ephemeral=True)
            return

        rows = db.execute("""
            SELECT c.chore_name, a.date_due, a.is_escalated
            FROM active_assignments a
            JOIN chores c ON c.chore_id = a.chore_id
            WHERE a.assigned_user_id = ? AND a.is_completed = 0
            ORDER BY a.date_due
        """, (user["user_id"],)).fetchall()

        if not rows:
            await interaction.response.send_message(
                "You have no pending chores. 🎉", ephemeral=True)
            return

        lines = []
        for r in rows:
            flag = " ⚠️ OVERDUE" if r["is_escalated"] else ""
            lines.append(f"**{r['chore_name']}** — due {r['date_due']}{flag}")

        embed = discord.Embed(title="📌 Your Pending Chores",
                              description="\n".join(lines),
                              color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @chore_group.command(name="export", description="Export a person's chore schedule as an .ics calendar file")
    @app_commands.describe(member="Who to export (defaults to you)")
    async def chore_export(self, interaction: discord.Interaction,
                           member: discord.Member = None):
        target = member or interaction.user
        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/chore export", {"member": str(target.id)})

        db = get_db()
        user = db.execute(
            "SELECT user_id, display_name FROM users WHERE discord_id = ? AND is_removed = 0",
            (str(target.id),)).fetchone()

        if not user:
            await interaction.response.send_message(
                f"{target.display_name} is not in the rotation.", ephemeral=True)
            return

        rows = db.execute("""
            SELECT c.chore_name, c.description, a.date_due, a.assignment_id
            FROM active_assignments a
            JOIN chores c ON c.chore_id = a.chore_id
            WHERE a.assigned_user_id = ? AND a.is_completed = 0
            ORDER BY a.date_due
        """, (user["user_id"],)).fetchall()

        if not rows:
            await interaction.response.send_message(
                f"{target.display_name} has no pending chores.", ephemeral=True)
            return

        ics = _build_ics(rows, user["display_name"])
        filename = f"{target.display_name.replace(' ', '_')}_chores.ics"
        file = discord.File(fp=__import__("io").BytesIO(ics.encode()), filename=filename)
        await interaction.response.send_message(
            f"📅 Chore schedule for **{target.display_name}** ({len(rows)} task(s))",
            file=file, ephemeral=True)

    @chore_group.command(name="upcoming", description="Show next 7 days of scheduled assignments")
    async def chore_upcoming(self, interaction: discord.Interaction):
        log_command(str(interaction.user.id), interaction.user.display_name, "/chore upcoming")

        db = get_db()
        today = date.today()
        end = today + timedelta(days=7)

        rows = db.execute("""
            SELECT c.chore_name, a.date_due, u.display_name, a.is_escalated, a.is_completed
            FROM active_assignments a
            JOIN chores c ON c.chore_id = a.chore_id
            JOIN users u ON u.user_id = a.assigned_user_id
            WHERE a.date_due BETWEEN ? AND ?
            ORDER BY a.date_due, c.chore_name
        """, (today.isoformat(), end.isoformat())).fetchall()

        if not rows:
            await interaction.response.send_message(
                "No assignments in the next 7 days.", ephemeral=True)
            return

        lines = []
        for r in rows:
            status = "✅" if r["is_completed"] else ("⚠️" if r["is_escalated"] else "🔲")
            lines.append(
                f"{status} **{r['chore_name']}** — {r['date_due']} — {r['display_name']}")

        embed = discord.Embed(title="📅 Upcoming Assignments (7 days)",
                              description="\n".join(lines),
                              color=discord.Color.teal())
        await interaction.response.send_message(embed=embed)

    @chore_group.command(name="seed", description="[Admin] Distribute all chores evenly")
    async def chore_seed(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return

        log_command(str(interaction.user.id), interaction.user.display_name, "/chore seed")
        await interaction.response.defer()

        db = get_db()
        chores = db.execute(
            "SELECT chore_id, chore_name, description, frequency_days, last_assigned_user_id "
            "FROM chores WHERE is_active = 1"
        ).fetchall()

        channel_id = int(os.environ["DISCORD_CHANNEL_ID"])
        channel = self.bot.get_channel(channel_id)

        from rotation import get_eligible_users
        from views import post_chores_thread
        today = date.today()
        seed_counts: dict[int, int] = {}

        # Phase 1: plan all assignments (chore → user) without writing to DB yet
        planned: list[dict] = []
        for chore in chores:
            chore_id = chore["chore_id"]
            eligible = get_eligible_users(chore_id)
            if not eligible:
                continue
            next_user = min(eligible, key=lambda u: seed_counts.get(u["user_id"], 0))
            seed_counts[next_user["user_id"]] = seed_counts.get(next_user["user_id"], 0) + 1
            planned.append({"chore": dict(chore), "user": dict(next_user)})

        # Phase 2: stagger due dates within each frequency group
        from collections import defaultdict
        by_freq: dict[int, list] = defaultdict(list)
        for p in planned:
            by_freq[p["chore"]["frequency_days"]].append(p)

        for freq, group in by_freq.items():
            n = len(group)
            for i, p in enumerate(group, start=1):
                days = max(1, round(freq * i / n))
                p["date_due"] = today + timedelta(days=days)

        # Phase 3: create assignments and group by user for thread posting
        user_chores: dict[int, dict] = {}
        for p in planned:
            chore = p["chore"]
            next_user = p["user"]
            assignment_id = create_assignment(
                chore["chore_id"], next_user["user_id"],
                today, date_due=p["date_due"],
            )
            uid = next_user["user_id"]
            if uid not in user_chores:
                user_chores[uid] = {"user": next_user, "chores": []}
            user_chores[uid]["chores"].append({
                "assignment_id": assignment_id,
                "chore_name": chore["chore_name"],
                "description": chore["description"],
                "frequency_days": chore["frequency_days"],
                "date_due": p["date_due"].isoformat(),
            })

        if channel:
            for uid, data in user_chores.items():
                await post_chores_thread(
                    channel,
                    data["user"]["discord_id"],
                    data["user"]["display_name"],
                    data["chores"],
                    db,
                )

        total = sum(len(d["chores"]) for d in user_chores.values())
        summary = ", ".join(
            f"{d['user']['display_name']}: {len(d['chores'])}"
            for d in sorted(user_chores.values(), key=lambda x: x["user"]["rotation_order"])
        )
        await interaction.followup.send(f"Seeded {total} chore(s). ({summary})")


def _build_ics(rows, display_name: str) -> str:
    from ical import build_ics
    return build_ics(rows, display_name)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChoresCog(bot))
