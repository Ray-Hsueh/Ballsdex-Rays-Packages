import asyncio
import discord
import random
from datetime import timedelta
from discord.ui import View, Button
from typing import TYPE_CHECKING, List, Optional
from discord import app_commands

from ballsdex.packages.battle.battling_user import BattlingUser
from ballsdex.settings import settings
from ballsdex.core.models import BallInstance, Player
from ballsdex.core.utils.transformers import BallInstanceTransform

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


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
        """
        Check if more balls can be added.
        """
        return len(battler.proposal) < self.MAX_BALLS

    def _generate_embed(self):
        self.embed.title = f"{settings.plural_collectible_name.title()} Battle"
        self.embed.color = discord.Colour.blurple()
        self.embed.description = (
            f"Select the {settings.plural_collectible_name} you want to use in battle.\n"
            "After preparation is complete, click the lock button below to confirm your selection.\n\n"
            f"*You can select up to {self.MAX_BALLS} balls.*\n"
            "*This battle will timeout after 30 minutes.*"
        )
        self.embed.set_footer(
            text="This message updates every 15 seconds, "
            "you can continue adjusting your selection."
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
            name=f"{self.battler1.user.display_name}'s Battle Lineup",
            value=format_proposal(self.battler1.proposal),
            inline=True,
        )
        self.embed.add_field(
            name=f"{self.battler2.user.display_name}'s Battle Lineup",
            value=format_proposal(self.battler2.proposal),
            inline=True,
        )

    async def update_message(self):
        self._generate_embed()
        await self.message.edit(embed=self.embed)

    async def update_message_loop(self):
        """
        Loop task that updates menu content every 15 seconds.
        """
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
                        f"⚠️ Battle will timeout in {int(remaining_time.total_seconds() / 60) + 1} minutes!\n"
                        "Please complete your selection soon."
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
                                f"⏰ Battle has timed out!\n\n"
                                f"Since {loser.mention} did not complete their selection in time,\n"
                                f"{winner.mention} automatically wins!"
                            )
                        else:
                            self.embed.description = (
                                f"⏰ Battle has timed out!\n\n"
                                f"Since neither player completed their selection in time,\n"
                                "the battle has been automatically cancelled."
                            )
                        self.embed.color = discord.Colour.red()
                        await self.message.edit(embed=self.embed)
                        await self.cancel("Battle has timed out.")
                        return
                    except (discord.NotFound, discord.Forbidden):
                        await self.cancel("Battle has timed out, but unable to update message.")
                        return

                try:
                    await self.update_message()
                except discord.NotFound:
                    await self.cancel("Battle message has been deleted.")
                    return
                except discord.Forbidden:
                    await self.cancel("Bot doesn't have sufficient permissions to update message.")
                    return
                except Exception as e:
                    print(f"Error occurred while updating message: {str(e)}")
                    await asyncio.sleep(15)
                    continue

                await asyncio.sleep(15)
        except asyncio.CancelledError:
            return
        finally:
            if not self.message or self.message.flags.ephemeral:
                self.cog.remove_battle(self.channel.guild.id)

    async def start(self):
        """
        Start the battle, send initial message and open selection.
        """
        try:
            self._generate_embed()
            self.message = await self.channel.send(
                content=f"🎮 {self.battler1.user.mention} has challenged {self.battler2.user.mention} to a battle!\n"
                "Please use `/battle add` command to select your balls, or use `/battle all` for random selection.\n"
                "After selection is complete, click the 'Lock Selection' button below to confirm.",
                embed=self.embed,
                view=self.current_view,
                allowed_mentions=discord.AllowedMentions(users=[self.battler1.user, self.battler2.user]),
            )
            self.task = self.bot.loop.create_task(self.update_message_loop())
            
            help_embed = discord.Embed(
                title="Battle Instructions",
                description=(
                    "1. Use `/battle add` command to select your balls\n"
                    "2. Use `/battle all` command to randomly select balls\n"
                    "3. Use `/battle best` command to select your strongest 10 balls\n"
                    "4. After selection is complete, click the 'Lock Selection' button\n"
                    "5. When both players have locked, the battle will automatically begin\n"
                    "6. Battle will automatically timeout after 30 minutes\n\n"
                    "📊 Damage Calculation Mechanism:\n"
                    "• Base damage = Attack power\n"
                    "• Defense reduction: When opponent's HP is higher, up to 20% damage reduction\n"
                    "• Critical hit: 8% base critical rate, higher attack power increases critical rate\n"
                    "• Critical damage is 1.3x base damage\n"
                    "• Battle messages will show actual defense reduction percentage"
                ),
                color=discord.Colour.blue()
            )
            help_embed.set_footer(text="Good luck!")
            try:
                await self.channel.send(embed=help_embed)
            except:
                pass
                
        except Exception as e:
            print(f"Error occurred while starting battle: {str(e)}")
            raise

    async def cancel(self, reason: str = "Battle has been cancelled."):
        """
        Immediately cancel the battle.
        """
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
            print(f"Error occurred while cancelling battle: {str(e)}")
        finally:
            self.cog.remove_battle(self.channel.guild.id)

    async def commence_battle(self):
        """
        Start the battle between two players.
        """
        if not self.battler1.proposal and not self.battler2.proposal:
            await self._display_battle_results([], None, "Neither player selected any balls!")
            return
        elif not self.battler1.proposal:
            await self._display_battle_results([], self.battler2.user, f"{self.battler1.user.display_name} didn't select any balls!")
            return
        elif not self.battler2.proposal:
            await self._display_battle_results([], self.battler1.user, f"{self.battler2.user.display_name} didn't select any balls!")
            return

        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        self.embed.description = "🎮 Battle begins!\n\n"
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
                
            score_msg = f"\n\n📊 Current Score:\n{self.battler1.user.display_name}: {battler1_wins} wins\n{self.battler2.user.display_name}: {battler2_wins} wins"
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
        """
        Simulate a single round of battle.
        """
        result = {
            "round": round_number,
            "ball1": ball1,
            "ball2": ball2,
            "winner": None,
            "details": []
        }

        if self.is_cancelled:
            return result

        battle_log = []
        
        round_start = f"Round {round_number} begins!\n"
        round_start += f"⚔️ {ball1.countryball.country} (ATK:{ball1.attack} HP:{ball1.health}) vs {ball2.countryball.country} (ATK:{ball2.attack} HP:{ball2.health})"
        battle_log.append(round_start)
        
        self.embed.description = "\n".join(battle_log)
        await self.message.edit(embed=self.embed)
        await asyncio.sleep(2)

        ball1_hp = ball1.health
        ball2_hp = ball2.health
        
        first_attacker = random.choice([1, 2])
        first_attack_msg = f"🎲 {'First attack: ' + ball1.countryball.country if first_attacker == 1 else 'First attack: ' + ball2.countryball.country}"
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
            
            defense_ratio = defender.health / (attacker.attack * 4)
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
                "inflicts",
                "strikes",
                "delivers",
                "causes",
                "brings",
                "applies",
                "bursts",
                "releases",
                "hits",
                "sends",
                "outputs",
                "emits",
                "generates"
            ]
            
            attack_emoji = random.choice(attack_emojis["crit"] if is_crit else attack_emojis["normal"])
            attack_msg = f"{attack_emoji} {attacker.countryball.country} "
            
            if is_crit:
                attack_msg += f"CRITICAL HIT {damage:.0f} damage!"
            else:
                attack_msg += f"{random.choice(attack_verbs)} {damage:.0f} damage!"
            
            if defense_reduction > 0:
                attack_msg += f" (Defense reduction: {defense_reduction*100:.0f}%)"
            
            attack_msg += f" (Remaining HP: {max(0, defender_hp):.0f})"
            battle_log.append(attack_msg)
            result["details"].append(attack_msg)
            
            self.embed.description = "\n".join(battle_log)
            await self.message.edit(embed=self.embed)
            await asyncio.sleep(1.5)
            
            return defender_hp

        while ball1_hp > 0 and ball2_hp > 0:
            if self.is_cancelled:
                return result

            if first_attacker == 1:
                ball2_hp = await perform_attack(ball1, ball2, ball1_hp, ball2_hp)
                if ball2_hp <= 0:
                    defeat_msg = f"💀 {ball2.countryball.country} has fallen!"
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
                    defeat_msg = f"💀 {ball1.countryball.country} has fallen!"
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
                    defeat_msg = f"💀 {ball1.countryball.country} has fallen!"
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
                    defeat_msg = f"💀 {ball2.countryball.country} has fallen!"
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
                "wins this round!",
                "achieves victory!",
                "demonstrates powerful strength!",
                "perfectly controls the battlefield!",
                "wins with brilliant tactics!",
                "stands out in the fierce duel!"
            ]
            battle_log.append(f"\n{random.choice(victory_emojis)} {result['winner'].display_name} {random.choice(victory_phrases)}")
            self.embed.description = "\n".join(battle_log)
            await self.message.edit(embed=self.embed)
            await asyncio.sleep(2)

        return result

    async def _display_battle_results(self, rounds: List[dict], winner: Optional[discord.User], custom_message: str = None):
        """
        Display battle results.
        """
        try:
            if custom_message:
                self.embed.description = custom_message
            else:
                description = "🏆 Battle ended!\n\n"
                
                total_rounds = len(rounds)
                if total_rounds > 0:
                    description += f"Total rounds fought: {total_rounds}\n\n"
                    
                    battler1_wins = sum(1 for r in rounds if r["winner"] == self.battler1.user)
                    battler2_wins = sum(1 for r in rounds if r["winner"] == self.battler2.user)
                    
                    description += f"📊 Battle Statistics:\n"
                    description += f"{self.battler1.user.display_name}: {battler1_wins} wins\n"
                    description += f"{self.battler2.user.display_name}: {battler2_wins} wins\n\n"
                    
                    if winner:
                        winner_wins = battler1_wins if winner == self.battler1.user else battler2_wins
                        victory_phrases = [
                            "achieves overwhelming victory",
                            "demonstrates amazing combat skills",
                            "perfectly controls the battlefield",
                            "wins with brilliant tactics",
                            "stands out in the fierce duel",
                            "shows exceptional combat wisdom"
                        ]
                        description += f"🎉 Congratulations {winner.display_name} {random.choice(victory_phrases)}!\n"
                        description += f"Won {winner_wins} exciting victories!"
                    else:
                        description += "🤝 Both sides are evenly matched, it's a draw!"
                        
                        draw_phrases = [
                            "This was an exciting duel!",
                            "Both sides demonstrated excellent strength!",
                            "Looking forward to the next duel!",
                            "This was an unforgettable battle!"
                        ]
                        description += f"\n\n{random.choice(draw_phrases)}"

                self.embed.description = description

            if winner:
                self.embed.color = discord.Colour.green()
            else:
                self.embed.color = discord.Colour.orange()
                
            try:
                await self.message.edit(embed=self.embed, view=None)
            except discord.NotFound:
                print("Battle result message has been deleted")
            except discord.Forbidden:
                print("No permission to update battle result message")
            except Exception as e:
                print(f"Error occurred while updating battle results: {str(e)}")
                
        except Exception as e:
            print(f"Error occurred while displaying battle results: {str(e)}")
            try:
                self.embed.description = "🏆 Battle has ended!"
                self.embed.color = discord.Colour.orange()
                await self.message.edit(embed=self.embed, view=None)
            except:
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
                "You cannot participate in this battle.", ephemeral=True
            )
            return False
        else:
            return True

    @discord.ui.button(label="Lock Selection", emoji="\N{LOCK}", style=discord.ButtonStyle.success)
    async def lock(self, interaction: discord.Interaction, button: Button):
        battler = self.battle.get_battler(interaction.user)
        if not battler:
            await interaction.response.send_message(
                "You are not a participant in this battle.", ephemeral=True
            )
            return
        if battler.locked:
            await interaction.response.send_message(
                "You have already locked your selection!", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        battler.locked = True
        await self.battle.update_message()
        if self.battle.battler1.locked and self.battle.battler2.locked:
            await interaction.followup.send(
                "Both players have locked their selections. Battle is about to begin!",
                ephemeral=True,
            )
            await self.battle.commence_battle()
        else:
            await interaction.followup.send(
                "Your selection has been locked. "
                "Waiting for the opponent to lock their selection.",
                ephemeral=True,
            )

    @discord.ui.button(label="Cancel Battle", emoji="\N{HEAVY MULTIPLICATION X}", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        if not self.battle.get_battler(interaction.user):
            try:
                await interaction.response.send_message(
                    "Only battle participants can cancel the battle.", ephemeral=True
                )
            except discord.NotFound:
                pass
            return
            
        try:
            await self.battle.cancel("Battle has been cancelled by player.")
            
            try:
                await interaction.response.send_message("Battle has been cancelled.", ephemeral=True)
            except discord.NotFound:
                try:
                    await interaction.followup.send("Battle has been cancelled.", ephemeral=True)
                except discord.NotFound:
                    pass
        except Exception as e:
            print(f"Error occurred while cancelling battle: {str(e)}")
            await self.battle.cancel("Battle has been cancelled by player.")

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

        if not battle.can_add_ball(battler):
            await interaction.response.send_message(
                f"Your battle lineup has reached the maximum limit ({battle.MAX_BALLS} balls).", ephemeral=True
            )
            return

        battler.proposal.append(ball)
        battler.proposal = battler.proposal[:battle.MAX_BALLS]
        await interaction.response.send_message(
            f"{ball.countryball.country} has been added to the battle lineup.", ephemeral=True
        )
        await battle.update_message()

    @app_commands.command()
    async def all(self, interaction: discord.Interaction):
        """
        Add all owned balls to the battle, up to 20.
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

        remaining_slots = battle.MAX_BALLS - len(battler.proposal)
        if remaining_slots <= 0:
            await interaction.response.send_message(
                f"Your battle lineup has reached the maximum limit ({battle.MAX_BALLS} balls).", ephemeral=True
            )
            return

        balls_to_add = available_balls[:remaining_slots]
        battler.proposal.extend(balls_to_add)
        battler.proposal = battler.proposal[:battle.MAX_BALLS]

        if not balls_to_add:
            await interaction.response.send_message("All your balls are already in the battle lineup.", ephemeral=True)
            return

        display_balls = balls_to_add[:10]
        more_balls = len(balls_to_add) - len(display_balls)
        display_message = "\n".join(f"{ball.countryball.country}" for ball in display_balls)
        if more_balls > 0:
            display_message += f"\n...and {more_balls} more."

        await interaction.response.send_message(
            f"Added the following balls to the battle lineup:\n{display_message}", ephemeral=True
        )
        await battle.update_message()


class FightInviteView(View):
    def __init__(self, fight: dict, cog: "Battle"):
        super().__init__(timeout=30)
        self.fight = fight
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in [self.fight["challenger"].id, self.fight["opponent"].id]:
            await interaction.response.send_message("Only duel participants can use these buttons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.fight["opponent"].id:
            await interaction.response.send_message("Only the invited player can accept the duel.", ephemeral=True)
            return

        self.fight["status"] = "active"

        embed = discord.Embed(
            title="Duel Accepted!",
            description=f"{self.fight['opponent'].mention} accepted the duel!\n\n"
                       f"Both players please use `/battle fight select` command to select a ball for the duel.",
            color=discord.Colour.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)

        self.cog.bot.loop.create_task(self._check_selection_timeout())

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.fight["opponent"].id:
            await interaction.response.send_message("Only the invited player can decline the duel.", ephemeral=True)
            return

        await self.cog._cancel_fight(interaction.guild_id, f"{self.fight['opponent'].mention} declined the duel.")
        await interaction.response.edit_message(view=None)

    async def on_timeout(self):
        if self.fight["status"] == "pending":
            await self.cog._cancel_fight(self.fight["message"].guild.id, "Duel invitation has expired.")
            try:
                await self.fight["message"].edit(view=None)
            except:
                pass

    async def _check_selection_timeout(self):
        """Check for ball selection timeout"""
        await asyncio.sleep(180)
        if self.fight["status"] == "active" and (not self.fight["challenger_ball"] or not self.fight["opponent_ball"]):
            await self.cog._cancel_fight(self.fight["message"].guild.id, "Ball selection time has expired.")
            try:
                embed = discord.Embed(
                    title="Duel Cancelled",
                    description="Ball selection time has expired.",
                    color=discord.Colour.red()
                )
                await self.fight["message"].edit(embed=embed, view=None)
            except:
                pass


class FightActionView(View):
    def __init__(self, fight: dict, current_user_id: int, cog):
        super().__init__(timeout=30)
        self.fight = fight
        self.current_user_id = current_user_id
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.current_user_id:
            await interaction.response.send_message("It's not your turn, please wait for the opponent's action.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Punch", emoji="👊", style=discord.ButtonStyle.primary)
    async def punch(self, interaction: discord.Interaction, button: Button):
        await self._handle_action(interaction, "Punch")

    @discord.ui.button(label="Kick", emoji="🦵", style=discord.ButtonStyle.danger)
    async def kick(self, interaction: discord.Interaction, button: Button):
        await self._handle_action(interaction, "Kick")

    @discord.ui.button(label="Defend", emoji="🛡️", style=discord.ButtonStyle.secondary)
    async def defend(self, interaction: discord.Interaction, button: Button):
        await self._handle_action(interaction, "Defend")

    @discord.ui.button(label="Run", emoji="💨", style=discord.ButtonStyle.danger)
    async def run(self, interaction: discord.Interaction, button: Button):
        await self._handle_escape(interaction)

    async def _handle_action(self, interaction: discord.Interaction, action: str):
        await self.cog._handle_fight_action(interaction, action)
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

    async def _handle_escape(self, interaction: discord.Interaction):
        fight = self.fight
        fight["status"] = "finished"
        runner = interaction.user
        embed = discord.Embed(
            title="Duel Ended!",
            description=f"{runner.mention} chose to run, battle ended!",
            color=discord.Colour.red()
        )
        await fight["message"].edit(embed=embed, view=None)
        if hasattr(self.cog, "fights") and fight.get("message") and fight.get("message").guild:
            guild_id = fight["message"].guild.id
            if guild_id in self.cog.fights:
                del self.cog.fights[guild_id]
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)