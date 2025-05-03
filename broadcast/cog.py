import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import asyncio
from ballsdex.core.models import GuildConfig
from ballsdex.settings import settings
from ballsdex.core.utils.utils import is_staff
from datetime import datetime, timedelta, timezone
import traceback
import math
import logging

# 設置日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Broadcast(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pages = {}  # 用於存儲分頁資訊

    async def cog_load(self):
        """當 cog 載入時執行"""
        # 確保機器人已準備好
        await self.bot.wait_until_ready()
        # 為所有伺服器獲取成員
        for guild in self.bot.guilds:
            try:
                await guild.fetch_members()
                logger.info(f"Fetched members for guild {guild.name}")
            except Exception as e:
                logger.error(f"Error fetching members for guild {guild.name}: {str(e)}")

    async def get_broadcast_channels(self):
        try:
            channels = set()
            async for config in GuildConfig.filter(enabled=True, spawn_channel__isnull=False):
                channels.add(config.spawn_channel)
            logger.info(f"Found {len(channels)} broadcast channels")
            return channels
        except Exception as e:
            logger.error(f"Error getting broadcast channels: {str(e)}")
            logger.error(traceback.format_exc())
            return set()

    async def get_member_count(self, guild):
        """獲取伺服器成員數"""
        try:
            # 確保我們有權限獲取成員列表
            if not guild.me.guild_permissions.view_channel:
                logger.warning(f"No permission to view members in guild {guild.name}")
                return 0
                
            # 直接使用 guild.member_count
            member_count = guild.member_count
            logger.info(f"Found {member_count} members in guild {guild.name}")
            return member_count
        except Exception as e:
            logger.error(f"Error in get_member_count: {str(e)}")
            logger.error(traceback.format_exc())
            return 0

    def create_embed(self, channel_list, total_stats, page, total_pages):
        """創建 embed 訊息"""
        try:
            embed = discord.Embed(
                title="球生成頻道列表",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            
            # 添加總體統計
            embed.add_field(
                name="總體統計",
                value=(
                    f"總頻道數：{total_stats['total_channels']} 個\n"
                    f"總成員數：{total_stats['total_members']:,} 人"
                ),
                inline=False
            )
            
            # 添加當前頁的頻道列表
            for channel_info in channel_list:
                embed.add_field(
                    name=channel_info['name'],
                    value=channel_info['value'],
                    inline=False
                )
            
            embed.set_footer(text=f"第 {page}/{total_pages} 頁")
            return embed
        except Exception as e:
            logger.error(f"Error creating embed: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    class PaginationView(discord.ui.View):
        def __init__(self, cog, channel_list, total_stats, timeout=180):
            super().__init__(timeout=timeout)
            self.cog = cog
            self.channel_list = channel_list
            self.total_stats = total_stats
            self.current_page = 1
            self.total_pages = math.ceil(len(channel_list) / 5)
            
            # 更新按鈕狀態
            self.update_buttons()
            
        def update_buttons(self):
            self.previous_page.disabled = self.current_page <= 1
            self.next_page.disabled = self.current_page >= self.total_pages
            
        @discord.ui.button(label="上一頁", style=discord.ButtonStyle.primary)
        async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.current_page > 1:
                self.current_page -= 1
                self.update_buttons()
                await self.update_message(interaction)
                
        @discord.ui.button(label="下一頁", style=discord.ButtonStyle.primary)
        async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.current_page < self.total_pages:
                self.current_page += 1
                self.update_buttons()
                await self.update_message(interaction)
                
        async def update_message(self, interaction: discord.Interaction):
            start_idx = (self.current_page - 1) * 5
            end_idx = start_idx + 5
            current_channels = self.channel_list[start_idx:end_idx]
            
            embed = self.cog.create_embed(current_channels, self.total_stats, self.current_page, self.total_pages)
            await interaction.response.edit_message(embed=embed, view=self)

    @app_commands.command(name="list_broadcast_channels", description="列出所有球生成頻道")
    @app_commands.default_permissions(administrator=True)
    async def list_broadcast_channels(self, interaction: discord.Interaction):
        if not is_staff(interaction):
            await interaction.response.send_message("您需要捷運球管理員權限才能使用此命令。")
            return

        try:
            channels = await self.get_broadcast_channels()
            if not channels:
                await interaction.response.send_message("目前沒有配置任何球生成頻道。")
                return

            await interaction.response.send_message("正在統計伺服器資訊，請稍候...")
            
            channel_list = []
            total_stats = {
                'total_channels': len(channels),
                'total_members': 0
            }
            
            logger.info(f"Processing {len(channels)} channels")
            
            for channel_id in channels:
                try:
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        guild = channel.guild
                        logger.info(f"Processing channel {channel.name} in guild {guild.name}")
                        
                        member_count = await self.get_member_count(guild)
                        total_stats['total_members'] += member_count
                        
                        channel_list.append({
                            'name': f"**{guild.name}**",
                            'value': (
                                f"└ 頻道：#{channel.name} (`{channel.id}`)\n"
                                f"└ 伺服器 ID：`{guild.id}`\n"
                                f"└ 成員：{member_count:,} 人"
                            )
                        })
                    else:
                        logger.warning(f"Channel {channel_id} not found")
                        channel_list.append({
                            'name': "未知頻道",
                            'value': f"ID: {channel_id}"
                        })
                except Exception as e:
                    logger.error(f"Error processing channel {channel_id}: {str(e)}")
                    logger.error(traceback.format_exc())
                    channel_list.append({
                        'name': "錯誤頻道",
                        'value': f"ID: {channel_id}"
                    })

            if not channel_list:
                await interaction.followup.send("無法獲取任何頻道資訊。")
                return

            try:
                # 分頁處理
                CHANNELS_PER_PAGE = 5
                total_pages = math.ceil(len(channel_list) / CHANNELS_PER_PAGE)
                
                logger.info(f"Creating pagination with {total_pages} pages")
                
                # 創建第一頁
                current_page = 1
                start_idx = (current_page - 1) * CHANNELS_PER_PAGE
                end_idx = start_idx + CHANNELS_PER_PAGE
                current_channels = channel_list[start_idx:end_idx]
                
                embed = self.create_embed(current_channels, total_stats, current_page, total_pages)
                
                # 創建分頁視圖
                view = self.PaginationView(self, channel_list, total_stats)
                
                # 發送訊息
                await interaction.followup.send(embed=embed, view=view)
                    
            except Exception as e:
                logger.error(f"Error sending channel list: {str(e)}")
                logger.error(traceback.format_exc())
                await interaction.followup.send("處理頻道列表時發生錯誤，請稍後再試。")
                
        except Exception as e:
            logger.error(f"Error in list_broadcast_channels: {str(e)}")
            logger.error(traceback.format_exc())
            await interaction.response.send_message("執行命令時發生錯誤，請稍後再試。")

    @app_commands.command(name="broadcast", description="向所有球生成頻道發送廣播訊息")
    @app_commands.default_permissions(administrator=True)
    async def broadcast(self, interaction: discord.Interaction, message: str):
        """向所有球生成頻道發送廣播訊息"""
        if not is_staff(interaction):
            await interaction.response.send_message("您需要捷運球管理員權限才能使用此命令。")
            return

        try:
            channels = await self.get_broadcast_channels()
            if not channels:
                await interaction.response.send_message("目前沒有配置任何球生成頻道。")
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
            
            for channel_id in channels:
                try:
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        await channel.send(broadcast_message)
                        success_count += 1
                    else:
                        fail_count += 1
                        failed_channels.append(f"未知頻道 (ID: {channel_id})")
                except Exception as e:
                    logger.error(f"Error broadcasting to channel {channel_id}: {str(e)}")
                    logger.error(traceback.format_exc())
                    fail_count += 1
                    if channel:
                        failed_channels.append(f"{channel.guild.name} - #{channel.name}")
                    else:
                        failed_channels.append(f"未知頻道 (ID: {channel_id})")
            
            result_message = f"廣播完成！\n成功發送: {success_count} 個頻道\n失敗: {fail_count} 個頻道"
            if failed_channels:
                result_message += "\n\n失敗的頻道：\n" + "\n".join(failed_channels)
            
            await interaction.followup.send(result_message)
                
        except Exception as e:
            logger.error(f"Error in broadcast: {str(e)}")
            logger.error(traceback.format_exc())
            await interaction.response.send_message("執行命令時發生錯誤，請稍後再試。") 
