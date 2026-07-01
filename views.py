import discord
from datetime import datetime, timezone


class ChoreCompleteView(discord.ui.View):
    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.assignment_id = assignment_id
        btn = discord.ui.Button(
            label="✅ Mark Completed",
            style=discord.ButtonStyle.success,
            custom_id=f"complete_chore_{assignment_id}",
        )
        btn.callback = self.complete_callback
        self.add_item(btn)

    async def complete_callback(self, interaction: discord.Interaction):
        from rotation import complete_assignment, get_db

        db = get_db()
        row = db.execute("""
            SELECT a.is_completed, a.chore_id, u.display_name, u.discord_id,
                   c.chore_name, a.assigned_user_id
            FROM active_assignments a
            JOIN users u ON u.user_id = a.assigned_user_id
            JOIN chores c ON c.chore_id = a.chore_id
            WHERE a.assignment_id = ?
        """, (self.assignment_id,)).fetchone()

        if not row:
            await interaction.response.send_message(
                "Assignment not found.", ephemeral=True)
            return

        if row["is_completed"]:
            await interaction.response.send_message(
                "This chore was already marked complete.", ephemeral=True)
            return

        complete_assignment(self.assignment_id, row["assigned_user_id"])

        completer = interaction.user.display_name
        completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Edit original message: disable button, update embed
        disabled_view = discord.ui.View(timeout=None)
        done_btn = discord.ui.Button(
            label=f"Completed by {completer}",
            style=discord.ButtonStyle.secondary,
            custom_id=f"complete_chore_{self.assignment_id}_done",
            disabled=True,
        )
        disabled_view.add_item(done_btn)

        original_embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if original_embed:
            embed = original_embed.copy()
            embed.description = (
                (embed.description or "") +
                f"\n\n✅ Completed by **{completer}** at {completed_at}"
            )
            await interaction.message.edit(embed=embed, view=disabled_view)
        else:
            await interaction.message.edit(view=disabled_view)

        await interaction.response.send_message(
            f"Marked **{row['chore_name']}** as complete. Nice work!", ephemeral=True)


async def post_chores_thread(
    channel: discord.TextChannel,
    discord_id: str,
    display_name: str,
    chores: list[dict],
    db,
) -> None:
    """Post a per-user thread in the channel with one embed per chore."""
    from datetime import date as _date
    today = _date.today().strftime("%Y-%m-%d")
    n = len(chores)

    starter = await channel.send(
        f"🧹 **{display_name}** has {n} chore{'s' if n != 1 else ''} for {today}"
    )
    thread = await starter.create_thread(
        name=f"{display_name} – {today}",
        auto_archive_duration=4320,  # 3 days
    )

    for c in chores:
        embed = build_assignment_embed(
            c["chore_name"], c.get("description") or "",
            discord_id, c["date_due"], c["frequency_days"],
            is_reminder=c.get("is_reminder", False),
        )
        view = ChoreCompleteView(assignment_id=c["assignment_id"])
        msg = await thread.send(embed=embed, view=view)
        db.execute(
            "UPDATE active_assignments SET discord_message_id = ? WHERE assignment_id = ?",
            (str(msg.id), c["assignment_id"]),
        )
    db.commit()


def build_assignment_embed(chore_name: str, description: str,
                            discord_id: str, date_due: str,
                            frequency_days: int,
                            is_reminder: bool = False) -> discord.Embed:
    title = f"🔁 Still Pending: {chore_name}" if is_reminder else f"🧹 Chore Assigned: {chore_name}"
    embed = discord.Embed(
        title=title,
        description=description or "",
        color=discord.Color.blue(),
    )
    embed.add_field(name="Assigned To", value=f"<@{discord_id}>", inline=True)
    embed.add_field(name="Due", value=date_due, inline=True)
    freq_label = (
        "Daily" if frequency_days == 1
        else f"Every {frequency_days} days"
    )
    embed.add_field(name="Frequency", value=freq_label, inline=True)
    return embed
