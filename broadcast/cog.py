import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import asyncio
from ballsdex.core.models import GuildConfig

class Broadcast(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_broadcast_channels(self):
        channels = set()
        async for config in GuildConfig.filter(enabled=True, spawn_channel__isnull=False):
            channels.add(config.spawn_channel)
        return channels

    @app_commands.command(name="broadcast", description="廣播訊息到所有球生成頻道")
    @app_commands.default_permissions(administrator=True)
    async def broadcast(self, interaction: discord.Interaction, message: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("您需要管理員權限才能使用此命令。")
            return

        await interaction.response.send_message("開始廣播訊息...")
        
        success_count = 0
        fail_count = 0
        failed_channels = []
        
        # 創建公告訊息
        broadcast_message = (
            "🔔 **系統公告** 🔔\n"
            "------------------------\n"
            f"{message}\n"
            "------------------------\n"
            f"*由 {interaction.user.name} 發送*"
        )
        
        for channel_id in await self.get_broadcast_channels():
            try:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    await channel.send(broadcast_message)
                    success_count += 1
                else:
                    fail_count += 1
                    failed_channels.append(f"未知頻道 (ID: {channel_id})")
            except Exception as e:
                fail_count += 1
                if channel:
                    failed_channels.append(f"{channel.guild.name} - #{channel.name}")
                else:
                    failed_channels.append(f"未知頻道 (ID: {channel_id})")
                print(f"Error broadcasting to channel {channel_id}: {e}")
        
        result_message = f"廣播完成！\n成功發送: {success_count} 個頻道\n失敗: {fail_count} 個頻道"
        if failed_channels:
            result_message += "\n\n失敗的頻道：\n" + "\n".join(failed_channels)
        
        await interaction.followup.send(result_message)

    @app_commands.command(name="list_broadcast_channels", description="列出所有球生成頻道")
    @app_commands.default_permissions(administrator=True)
    async def list_broadcast_channels(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("您需要管理員權限才能使用此命令。")
            return

        channels = await self.get_broadcast_channels()
        if not channels:
            await interaction.response.send_message("目前沒有配置任何球生成頻道。")
            return

        channel_list = []
        for channel_id in channels:
            channel = self.bot.get_channel(channel_id)
            if channel:
                channel_list.append(f"{channel.guild.name} - #{channel.name}")
            else:
                channel_list.append(f"未知頻道 (ID: {channel_id})")

        await interaction.response.send_message(
            "球生成頻道列表：\n" + "\n".join(channel_list)
        ) 