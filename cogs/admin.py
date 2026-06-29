import os

import discord
from discord import app_commands
from discord.ext import commands

from db import get_db
from rotation import log_command


def _is_admin(interaction: discord.Interaction) -> bool:
    return str(interaction.user.id) == os.environ.get("ADMIN_DISCORD_ID", "")


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    admin_group = app_commands.Group(name="admin", description="Admin commands")

    @admin_group.command(name="escalations", description="List all currently escalated assignments")
    async def admin_escalations(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return

        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/admin escalations")

        db = get_db()
        rows = db.execute("""
            SELECT c.chore_name, a.date_due, u.display_name, u.discord_id,
                   a.assignment_id, a.date_assigned
            FROM active_assignments a
            JOIN chores c ON c.chore_id = a.chore_id
            JOIN users u ON u.user_id = a.assigned_user_id
            WHERE a.is_escalated = 1 AND a.is_completed = 0
            ORDER BY a.date_due
        """).fetchall()

        if not rows:
            await interaction.response.send_message(
                "No escalated assignments. ✅", ephemeral=True)
            return

        lines = []
        for r in rows:
            lines.append(
                f"⚠️ **{r['chore_name']}** — assigned to <@{r['discord_id']}> "
                f"({r['display_name']}) — due {r['date_due']} "
                f"(assigned {r['date_assigned']})"
            )

        embed = discord.Embed(
            title="⚠️ Escalated Assignments",
            description="\n".join(lines),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


    @admin_group.command(name="run-assignments", description="[Admin] Manually trigger today's assignment run")
    async def admin_run_assignments(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return

        log_command(str(interaction.user.id), interaction.user.display_name,
                    "/admin run-assignments")

        await interaction.response.defer(ephemeral=True)

        from scheduler_jobs import run_daily_assignments
        await run_daily_assignments()

        await interaction.followup.send("Assignment run complete.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
