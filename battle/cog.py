import discord
from discord import app_commands
from discord.ext import commands
from typing import TYPE_CHECKING, Optional, cast, Dict
import random

from ballsdex.core.models import BallInstance, Player
from ballsdex.packages.battle.menu import (
    BattleMenu,
    BulkAddView,
)
from ballsdex.packages.battle.battling_user import BattlingUser
from ballsdex.settings import settings
from ballsdex.core.utils.transformers import BallInstanceTransform
from ballsdex.core.utils.sorting import SortingChoices, sort_balls
from ballsdex.core.utils.transformers import (
    BallEnabledTransform,
    SpecialEnabledTransform,
)

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


class Battle(commands.GroupCog):
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.battles = {}

    bulk = app_commands.Group(name="bulk", description="Bulk battle commands")

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
        Start a battle against the provided Discord user.

        Parameters
        ----------
        user: discord.User
            Target opponent.
        """
        try:
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send("Preparing the battle, please wait...", ephemeral=True)
            if not interaction.guild_id:
                await interaction.response.send_message("You can only battle inside a server.", ephemeral=True)
                return

            if user.bot:
                await interaction.response.send_message("You cannot battle bots.", ephemeral=True)
                return
            if user.id == interaction.user.id:
                await interaction.response.send_message(
                    "You cannot battle yourself.", ephemeral=True
                )
                return

            battle = self.get_battle(interaction)
            if battle:
                if interaction.user.id in [battle.battler1.user.id, battle.battler2.user.id]:
                    await interaction.response.send_message(
                        "You are already part of an active battle.", ephemeral=True
                    )
                    return
                elif user.id in [battle.battler1.user.id, battle.battler2.user.id]:
                    await interaction.response.send_message(
                        "Your opponent is already battling someone else.", ephemeral=True
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
                await interaction.followup.send("The battle has started!", ephemeral=True)
            except Exception:
                pass
        except Exception as e:
            print(f"Failed to start the battle: {str(e)}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("An error occurred while starting the battle. Please try again later.", ephemeral=True)
                else:
                    await interaction.followup.send("An error occurred while starting the battle. Please try again later.", ephemeral=True)
            except Exception:
                pass

    @app_commands.command()
    async def add(
        self,
        interaction: discord.Interaction,
        ball: BallInstanceTransform,
    ):
        """
        Add a single ball to your battle roster.

        Parameters
        ----------
        ball: BallInstanceTransform
            Ball to include.
        """
        if not ball:
            return

        if not interaction.guild_id:
            await interaction.response.send_message("You can only battle inside a server.", ephemeral=True)
            return

        battle = self.get_battle(interaction)
        if not battle:
            await interaction.response.send_message("There is no ongoing battle right now.", ephemeral=True)
            return

        battler = battle.get_battler(interaction.user)
        if not battler:
            await interaction.response.send_message("You are not part of this battle.", ephemeral=True)
            return

        if battler.locked:
            await interaction.response.send_message("Your selection is locked and cannot be updated.", ephemeral=True)
            return

        if ball.player.discord_id != interaction.user.id:
            await interaction.response.send_message(
                "You can only use your own balls in battle.", ephemeral=True
            )
            return

        if ball in battler.proposal:
            await interaction.response.send_message(
                "This ball is already in your battle roster.", ephemeral=True
            )
            return

        battler.proposal.append(ball)
        await interaction.response.send_message(
            f"{ball.countryball.country} has been added to your roster.", ephemeral=True
        )
        await battle.update_message()

    @app_commands.command()
    async def remove(
        self,
        interaction: discord.Interaction,
        ball: BallInstanceTransform,
    ):
        """
        Remove a ball from your battle roster.

        Parameters
        ----------
        ball: BallInstanceTransform
            Ball to remove.
        """
        if not ball:
            return

        if not interaction.guild_id:
            await interaction.response.send_message("You can only battle inside a server.", ephemeral=True)
            return

        battle = self.get_battle(interaction)
        if not battle:
            await interaction.response.send_message("There is no ongoing battle right now.", ephemeral=True)
            return

        battler = battle.get_battler(interaction.user)
        if not battler:
            await interaction.response.send_message("You are not part of this battle.", ephemeral=True)
            return

        if battler.locked:
            await interaction.response.send_message("Your selection is locked and cannot be updated.", ephemeral=True)
            return

        if ball not in battler.proposal:
            await interaction.response.send_message(
                "This ball is not in your battle roster.", ephemeral=True
            )
            return

        battler.proposal.remove(ball)
        await interaction.response.send_message(
            f"{ball.countryball.country} has been removed from your roster.", ephemeral=True
        )
        await battle.update_message()

    @app_commands.command()
    async def all(self, interaction: discord.Interaction):
        """
        Randomly add up to ten balls to your battle roster.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("You can only battle inside a server.", ephemeral=True)
            return

        battle = self.get_battle(interaction)
        if not battle:
            await interaction.response.send_message("There is no ongoing battle right now.", ephemeral=True)
            return

        battler = battle.get_battler(interaction.user)
        if not battler:
            await interaction.response.send_message("You are not part of this battle.", ephemeral=True)
            return

        if battler.locked:
            await interaction.response.send_message("Your selection is locked and cannot be updated.", ephemeral=True)
            return

        player = await Player.get(discord_id=interaction.user.id)
        all_balls = await BallInstance.filter(player=player)

        if not all_balls:
            await interaction.response.send_message("You do not own any usable balls.", ephemeral=True)
            return

        available_balls = [ball for ball in all_balls if ball not in battler.proposal]

        if not available_balls:
            await interaction.response.send_message("Every ball you own is already in your roster.", ephemeral=True)
            return

        remaining_slots = battle.MAX_BALLS - len(battler.proposal)
        if remaining_slots <= 0:
            await interaction.response.send_message(
                f"Your roster already reached the maximum of {battle.MAX_BALLS} balls.", ephemeral=True
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
            f"Randomly selected the following balls:\n{display_message}", ephemeral=True
        )
        await battle.update_message()

    @app_commands.command()
    async def best(self, interaction: discord.Interaction):
        """
        Add up to ten of your strongest balls to the battle.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("You can only battle inside a server.", ephemeral=True)
            return

        battle = self.get_battle(interaction)
        if not battle:
            await interaction.response.send_message("There is no ongoing battle right now.", ephemeral=True)
            return

        battler = battle.get_battler(interaction.user)
        if not battler:
            await interaction.response.send_message("You are not part of this battle.", ephemeral=True)
            return

        if battler.locked:
            await interaction.response.send_message("Your selection is locked and cannot be updated.", ephemeral=True)
            return

        player = await Player.get(discord_id=interaction.user.id)
        all_balls = await BallInstance.filter(player=player)

        if not all_balls:
            await interaction.response.send_message("You do not own any usable balls.", ephemeral=True)
            return

        available_balls = [ball for ball in all_balls if ball not in battler.proposal]

        if not available_balls:
            await interaction.response.send_message("Every ball you own is already in your roster.", ephemeral=True)
            return

        remaining_slots = battle.MAX_BALLS - len(battler.proposal)
        if remaining_slots <= 0:
            await interaction.response.send_message(
                f"Your roster already reached the maximum of {battle.MAX_BALLS} balls.", ephemeral=True
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
            f"The following strongest balls were selected:\n{display_message}", ephemeral=True
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
        Add many balls at once using search filters.

        Parameters
        ----------
        countryball: Ball
            Filter on a specific ball ID.
        sort: SortingChoices
            Sorting applied before display.
        special: Special
            Filter by special event flag.
        """
        await interaction.response.defer(ephemeral=True, thinking=True)
        battle = self.get_battle(interaction)
        if not battle:
            await interaction.followup.send("There is no ongoing battle right now.", ephemeral=True)
            return

        battler = battle.get_battler(interaction.user)
        if not battler:
            await interaction.followup.send("You are not part of this battle.", ephemeral=True)
            return
        
        if battler.locked:
            await interaction.followup.send("Your selection is locked and cannot be updated.", ephemeral=True)
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
                f"No {settings.plural_collectible_name} matched your filters.", ephemeral=True
            )
            return
        
        view = BulkAddView(interaction, balls, self)
        await view.start(
            content=f"Pick the {settings.plural_collectible_name} you want to bring to battle."
            " Switching pages clears the preview but keeps previously selected balls."
        )
