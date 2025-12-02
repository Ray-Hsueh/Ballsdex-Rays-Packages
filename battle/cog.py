import discord
from discord import app_commands
from discord.ext import commands
from typing import TYPE_CHECKING, Optional, cast, Dict
import random
import asyncio
from datetime import datetime

from ballsdex.core.models import BallInstance, Player
from ballsdex.packages.battle.menu import (
    BattleMenu, 
    FightInviteView, 
    FightActionView, 
    BulkAddView
)
from ballsdex.packages.battle.battling_user import BattlingUser
from ballsdex.settings import settings
from ballsdex.core.utils.transformers import (
    BallInstanceTransform,
    BallEnabledTransform,
    SpecialEnabledTransform,
)
from ballsdex.core.utils.sorting import SortingChoices, sort_balls

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


class Battle(commands.GroupCog):
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.battles = {}

    def get_battle(self, interaction: discord.Interaction) -> Optional[BattleMenu]:
        """
        Get the current battle in the server.
        """
        if not interaction.guild_id:
            return None
        battle = self.battles.get(interaction.guild_id)
        if battle and not battle.message:
            self.remove_battle(interaction.guild_id)
            return None
        return battle

    def remove_battle(self, guild_id: int):
        """
        Remove the battle for the specified server.
        """
        if guild_id in self.battles:
            battle = self.battles[guild_id]
            if battle.task and not battle.task.done():
                battle.task.cancel()
            del self.battles[guild_id]

    @app_commands.command()
    async def begin(self, interaction: discord.Interaction["BallsDexBot"], user: discord.User):
        """
        Start a battle with the specified user.

        Parameters
        ----------
        user: discord.User
            The user you want to battle against
        """
        try:
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send("Preparing battle, please wait...", ephemeral=True)
            if not interaction.guild_id:
                await interaction.response.send_message("Battles can only be conducted in servers.", ephemeral=True)
                return
                
            if user.bot:
                await interaction.response.send_message("Cannot battle against bots.", ephemeral=True)
                return
            if user.id == interaction.user.id:
                await interaction.response.send_message(
                    "Cannot battle against yourself.", ephemeral=True
                )
                return

            battle = self.get_battle(interaction)
            if battle:
                if interaction.user.id in [battle.battler1.user.id, battle.battler2.user.id]:
                    await interaction.response.send_message(
                        "You are already in an ongoing battle.", ephemeral=True
                    )
                    return
                elif user.id in [battle.battler1.user.id, battle.battler2.user.id]:
                    await interaction.response.send_message(
                        "The opponent is already in an ongoing battle.", ephemeral=True
                    )
                    return
                else:
                    await interaction.response.send_message(
                        "There is already an ongoing battle in this server.", ephemeral=True
                    )
                    return

            player1, _ = await Player.get_or_create(discord_id=interaction.user.id)
            player2, _ = await Player.get_or_create(discord_id=user.id)

            battle_menu = BattleMenu(
                self, interaction, BattlingUser(interaction.user, player1), BattlingUser(user, player2)
            )
            self.battles[interaction.guild_id] = battle_menu
            
            await battle_menu.start()
            
        except discord.NotFound:
            try:
                await interaction.followup.send("Battle started!", ephemeral=True)
            except:
                pass
        except Exception as e:
            print(f"Error occurred while starting battle: {str(e)}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("An error occurred while starting the battle, please try again later.", ephemeral=True)
                else:
                    await interaction.followup.send("An error occurred while starting the battle, please try again later.", ephemeral=True)
            except:
                pass

    @app_commands.command()
    async def add(
        self,
        interaction: discord.Interaction,
        ball: BallInstanceTransform,
    ):
        """
        Add a ball to the battle.

        Parameters
        ----------
        ball: BallInstanceTransform
            The ball you want to add to the battle
        """
        if not ball:
            return

        if not interaction.guild_id:
            await interaction.response.send_message("Battles can only be conducted in servers.", ephemeral=True)
            return

        battle = self.get_battle(interaction)
        if not battle:
            await interaction.response.send_message("There is no ongoing battle.", ephemeral=True)
            return

        battler = battle.get_battler(interaction.user)
        if not battler:
            await interaction.response.send_message("You are not a participant in this battle.", ephemeral=True)
            return

        if battler.locked:
            await interaction.response.send_message("You have already locked your selection, cannot add more balls.", ephemeral=True)
            return

        if ball.player.discord_id != interaction.user.id:
            await interaction.response.send_message(
                "You can only use your own balls in battle.", ephemeral=True
            )
            return

        if ball in battler.proposal:
            await interaction.response.send_message(
                "This ball is already in your battle lineup.", ephemeral=True
            )
            return

        battler.proposal.append(ball)
        await interaction.response.send_message(
            f"{ball.countryball.country} has been added to the battle lineup.", ephemeral=True
        )
        await battle.update_message()

    @app_commands.command()
    async def remove(
        self,
        interaction: discord.Interaction,
        ball: BallInstanceTransform,
    ):
        """
        Remove a ball from the battle.

        Parameters
        ----------
        ball: BallInstanceTransform
            The ball you want to remove from the battle
        """
        if not ball:
            return

        if not interaction.guild_id:
            await interaction.response.send_message("Battles can only be conducted in servers.", ephemeral=True)
            return

        battle = self.get_battle(interaction)
        if not battle:
            await interaction.response.send_message("There is no ongoing battle.", ephemeral=True)
            return

        battler = battle.get_battler(interaction.user)
        if not battler:
            await interaction.response.send_message("You are not a participant in this battle.", ephemeral=True)
            return

        if battler.locked:
            await interaction.response.send_message("You have already locked your selection, cannot remove balls.", ephemeral=True)
            return

        if ball not in battler.proposal:
            await interaction.response.send_message(
                "This ball is not in your battle lineup.", ephemeral=True
            )
            return

        battler.proposal.remove(ball)
        await interaction.response.send_message(
            f"{ball.countryball.country} has been removed from the battle lineup.", ephemeral=True
        )
        await battle.update_message()

    @app_commands.command()
    async def all(self, interaction: discord.Interaction):
        """
        Randomly select up to 10 balls to add to the battle.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Battles can only be conducted in servers.", ephemeral=True)
            return

        battle = self.get_battle(interaction)
        if not battle:
            await interaction.response.send_message("There is no ongoing battle.", ephemeral=True)
            return

        battler = battle.get_battler(interaction.user)
        if not battler:
            await interaction.response.send_message("You are not a participant in this battle.", ephemeral=True)
            return

        if battler.locked:
            await interaction.response.send_message("You have already locked your selection, cannot add more balls.", ephemeral=True)
            return

        player = await Player.get(discord_id=interaction.user.id)
        all_balls = await BallInstance.filter(player=player)

        if not all_balls:
            await interaction.response.send_message("You don't have any available balls.", ephemeral=True)
            return

        available_balls = [ball for ball in all_balls if ball not in battler.proposal]

        if not available_balls:
            await interaction.response.send_message("All your balls are already in the battle lineup.", ephemeral=True)
            return

        remaining_slots = battle.MAX_BALLS - len(battler.proposal)
        if remaining_slots <= 0:
            await interaction.response.send_message(
                f"Your battle lineup has reached the maximum limit ({battle.MAX_BALLS} balls).", ephemeral=True
            )
            return

        random.shuffle(available_balls)
        balls_to_add = available_balls[:remaining_slots]
        battler.proposal.extend(balls_to_add)
        battler.proposal = battler.proposal[:battle.MAX_BALLS]

        display_balls = balls_to_add[:10]
        more_balls = len(balls_to_add) - len(display_balls)
        display_message = "\n".join(f"{ball.countryball.country}" for ball in display_balls)
        if more_balls > 0:
            display_message += f"\n...and {more_balls} more."

        await interaction.response.send_message(
            f"Randomly selected the following balls for the battle lineup:\n{display_message}", ephemeral=True
        )
        await battle.update_message()

    @app_commands.command()
    async def best(self, interaction: discord.Interaction):
        """
        Select your strongest 10 balls to add to the battle.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Battles can only be conducted in servers.", ephemeral=True)
            return

        battle = self.get_battle(interaction)
        if not battle:
            await interaction.response.send_message("There is no ongoing battle.", ephemeral=True)
            return

        battler = battle.get_battler(interaction.user)
        if not battler:
            await interaction.response.send_message("You are not a participant in this battle.", ephemeral=True)
            return

        if battler.locked:
            await interaction.response.send_message("You have already locked your selection, cannot add more balls.", ephemeral=True)
            return

        player = await Player.get(discord_id=interaction.user.id)
        all_balls = await BallInstance.filter(player=player)

        if not all_balls:
            await interaction.response.send_message("You don't have any available balls.", ephemeral=True)
            return

        available_balls = [ball for ball in all_balls if ball not in battler.proposal]

        if not available_balls:
            await interaction.response.send_message("All your balls are already in the battle lineup.", ephemeral=True)
            return

        remaining_slots = battle.MAX_BALLS - len(battler.proposal)
        if remaining_slots <= 0:
            await interaction.response.send_message(
                f"Your battle lineup has reached the maximum limit ({battle.MAX_BALLS} balls).", ephemeral=True
            )
            return

        available_balls.sort(key=lambda x: x.attack + x.health, reverse=True)
        balls_to_add = available_balls[:remaining_slots]
        battler.proposal.extend(balls_to_add)
        battler.proposal = battler.proposal[:battle.MAX_BALLS]

        display_balls = balls_to_add[:10]
        more_balls = len(balls_to_add) - len(display_balls)
        display_message = "\n".join(
            f"{ball.countryball.country} (ATK:{ball.attack} HP:{ball.health} Total:{ball.attack + ball.health})" 
            for ball in display_balls
        )
        if more_balls > 0:
            display_message += f"\n...and {more_balls} more."

        await interaction.response.send_message(
            f"Selected the following strongest balls for the battle lineup:\n{display_message}", ephemeral=True
        )
        await battle.update_message()

    @bulk.command(name="add")
    async def bulk_add(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        countryball: BallEnabledTransform | None = None,
        sort: SortingChoices | None = None,
        special: SpecialEnabledTransform | None = None,
    ):
        """
        Add multiple balls to the battle using search filters.

        Parameters
        ----------
        countryball: Ball
            Filter by specific countryball.
        sort: SortingChoices
            Sort the balls (useful to see duplicates).
        special: Special
            Filter by special event background.
        """
        await interaction.response.defer(ephemeral=True, thinking=True)
        battle = self.get_battle(interaction)
        if not battle:
            await interaction.followup.send("There is no ongoing battle.", ephemeral=True)
            return

        battler = battle.get_battler(interaction.user)
        if not battler:
            await interaction.followup.send("You are not a participant in this battle.", ephemeral=True)
            return
        
        if battler.locked:
            await interaction.followup.send("You have already locked your selection, cannot add more balls.", ephemeral=True)
            return

        query = BallInstance.filter(player__discord_id=interaction.user.id)
        if countryball:
            query = query.filter(ball=countryball)
        if special:
            query = query.filter(special=special)
        if sort:
            query = sort_balls(sort, query)
        balls = await query
        if not balls:
            await interaction.followup.send(
                f"No {settings.plural_collectible_name} found matching criteria.", ephemeral=True
            )
            return
        
        view = BulkAddView(interaction, balls, self)
        await view.start(
            content=f"Select the {settings.plural_collectible_name} you want to add to the battle.\n"
            "Note: Selection clears when changing pages, but confirmed balls are saved."
        )
