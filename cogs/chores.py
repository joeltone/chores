import os
from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from db import get_db
from rotation import get_next_user, create_assignment, log_command
from views import ChoreCompleteView, build_assignment_embed


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
        count = 0

        for chore in chores:
            chore_id = chore["chore_id"]
            try:
                next_user = get_next_user(chore_id, chore["last_assigned_user_id"])
            except ValueError:
                continue

            assignment_id = create_assignment(chore_id, next_user["user_id"])

            row = db.execute(
                "SELECT date_due FROM active_assignments WHERE assignment_id = ?",
                (assignment_id,)).fetchone()

            if channel:
                embed = build_assignment_embed(
                    chore["chore_name"], chore["description"],
                    next_user["discord_id"],
                    row["date_due"] if row else "—",
                    chore["frequency_days"],
                )
                view = ChoreCompleteView(assignment_id=assignment_id)
                msg = await channel.send(embed=embed, view=view)
                db.execute("""
                    UPDATE active_assignments SET discord_message_id = ?
                    WHERE assignment_id = ?
                """, (str(msg.id), assignment_id))
                db.commit()

            count += 1

        await interaction.followup.send(f"Seeded {count} chore assignment(s).")


async def setup(bot: commands.Bot):
    await bot.add_cog(ChoresCog(bot))
