import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import asyncio
from ballsdex.core.models import GuildConfig, BallInstance
from ballsdex.settings import settings
from ballsdex.core.utils.utils import is_staff
from datetime import datetime, timedelta, timezone
import traceback
import math
import logging

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

class Broadcast(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pages = {}

    async def cog_load(self):
        """Runs when cog loads"""
        await self.bot.wait_until_ready()
        pass

    async def get_broadcast_channels(self):
        try:
            channels = set()
            async for config in GuildConfig.filter(enabled=True, spawn_channel__isnull=False):
                channels.add(config.spawn_channel)
            return channels
        except Exception as e:
            logger.error(f"Error getting broadcast channels: {str(e)}")
            logger.error(traceback.format_exc())
            return set()

    async def get_member_count(self, guild):
        """Number of Acquired Server Members"""
        try:
            if not guild.me.guild_permissions.view_channel:
                logger.warning(f"No permission to view channel in guild {guild.name}")
                return 0
                
            return guild.member_count
                
        except Exception as e:
            logger.error(f"Error in get_member_count: {str(e)}")
            logger.error(traceback.format_exc())
            return 0

    def create_embed(self, channel_list, total_stats, page, total_pages):
        """Create embed message"""
        try:
            embed = discord.Embed(
                title="Ball generating channel list",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(
                name="Overall Statistics",
                value=(
                    f"Total number of channels:{total_stats['total_channels']}\n"
                    f"Total number of members:{total_stats['total_members']:,}"
                ),
                inline=False
            )
            
            for channel_info in channel_list:
                embed.add_field(
                    name=channel_info['name'],
                    value=channel_info['value'],
                    inline=False
                )
            
            embed.set_footer(text=f"Page {page}/{total_pages}")
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
            
            self.update_buttons()
            
        def update_buttons(self):
            self.previous_page.disabled = self.current_page <= 1
            self.next_page.disabled = self.current_page >= self.total_pages
            
        @discord.ui.button(label="Previous page", style=discord.ButtonStyle.primary)
        async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.current_page > 1:
                self.current_page -= 1
                self.update_buttons()
                await self.update_message(interaction)
                
        @discord.ui.button(label="Next Page", style=discord.ButtonStyle.primary)
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

    @app_commands.command(name="list_broadcast_channels", description="List all ball generating channels")
    @app_commands.default_permissions(administrator=True)
    async def list_broadcast_channels(self, interaction: discord.Interaction):
        if not is_staff(interaction):
            await interaction.response.send_message("You will need the Ball Administrator privileges to use this command.")
            return

        try:
            channels = await self.get_broadcast_channels()
            if not channels:
                await interaction.response.send_message("There are currently no ball generating channels configured.")
                return

            await interaction.response.send_message("Please wait while the server information is being counted...")
            
            channel_list = []
            total_stats = {
                'total_channels': len(channels),
                'total_members': 0
            }
            
            logger.info(f"Processing {len(channels)} channels")
            
            for channel_id in channels:
                try:
                    channel = self.bot.get_channel(channel_id)
                    if not channel:
                        logger.warning(f"Channel {channel_id} not found")
                        channel_list.append({
                            'name': "Unknown Channel",
                            'value': f"ID: {channel_id}"
                        })
                        continue
                        
                    guild = channel.guild
                    if not guild:
                        logger.warning(f"Guild not found for channel {channel_id}")
                        channel_list.append({
                            'name': "Unknown Server",
                            'value': f"Channel ID: {channel_id}"
                        })
                        continue
                        
                    logger.info(f"Processing channel {channel.name} in guild {guild.name}")
                    
                    member_count = await self.get_member_count(guild)
                    total_stats['total_members'] += member_count
                    
                    channel_list.append({
                        'name': f"**{guild.name}**",
                        'value': (
                            f"└ Channel: #{channel.name} (`{channel.id}`)\n"
                            f"└ Server ID: `{guild.id}`\n"
                            f"└ Number of Members: {member_count:,}"
                        )
                    })

                    total_catches = await BallInstance.filter(server_id=guild.id).count()
                    if total_catches >= 20:
                        recent_catches = await BallInstance.filter(
                            server_id=guild.id
                        ).order_by("-catch_date").limit(10).prefetch_related("player")

                        if recent_catches:
                            unique_catchers = len(set(ball.player.discord_id for ball in recent_catches))
                            if unique_catchers == 1:
                                player = recent_catches[0].player
                                channel_list[-1]['value'] += f"\n└ ⚠️ **The last 10 balls have all been caught by {player} **"

                except Exception as e:
                    logger.error(f"Error processing channel {channel_id}: {str(e)}")
                    logger.error(traceback.format_exc())
                    channel_list.append({
                        'name': "Error Channel",
                        'value': f"ID: {channel_id}"
                    })

            if not channel_list:
                await interaction.followup.send("No channel information is available.")
                return

            try:
                CHANNELS_PER_PAGE = 5
                total_pages = math.ceil(len(channel_list) / CHANNELS_PER_PAGE)
                
                logger.info(f"Creating pagination with {total_pages} pages")
                
                current_page = 1
                start_idx = (current_page - 1) * CHANNELS_PER_PAGE
                end_idx = start_idx + CHANNELS_PER_PAGE
                current_channels = channel_list[start_idx:end_idx]
                
                embed = self.create_embed(current_channels, total_stats, current_page, total_pages)
                
                view = self.PaginationView(self, channel_list, total_stats)
                
                await interaction.followup.send(embed=embed, view=view)
                    
            except Exception as e:
                logger.error(f"Error sending channel list: {str(e)}")
                logger.error(traceback.format_exc())
                await interaction.followup.send("An error occurred while processing the channel list, please try again later.")
                
        except Exception as e:
            logger.error(f"Error in list_broadcast_channels: {str(e)}")
            logger.error(traceback.format_exc())
            await interaction.response.send_message("An error occurred while executing the command, please try again later.")

    @app_commands.command(name="broadcast", description="Send broadcast messages to all ball-generating channels")
    @app_commands.default_permissions(administrator=True)
    async def broadcast(self, interaction: discord.Interaction, message: str):
        """Send broadcast messages to all ball-generating channels"""
        if not is_staff(interaction):
            await interaction.response.send_message("You will need the Ball Administrator privileges to use this command.")
            return

        try:
            channels = await self.get_broadcast_channels()
            if not channels:
                await interaction.response.send_message("There are currently no ball generating channels configured.")
                return

            await interaction.response.send_message("Start broadcasting messages...")
            
            success_count = 0
            fail_count = 0
            failed_channels = []
            
            broadcast_message = (
                "🔔 **System Announcement** 🔔\n"
                "------------------------\n"
                f"{message}\n"
                "------------------------\n"
                f"*Sent by {interaction.user.name}*"
            )
            
            for channel_id in channels:
                try:
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        await channel.send(broadcast_message)
                        success_count += 1
                    else:
                        fail_count += 1
                        failed_channels.append(f"Unknown Channel (ID: {channel_id})")
                except Exception as e:
                    logger.error(f"Error broadcasting to channel {channel_id}: {str(e)}")
                    logger.error(traceback.format_exc())
                    fail_count += 1
                    if channel:
                        failed_channels.append(f"{channel.guild.name} - #{channel.name}")
                    else:
                        failed_channels.append(f"Unknown Channel (ID: {channel_id})")
            
            result_message = f"Broadcast completed!\nSuccessfully sent: {success_count} channels\nFailure to send: {fail_count} channels"
            if failed_channels:
                result_message += "\n\nThe Failure Channel:\n" + "\n".join(failed_channels)
            
            await interaction.followup.send(result_message)
                
        except Exception as e:
            logger.error(f"Error in broadcast: {str(e)}")
            logger.error(traceback.format_exc())
            await interaction.response.send_message("An error occurred while executing the command, please try again later.") 
