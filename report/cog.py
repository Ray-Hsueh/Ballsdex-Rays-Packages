import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import random
import time
from datetime import datetime

REPORT_CHANNEL_ID = 1234567890123456789 #Put your report channel id here
REPORT_GUILD_ID = 1234567890123456789 #Put your report guild id here
REPORT_JSON_PATH = os.path.join(os.path.dirname(__file__), "reports.json")

REPORT_TYPES = [
    ("Violation Report", "violation"),
    ("Bug Report", "bug"),
    ("Suggestion", "suggestion"),
    ("Other", "other"),
]

def load_reports():
    if not os.path.exists(REPORT_JSON_PATH):
        return {}
    with open(REPORT_JSON_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}

def save_reports(data):
    with open(REPORT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def generate_report_id(existing_ids):
    while True:
        rid = str(random.randint(100000, 999999))
        if rid not in existing_ids:
            return rid

class ReportCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.report_messages = {}

    @app_commands.command(name="report", description="Report issues or suggestions to the backend server")
    @app_commands.describe(
        report_type="Select report type",
        content="Please describe your issue or suggestion in detail"
    )
    @app_commands.choices(
        report_type=[app_commands.Choice(name=label, value=value) for label, value in REPORT_TYPES]
    )
    async def report(self, interaction: discord.Interaction, report_type: app_commands.Choice[str], content: str):
        reports = load_reports()
        report_id = generate_report_id(reports.keys())
        now = datetime.utcnow().isoformat()
        reports[report_id] = {
            "user_id": interaction.user.id,
            "user_name": str(interaction.user),
            "type": report_type.name,
            "type_value": report_type.value,
            "content": content,
            "time": now,
            "replied": False,
            "reply_time": None,
            "reply_by": None,
        }
        save_reports(reports)

        embed = discord.Embed(
            title=f"New User Report Received (ID: {report_id})",
            color=discord.Color.orange()
        )
        embed.add_field(name="Report Type", value=report_type.name, inline=False)
        embed.add_field(name="Content", value=content, inline=False)
        embed.add_field(name="Report ID", value=report_id, inline=False)
        embed.add_field(name="Status", value="Pending", inline=False)
        embed.set_footer(text=f"From {interaction.user} ({interaction.user.id})")
        embed.timestamp = discord.utils.utcnow()

        guild = self.bot.get_guild(REPORT_GUILD_ID)
        if guild is not None:
            channel = guild.get_channel(REPORT_CHANNEL_ID)
            if channel and isinstance(channel, discord.TextChannel):
                message = await channel.send(embed=embed)
                self.report_messages[report_id] = message
                await interaction.response.send_message(f"✅ Report submitted successfully! Your report ID is {report_id}. You will be notified of any updates via DM.", ephemeral=True)
                try:
                    await interaction.user.send(
                        f"Hello, we have received your report (ID: {report_id}, Type: {report_type.name}). An administrator will process it.\nYou will be notified of any updates via DM. Thank you for your assistance!"
                    )
                except Exception:
                    pass
                return

        await interaction.response.send_message("❌ Report submission failed. Please contact an administrator.", ephemeral=True)

    @app_commands.command(name="reply_report", description="Admin reply to user reports")
    @app_commands.describe(
        report_id="Report ID to reply to (6 digits)",
        reply_content="Reply content to send"
    )
    async def reply_report(self, interaction: discord.Interaction, report_id: str, reply_content: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only administrators can use this command.", ephemeral=True)
            return
        reports = load_reports()
        report = reports.get(report_id)
        if not report:
            await interaction.response.send_message(f"❌ Report ID {report_id} not found.", ephemeral=True)
            return

        report["replied"] = True
        report["reply_time"] = datetime.utcnow().isoformat()
        report["reply_by"] = str(interaction.user)
        save_reports(reports)

        if report_id in self.report_messages:
            original_message = self.report_messages[report_id]
            original_embed = original_message.embeds[0]
            original_embed.color = discord.Color.green()
            for i, field in enumerate(original_embed.fields):
                if field.name == "Status":
                    original_embed.set_field_at(i, name="Status", value="Replied", inline=False)
                    break
            await original_message.edit(embed=original_embed)

        embed = discord.Embed(
            title=f"Admin Reply (Report ID: {report_id})",
            color=discord.Color.green()
        )
        embed.add_field(name="Report Type", value=report["type"], inline=False)
        embed.add_field(name="Original Content", value=report["content"], inline=False)
        embed.add_field(name="Admin Reply", value=reply_content, inline=False)
        embed.set_footer(text=f"Replied by: {interaction.user} ({interaction.user.id})")
        embed.timestamp = discord.utils.utcnow()

        guild = self.bot.get_guild(REPORT_GUILD_ID)
        if guild is not None:
            channel = guild.get_channel(REPORT_CHANNEL_ID)
            if channel and isinstance(channel, discord.TextChannel):
                await channel.send(embed=embed)
                await interaction.response.send_message(f"✅ Reply sent successfully.", ephemeral=True)
                return

        await interaction.response.send_message("❌ Reply failed. Please contact an administrator.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ReportCog(bot)) 