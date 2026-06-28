import os
import discord
from discord import app_commands
from discord.ext import commands

from db import get_db
from rotation import reassign_open_assignments, log_command
from views import ChoreCompleteView, build_assignment_embed


def _is_admin(interaction: discord.Interaction) -> bool:
    admin_id = os.environ.get("ADMIN_DISCORD_ID", "")
    return str(interaction.user.id) == admin_id


class UsersCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    user_group = app_commands.Group(name="user", description="User management commands")

    @user_group.command(name="add", description="Add a user to the chore rotation")
    @app_commands.describe(member="The Discord user to add")
    async def user_add(self, interaction: discord.Interaction, member: discord.Member):
        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/user add", {"member": str(member.id)})

        db = get_db()
        existing = db.execute(
            "SELECT user_id, is_removed FROM users WHERE discord_id = ?",
            (str(member.id),)).fetchone()

        if existing and not existing["is_removed"]:
            await interaction.response.send_message(
                f"{member.display_name} is already in the rotation.", ephemeral=True)
            return

        max_order = db.execute(
            "SELECT COALESCE(MAX(rotation_order), -1) FROM users").fetchone()[0]

        if existing and existing["is_removed"]:
            db.execute("""
                UPDATE users SET is_removed = 0, is_active = 1,
                    rotation_order = ?, display_name = ?
                WHERE discord_id = ?
            """, (max_order + 1, member.display_name, str(member.id)))
        else:
            db.execute("""
                INSERT INTO users (discord_id, display_name, rotation_order, is_active, is_removed)
                VALUES (?, ?, ?, 1, 0)
            """, (str(member.id), member.display_name, max_order + 1))

        db.commit()
        await interaction.response.send_message(
            f"Added **{member.display_name}** to the rotation (position {max_order + 1}).")

    @user_group.command(name="pause", description="[Admin] Temporarily pause a user")
    @app_commands.describe(member="The user to pause")
    async def user_pause(self, interaction: discord.Interaction, member: discord.Member):
        if not _is_admin(interaction):
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return

        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/user pause", {"member": str(member.id)})

        db = get_db()
        row = db.execute(
            "SELECT user_id, is_active FROM users WHERE discord_id = ? AND is_removed = 0",
            (str(member.id),)).fetchone()

        if not row:
            await interaction.response.send_message(
                f"{member.display_name} is not in the rotation.", ephemeral=True)
            return
        if not row["is_active"]:
            await interaction.response.send_message(
                f"{member.display_name} is already paused.", ephemeral=True)
            return

        db.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (row["user_id"],))
        db.commit()

        await interaction.response.defer()
        reassignments = reassign_open_assignments(row["user_id"], reason="reassigned")
        await _notify_reassignments(interaction, reassignments, self.bot)

        await interaction.followup.send(
            f"**{member.display_name}** paused. "
            f"Reassigned {len(reassignments)} open task(s).")

    @user_group.command(name="reinstate", description="[Admin] Reinstate a paused user")
    @app_commands.describe(member="The user to reinstate")
    async def user_reinstate(self, interaction: discord.Interaction, member: discord.Member):
        if not _is_admin(interaction):
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return

        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/user reinstate", {"member": str(member.id)})

        db = get_db()
        row = db.execute(
            "SELECT user_id, is_active FROM users WHERE discord_id = ? AND is_removed = 0",
            (str(member.id),)).fetchone()

        if not row:
            await interaction.response.send_message(
                f"{member.display_name} is not in the rotation.", ephemeral=True)
            return
        if row["is_active"]:
            await interaction.response.send_message(
                f"{member.display_name} is already active.", ephemeral=True)
            return

        max_order = db.execute(
            "SELECT COALESCE(MAX(rotation_order), -1) FROM users").fetchone()[0]

        db.execute("""
            UPDATE users SET is_active = 1, rotation_order = ?
            WHERE user_id = ?
        """, (max_order + 1, row["user_id"]))
        db.commit()

        await interaction.response.send_message(
            f"**{member.display_name}** reinstated at end of rotation (position {max_order + 1}).")

    @user_group.command(name="remove", description="[Admin] Permanently remove a user")
    @app_commands.describe(member="The user to remove")
    async def user_remove(self, interaction: discord.Interaction, member: discord.Member):
        if not _is_admin(interaction):
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return

        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/user remove", {"member": str(member.id)})

        db = get_db()
        row = db.execute(
            "SELECT user_id FROM users WHERE discord_id = ? AND is_removed = 0",
            (str(member.id),)).fetchone()

        if not row:
            await interaction.response.send_message(
                f"{member.display_name} is not in the rotation.", ephemeral=True)
            return

        db.execute(
            "UPDATE users SET is_removed = 1, is_active = 0 WHERE user_id = ?",
            (row["user_id"],))
        db.commit()

        await interaction.response.defer()
        reassignments = reassign_open_assignments(row["user_id"], reason="reassigned")
        await _notify_reassignments(interaction, reassignments, self.bot)

        await interaction.followup.send(
            f"**{member.display_name}** permanently removed. "
            f"Reassigned {len(reassignments)} open task(s).")

    @user_group.command(name="list", description="List all active users and their rotation order")
    async def user_list(self, interaction: discord.Interaction):
        log_command(str(interaction.user.id), interaction.user.display_name, "/user list")

        db = get_db()
        users = db.execute("""
            SELECT discord_id, display_name, rotation_order, is_active
            FROM users WHERE is_removed = 0
            ORDER BY rotation_order
        """).fetchall()

        if not users:
            await interaction.response.send_message("No users in the rotation.", ephemeral=True)
            return

        lines = []
        for u in users:
            status = "⏸ paused" if not u["is_active"] else ""
            lines.append(
                f"`{u['rotation_order']}` <@{u['discord_id']}> — **{u['display_name']}** {status}"
            )

        embed = discord.Embed(title="👥 Rotation Order", description="\n".join(lines),
                              color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed)


async def _notify_reassignments(interaction: discord.Interaction, reassignments: list[dict],
                                 bot: discord.Client) -> None:
    from db import get_db
    db = get_db()
    channel_id = int(os.environ["DISCORD_CHANNEL_ID"])
    channel = bot.get_channel(channel_id)
    if not channel:
        return

    for r in reassignments:
        chore = db.execute(
            "SELECT chore_name, description, frequency_days FROM chores WHERE chore_id = ?",
            (r["chore_id"],)).fetchone()
        assign = db.execute(
            "SELECT date_due FROM active_assignments WHERE assignment_id = ?",
            (r["new_assignment_id"],)).fetchone()

        embed = build_assignment_embed(
            chore["chore_name"], chore["description"],
            r["new_user"]["discord_id"],
            assign["date_due"] if assign else "—",
            chore["frequency_days"],
        )
        view = ChoreCompleteView(assignment_id=r["new_assignment_id"])
        msg = await channel.send(embed=embed, view=view)

        db.execute("""
            UPDATE active_assignments SET discord_message_id = ?
            WHERE assignment_id = ?
        """, (str(msg.id), r["new_assignment_id"]))
        db.commit()


async def setup(bot: commands.Bot):
    await bot.add_cog(UsersCog(bot))
