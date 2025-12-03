import asyncio
import discord
import random
from datetime import timedelta
from discord.ui import View, Button
from typing import TYPE_CHECKING, List, Optional, Set
from discord import app_commands

from ballsdex.packages.battle.battling_user import BattlingUser
from ballsdex.settings import settings
from ballsdex.core.models import BallInstance, Player
from ballsdex.core.utils.transformers import BallInstanceTransform
from ballsdex.core.utils.paginator import Pages
from ballsdex.core.utils import menus
from ballsdex.core.utils.buttons import ConfirmChoiceView

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot
    from ballsdex.packages.battle.cog import Battle as BattleCog


class BattleMenu:
    def __init__(
        self,
        cog: "Battle",
        interaction: discord.Interaction["BallsDexBot"],
        battler1: BattlingUser,
        battler2: BattlingUser,
    ):
        self.cog = cog
        self.bot = interaction.client
        self.channel: discord.TextChannel = interaction.channel
        self.battler1 = battler1
        self.battler2 = battler2
        self.embed = discord.Embed()
        self.task: Optional[asyncio.Task] = None
        self.current_view: BattleView = BattleView(self)
        self.message: Optional[discord.Message] = None
        self.is_cancelled = False
        self.MAX_BALLS = 10

    def get_battler(self, user: discord.User) -> Optional[BattlingUser]:
        if user.id == self.battler1.user.id:
            return self.battler1
        elif user.id == self.battler2.user.id:
            return self.battler2
        return None

    def can_add_ball(self, battler: BattlingUser) -> bool:
        """Return True if the battler still has room for more balls."""
        return len(battler.proposal) < self.MAX_BALLS

    def _generate_embed(self):
        self.embed.title = f"{settings.plural_collectible_name.title()} Battle"
        self.embed.color = discord.Colour.blurple()
        self.embed.description = (
            f"Pick the {settings.plural_collectible_name} you want to bring.\n"
            "Once you are ready, lock your selection using the button below.\n\n"
            f"*You can choose up to {self.MAX_BALLS} balls.*\n"
            "*This battle times out after 30 minutes.*"
        )
        self.embed.set_footer(
            text="This message refreshes every 15 seconds so you can keep adjusting your roster."
        )
        self.embed.clear_fields()

        def format_proposal(proposal):
            display_balls = proposal[:10]
            more_balls = len(proposal) - len(display_balls)
            display_message = "\n".join(
                f"- {self.bot.get_emoji(ball.countryball.emoji_id)} {ball.countryball.country} (#{ball.id:0X})"
                for ball in display_balls
            )
            if more_balls > 0:
                display_message += f"\n...and {more_balls} more."
            return display_message or "No balls selected yet."

        self.embed.add_field(
            name=f"{self.battler1.user.display_name} roster",
            value=format_proposal(self.battler1.proposal),
            inline=True,
        )
        self.embed.add_field(
            name=f"{self.battler2.user.display_name} roster",
            value=format_proposal(self.battler2.proposal),
            inline=True,
        )

    async def update_message(self):
        self._generate_embed()
        await self.message.edit(embed=self.embed)

    async def update_message_loop(self):
        """Background task that refreshes the battle embed every 15 seconds."""
        assert self.task
        start_time = discord.utils.utcnow()
        timeout_duration = timedelta(minutes=30)
        warning_duration = timedelta(minutes=25)
        warning_sent = False

        try:
            while True:
                current_time = discord.utils.utcnow()
                elapsed_time = current_time - start_time
                remaining_time = timeout_duration - elapsed_time

                if not warning_sent and elapsed_time >= warning_duration:
                    warning_sent = True
                    warning_msg = (
                        f"⚠️ This battle will time out in {int(remaining_time.total_seconds() / 60) + 1} minutes!\n"
                        "Please finalize your selection."
                    )
                    self.embed.description = warning_msg
                    self.embed.color = discord.Colour.orange()
                    try:
                        await self.message.edit(embed=self.embed)
                    except (discord.NotFound, discord.Forbidden):
                        pass

                if elapsed_time >= timeout_duration:
                    try:
                        if self.battler1.locked or self.battler2.locked:
                            winner = self.battler1.user if self.battler1.locked else self.battler2.user
                            loser = self.battler2.user if self.battler1.locked else self.battler1.user
                            self.embed.description = (
                                f"⏰ The battle timed out!\n\n"
                                f"{loser.mention} did not finish in time,\n"
                                f"so {winner.mention} wins by default."
                            )
                        else:
                            self.embed.description = (
                                f"⏰ The battle timed out!\n\n"
                                f"Neither player locked their roster in time,\n"
                                "so the battle was cancelled."
                            )
                        self.embed.color = discord.Colour.red()
                        await self.message.edit(embed=self.embed)
                        await self.cancel("The battle timed out.")
                        return
                    except (discord.NotFound, discord.Forbidden):
                        await self.cancel("The battle timed out but the message could not be updated.")
                        return

                try:
                    await self.update_message()
                except discord.NotFound:
                    await self.cancel("The battle message has been deleted.")
                    return
                except discord.Forbidden:
                    await self.cancel("The bot lacks permission to update the battle message.")
                    return
                except Exception as e:
                    print(f"Failed to refresh battle message: {str(e)}")
                    await asyncio.sleep(15)
                    continue

                await asyncio.sleep(15)
        except asyncio.CancelledError:
            return
        finally:
            if not self.message or self.message.flags.ephemeral:
                self.cog.remove_battle(self.channel.guild.id)

    async def start(self):
        """Initialize the battle message and controls."""
        try:
            self._generate_embed()
            self.message = await self.channel.send(
                content=f"🎮 {self.battler1.user.mention} has challenged {self.battler2.user.mention}!\n"
                "Use `/battle add` to pick specific balls or `/battle all` for random picks.\n"
                "Lock in your roster once you are satisfied.",
                embed=self.embed,
                view=self.current_view,
                allowed_mentions=discord.AllowedMentions(users=[self.battler1.user, self.battler2.user]),
            )
            self.task = self.bot.loop.create_task(self.update_message_loop())

            help_embed = discord.Embed(
                title="Battle instructions",
                description=(
                    "1. Use `/battle add` to choose exact balls.\n"
                    "2. Use `/battle all` to fill slots at random.\n"
                    "3. Use `/battle best` to pick your ten strongest balls.\n"
                    "4. Use `/battle bulk add` for the multi-select view.\n"
                    "5. Lock your selection once you are ready.\n"
                    "6. The battle begins automatically once both sides lock.\n"
                    "7. The session times out after 30 minutes.\n\n"
                    "📊 Damage model:\n"
                    "• Base damage equals attack.\n"
                    "• Defense mitigation removes up to 20% when HP greatly exceeds attack.\n"
                    "• Critical chance starts at 8% and scales with attack advantage.\n"
                    "• Critical damage deals 1.3x the mitigated damage (minimum attack * 1.3).\n"
                    "• Each log entry displays the applied mitigation."
                ),
                color=discord.Colour.blue()
            )
            help_embed.set_footer(text="Good luck!")
            try:
                await self.channel.send(embed=help_embed)
            except Exception:
                pass
                
        except Exception as e:
            print(f"Failed to start the battle: {str(e)}")
            raise

    async def cancel(self, reason: str = "The battle was cancelled."):
        """Cancel the battle immediately and disable controls."""
        try:
            self.is_cancelled = True
            if self.task and not self.task.done():
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass

            self.current_view.stop()
            for item in self.current_view.children:
                item.disabled = True

            self.embed.description = f"**{reason}**"
            self.embed.color = discord.Colour.red()
            
            if self.message:
                try:
                    await self.message.edit(content=None, embed=self.embed, view=self.current_view)
                except (discord.NotFound, discord.Forbidden):
                    pass
        except Exception as e:
            print(f"Failed to cancel the battle: {str(e)}")
        finally:
            self.cog.remove_battle(self.channel.guild.id)

    async def commence_battle(self):
        """Run the battle simulation between both players."""
        if not self.battler1.proposal and not self.battler2.proposal:
            await self._display_battle_results([], None, "Both players forgot to pick a team!")
            return
        if not self.battler1.proposal:
            await self._display_battle_results([], self.battler2.user, f"{self.battler1.user.display_name} did not select any balls!")
            return
        if not self.battler2.proposal:
            await self._display_battle_results([], self.battler1.user, f"{self.battler2.user.display_name} did not select any balls!")
            return

        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        self.embed.description = "🎮 The battle begins!\n\n"
        await self.message.edit(embed=self.embed)
        await asyncio.sleep(2)

        rounds = []
        battler1_wins = 0
        battler2_wins = 0
        
        for i in range(min(len(self.battler1.proposal), len(self.battler2.proposal))):
            ball1 = self.battler1.proposal[i]
            ball2 = self.battler2.proposal[i]
            round_result = await self._battle_round(i + 1, ball1, ball2)
            rounds.append(round_result)
            
            if round_result["winner"] == self.battler1.user:
                battler1_wins += 1
            elif round_result["winner"] == self.battler2.user:
                battler2_wins += 1
                
            score_msg = (
                f"\n\n📊 Score update:\n"
                f"{self.battler1.user.display_name}: {battler1_wins} wins\n"
                f"{self.battler2.user.display_name}: {battler2_wins} wins"
            )
            self.embed.description += score_msg
            await self.message.edit(embed=self.embed)
            await asyncio.sleep(4)

        if battler1_wins > battler2_wins:
            winner = self.battler1.user
        elif battler2_wins > battler1_wins:
            winner = self.battler2.user
        else:
            winner = None

        await self._display_battle_results(rounds, winner)
        self.cog.remove_battle(self.channel.guild.id)

    async def _battle_round(self, round_number: int, ball1, ball2):
        """Simulate a single battle round."""
        result = {
            "round": round_number,
            "ball1": ball1,
            "ball2": ball2,
            "winner": None,
            "details": []
        }

        if self.is_cancelled:
            return result

        battle_log: list[str] = []
        round_start = f"Round {round_number} begins!\n"
        round_start += f"⚔️ {ball1.countryball.country} (ATK:{ball1.attack} HP:{ball1.health}) vs {ball2.countryball.country} (ATK:{ball2.attack} HP:{ball2.health})"
        battle_log.append(round_start)
        
        self.embed.description = "\n".join(battle_log)
        await self.message.edit(embed=self.embed)
        await asyncio.sleep(2)
        
        ball1_hp = ball1.health
        ball2_hp = ball2.health
        
        first_attacker = random.choice([1, 2])
        first_attack_msg = (
            f"🎲 First strike: {ball1.countryball.country}"
            if first_attacker == 1
            else f"🎲 First strike: {ball2.countryball.country}"
        )
        battle_log.append(first_attack_msg)
        
        self.embed.description = "\n".join(battle_log)
        await self.message.edit(embed=self.embed)
        await asyncio.sleep(1.5)
        
        async def perform_attack(attacker, defender, attacker_hp, defender_hp):
            base_crit_chance = 0.08
            attack_advantage = attacker.attack / (defender.health + 1)
            crit_chance = min(max(base_crit_chance * (1 + attack_advantage * 0.3), 0.05), 0.2)
            
            is_crit = random.random() < crit_chance
            damage_multiplier = 1.3 if is_crit else 1.0
            
            defense_ratio = defender.health / (max(attacker.attack, 1) * 4)
            defense_reduction = min(defense_ratio, 0.2)
            base_damage = attacker.attack * (1 - defense_reduction)
            
            damage = base_damage * damage_multiplier if not is_crit else max(base_damage * damage_multiplier, attacker.attack * 1.3)
            
            defender_hp -= damage
            
            attack_emojis = {
                "normal": ["⚔️", "🗡️", "👊", "💢", "💫"],
                "crit": ["💥", "✨", "🌟", "🔥", "⚡"]
            }
            
            attack_verbs = [
                "deals",
                "delivers",
                "unleashes",
                "strikes for",
                "hits for",
                "inflicts",
                "lands",
                "bursts for",
                "lashes out for",
                "smashes for",
                "hammers for",
                "slashes for",
            ]
            
            attack_emoji = random.choice(attack_emojis["crit"] if is_crit else attack_emojis["normal"])
            attack_msg = f"{attack_emoji} {attacker.countryball.country} "
            
            if is_crit:
                attack_msg += f"crits for {damage:.0f} damage!"
            else:
                attack_msg += f"{random.choice(attack_verbs)} {damage:.0f} damage!"
            
            if defense_reduction > 0:
                attack_msg += f" (mitigation: {defense_reduction*100:.0f}%)"
            
            attack_msg += f" (defender HP: {max(0, defender_hp):.0f})"
            battle_log.append(attack_msg)
            result["details"].append(attack_msg)
            
            self.embed.description = "\n".join(battle_log)
            await self.message.edit(embed=self.embed)
            await asyncio.sleep(1.5)
            
            return defender_hp

        turn_count = 0
        max_turns = 10

        while ball1_hp > 0 and ball2_hp > 0:
            turn_count += 1
            if turn_count > max_turns:
                draw_msg = "⚠️ Both sides are exhausted. This round ends in a draw."
                battle_log.append(draw_msg)
                result["details"].append(draw_msg)
                self.embed.description = "\n".join(battle_log)
                await self.message.edit(embed=self.embed)
                await asyncio.sleep(2)
                break
            if self.is_cancelled:
                return result

            if first_attacker == 1:
                ball2_hp = await perform_attack(ball1, ball2, ball1_hp, ball2_hp)
                if ball2_hp <= 0:
                    defeat_msg = f"💀 {ball2.countryball.country} is down!"
                    battle_log.append(defeat_msg)
                    result["details"].append(defeat_msg)
                    result["winner"] = self.battler1.user
                    self.embed.description = "\n".join(battle_log)
                    await self.message.edit(embed=self.embed)
                    await asyncio.sleep(2)
                    break
                
                if self.is_cancelled:
                    return result
                
                ball1_hp = await perform_attack(ball2, ball1, ball2_hp, ball1_hp)
                if ball1_hp <= 0:
                    defeat_msg = f"💀 {ball1.countryball.country} is down!"
                    battle_log.append(defeat_msg)
                    result["details"].append(defeat_msg)
                    result["winner"] = self.battler2.user
                    self.embed.description = "\n".join(battle_log)
                    await self.message.edit(embed=self.embed)
                    await asyncio.sleep(2)
                    break
            else:
                ball1_hp = await perform_attack(ball2, ball1, ball2_hp, ball1_hp)
                if ball1_hp <= 0:
                    defeat_msg = f"💀 {ball1.countryball.country} is down!"
                    battle_log.append(defeat_msg)
                    result["details"].append(defeat_msg)
                    result["winner"] = self.battler2.user
                    self.embed.description = "\n".join(battle_log)
                    await self.message.edit(embed=self.embed)
                    await asyncio.sleep(2)
                    break
                
                if self.is_cancelled:
                    return result
                
                ball2_hp = await perform_attack(ball1, ball2, ball1_hp, ball2_hp)
                if ball2_hp <= 0:
                    defeat_msg = f"💀 {ball2.countryball.country} is down!"
                    battle_log.append(defeat_msg)
                    result["details"].append(defeat_msg)
                    result["winner"] = self.battler1.user
                    self.embed.description = "\n".join(battle_log)
                    await self.message.edit(embed=self.embed)
                    await asyncio.sleep(2)
                    break

        if result["winner"] and not self.is_cancelled:
            victory_emojis = ["🏆", "👑", "🏅", "✨", "🌟", "💫", "🎉", "🎊"]
            victory_phrases = [
                "wins the round!",
                "secures the victory!",
                "dominates this duel!",
                "controls the battlefield!",
                "outplays the opponent!",
                "emerges triumphant!",
            ]
            battle_log.append(f"\n{random.choice(victory_emojis)} {result['winner'].display_name} {random.choice(victory_phrases)}")
            self.embed.description = "\n".join(battle_log)
            await self.message.edit(embed=self.embed)
            await asyncio.sleep(2)

        return result

    async def _display_battle_results(self, rounds: List[dict], winner: Optional[discord.User], custom_message: str = None):
        """Display the final outcome of the battle."""
        try:
            if custom_message:
                self.embed.description = custom_message
            else:
                description = "🏆 The battle is over!\n\n"
                
                total_rounds = len(rounds)
                if total_rounds > 0:
                    description += f"{total_rounds} rounds were played.\n\n"
                    
                    battler1_wins = sum(1 for r in rounds if r["winner"] == self.battler1.user)
                    battler2_wins = sum(1 for r in rounds if r["winner"] == self.battler2.user)
                    
                    description += "📊 Scoreboard:\n"
                    description += f"{self.battler1.user.display_name}: {battler1_wins} wins\n"
                    description += f"{self.battler2.user.display_name}: {battler2_wins} wins\n\n"
                    
                    if winner:
                        winner_wins = battler1_wins if winner == self.battler1.user else battler2_wins
                        victory_phrases = [
                            "secures a decisive victory",
                            "showcases impressive tactics",
                            "controls the fight from start to finish",
                            "wins with flawless execution",
                            "outmaneuvers the opponent brilliantly",
                            "demonstrates outstanding battle sense",
                        ]
                        description += f"🎉 Congratulations to {winner.display_name}, who {random.choice(victory_phrases)}!\n"
                        description += f"They close the battle with {winner_wins} winning rounds."
                    else:
                        description += "🤝 Both players are evenly matched. It's a draw!"
                        
                        draw_phrases = [
                            "What a spectacular duel!",
                            "Both sides showed incredible strength.",
                            "We cannot wait for the rematch.",
                            "This was a memorable fight!",
                        ]
                        description += f"\n\n{random.choice(draw_phrases)}"

                self.embed.description = description

            self.embed.color = discord.Colour.green() if winner else discord.Colour.orange()
                
            try:
                await self.message.edit(embed=self.embed, view=None)
            except discord.NotFound:
                print("Battle result message was deleted.")
            except discord.Forbidden:
                print("Missing permissions to update the battle result message.")
            except Exception as e:
                print(f"Failed to update battle result message: {str(e)}")
                
        except Exception as e:
            print(f"Failed to render battle results: {str(e)}")
            try:
                self.embed.description = "🏆 The battle has ended."
                self.embed.color = discord.Colour.orange()
                await self.message.edit(embed=self.embed, view=None)
            except Exception:
                pass


class BattleView(View):
    def __init__(self, battle: BattleMenu):
        super().__init__(timeout=60 * 30)
        self.battle = battle

    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        try:
            self.battle.get_battler(interaction.user)
        except RuntimeError:
            await interaction.response.send_message(
                "You cannot interact with this battle.", ephemeral=True
            )
            return False
        else:
            return True

    @discord.ui.button(label="Lock selection", emoji="\N{LOCK}", style=discord.ButtonStyle.success)
    async def lock(self, interaction: discord.Interaction, button: Button):
        battler = self.battle.get_battler(interaction.user)
        if not battler:
            await interaction.response.send_message(
                "You are not part of this battle.", ephemeral=True
            )
            return
        if battler.locked:
            await interaction.response.send_message(
                "Your roster is already locked.", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        battler.locked = True
        await self.battle.update_message()
        if self.battle.battler1.locked and self.battle.battler2.locked:
            await interaction.followup.send(
                "Both players are locked in. The battle will begin shortly!",
                ephemeral=True,
            )
            await self.battle.commence_battle()
        else:
            await interaction.followup.send(
                "Your selection is now locked. Waiting for your opponent.",
                ephemeral=True,
            )

    @discord.ui.button(label="Cancel battle", emoji="\N{HEAVY MULTIPLICATION X}", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        if not self.battle.get_battler(interaction.user):
            try:
                await interaction.response.send_message(
                    "Only participants can cancel the battle.", ephemeral=True
                )
            except discord.NotFound:
                pass
            return
            
        try:
            await self.battle.cancel("The battle was cancelled by a player.")
            try:
                await interaction.response.send_message("The battle has been cancelled.", ephemeral=True)
            except discord.NotFound:
                try:
                    await interaction.followup.send("The battle has been cancelled.", ephemeral=True)
                except discord.NotFound:
                    pass
        except Exception as e:
            print(f"Failed to cancel battle via button: {str(e)}")
            await self.battle.cancel("The battle was cancelled by a player.")

    @app_commands.command()
    async def add(
        self,
        interaction: discord.Interaction,
        ball: BallInstanceTransform,
    ):
        """
        Add a ball to the battle roster.

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
                "This ball is already in your roster.", ephemeral=True
            )
            return

        if not battle.can_add_ball(battler):
            await interaction.response.send_message(
                f"Your roster already reached the maximum of {battle.MAX_BALLS} balls.", ephemeral=True
            )
            return

        battler.proposal.append(ball)
        battler.proposal = battler.proposal[:battle.MAX_BALLS]
        await interaction.response.send_message(
            f"{ball.countryball.country} joined your roster.", ephemeral=True
        )
        await battle.update_message()

    @app_commands.command()
    async def all(self, interaction: discord.Interaction):
        """
        Add every ball you own, up to the configured limit.
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

        remaining_slots = battle.MAX_BALLS - len(battler.proposal)
        if remaining_slots <= 0:
            await interaction.response.send_message(
                f"Your roster already reached the maximum of {battle.MAX_BALLS} balls.", ephemeral=True
            )
            return

        balls_to_add = available_balls[:remaining_slots]
        battler.proposal.extend(balls_to_add)
        battler.proposal = battler.proposal[:battle.MAX_BALLS]

        if not balls_to_add:
            await interaction.response.send_message("Every ball you own is already in your roster.", ephemeral=True)
            return

        display_balls = balls_to_add[:10]
        more_balls = len(balls_to_add) - len(display_balls)
        display_message = "\n".join(f"{ball.countryball.country}" for ball in display_balls)
        if more_balls > 0:
            display_message += f"\n...and {more_balls} more."

        await interaction.response.send_message(
            f"The following balls were added:\n{display_message}", ephemeral=True
        )
        await battle.update_message()


class CountryballsSource(menus.ListPageSource):
    def __init__(self, entries: List[BallInstance]):
        super().__init__(entries, per_page=25)

    async def format_page(self, menu: "CountryballsSelector", balls: List[BallInstance]):
        menu.set_options(balls)
        return True


class CountryballsSelector(Pages):
    def __init__(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        balls: List[BallInstance],
        cog: "BattleCog",
    ):
        self.bot = interaction.client
        self.interaction = interaction
        source = CountryballsSource(balls)
        super().__init__(source, interaction=interaction)
        self.add_item(self.select_ball_menu)
        self.add_item(self.confirm_button)
        self.add_item(self.select_all_button)
        self.add_item(self.clear_button)
        self.balls_selected: Set[BallInstance] = set()
        self.cog = cog

    def set_options(self, balls: List[BallInstance]):
        options: List[discord.SelectOption] = []
        for ball in balls:
            emoji = self.bot.get_emoji(int(ball.countryball.emoji_id))
            favorite = f"{settings.favorited_collectible_emoji} " if ball.favorite else ""
            special = ball.special_emoji(self.bot, True)
            options.append(
                discord.SelectOption(
                    label=f"{favorite}{special}#{ball.pk:0X} {ball.countryball.country}",
                    description=f"ATK: {ball.attack} • HP: {ball.health}",
                    emoji=emoji,
                    value=f"{ball.pk}",
                    default=ball in self.balls_selected,
                )
            )
        self.select_ball_menu.options = options
        self.select_ball_menu.max_values = len(options)

    @discord.ui.select(min_values=1, max_values=25)
    async def select_ball_menu(
        self, interaction: discord.Interaction["BallsDexBot"], item: discord.ui.Select
    ):
        for value in item.values:
            ball_instance = await BallInstance.get(id=int(value)).prefetch_related(
                "ball", "player"
            )
            self.balls_selected.add(ball_instance)
        await interaction.response.defer()

    @discord.ui.button(label="Select page", style=discord.ButtonStyle.secondary)
    async def select_all_button(
        self, interaction: discord.Interaction["BallsDexBot"], button: Button
    ):
        await interaction.response.defer(thinking=True, ephemeral=True)
        for ball in self.select_ball_menu.options:
            ball_instance = await BallInstance.get(id=int(ball.value)).prefetch_related(
                "ball", "player"
            )
            if ball_instance not in self.balls_selected:
                self.balls_selected.add(ball_instance)
        await interaction.followup.send(
            (
                f"All {settings.plural_collectible_name} on this page were selected.\n"
                "Switch pages to refresh the highlights."
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.primary)
    async def confirm_button(
        self, interaction: discord.Interaction["BallsDexBot"], button: Button
    ):
        await interaction.response.defer(thinking=True, ephemeral=True)
        battle = self.cog.get_battle(interaction)
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

        if any(ball in battler.proposal for ball in self.balls_selected):
            await interaction.followup.send(
                f"Some of these {settings.plural_collectible_name} are already in your roster.",
                ephemeral=True,
            )
            return
        
        if len(battler.proposal) + len(self.balls_selected) > battle.MAX_BALLS:
            await interaction.followup.send(
                f"You can only bring {battle.MAX_BALLS} balls.",
                ephemeral=True
            )
            return

        if len(self.balls_selected) == 0:
            await interaction.followup.send(
                f"You have not selected any {settings.plural_collectible_name} yet.",
                ephemeral=True,
            )
            return

        for ball in self.balls_selected:
            battler.proposal.append(ball)

        grammar = (
            f"{settings.collectible_name}"
            if len(self.balls_selected) == 1
            else f"{settings.plural_collectible_name}"
        )
        await interaction.followup.send(
            f"{len(self.balls_selected)} {grammar} added to your roster.", ephemeral=True
        )
        await battle.update_message()
        self.balls_selected.clear()
        self.stop()

    @discord.ui.button(label="Clear selection", style=discord.ButtonStyle.danger)
    async def clear_button(self, interaction: discord.Interaction["BallsDexBot"], button: Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        self.balls_selected.clear()
        await interaction.followup.send(
            f"Cleared the currently highlighted {settings.plural_collectible_name}."
            f" This does not remove anything already added to your roster.\n"
            f"Some options might still appear selected until you switch pages, "
            "which will refresh their state.",
            ephemeral=True,
        )


class BulkAddView(CountryballsSelector):
    async def on_timeout(self) -> None:
        return await super().on_timeout()