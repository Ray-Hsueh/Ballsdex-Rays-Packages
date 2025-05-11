from typing import Optional, List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from datetime import datetime, timedelta
import json
import os

from ballsdex.core.models import BallInstance, Player as PlayerModel, Ball, Economy, Regime
from ballsdex.core.utils.enums import SortingChoices
from ballsdex.core.utils.transformers import BallEnabledTransform
from ballsdex.packages.trade.menu import ConfirmView
from ballsdex.core.utils.paginator import FieldPageSource, Pages

PENDING_REWARDS_FILE = os.path.join(os.path.dirname(__file__), "pending_rewards.json")

class PendingReward:
    def __init__(self, user_id: int, reward_info: Dict[str, Any], expiry_time: datetime):
        self.user_id = user_id
        self.reward_info = reward_info
        self.expiry_time = expiry_time

class RewardManager:
    def __init__(self):
        # Ensure rewards folder exists
        rewards_dir = os.path.dirname(PENDING_REWARDS_FILE)
        if not os.path.exists(rewards_dir):
            os.makedirs(rewards_dir)
        self.pending_rewards = self.load_pending_rewards()
        self.confirmation_timeout = 86400  # 24 hours
        
    def load_pending_rewards(self):
        if os.path.exists(PENDING_REWARDS_FILE):
            with open(PENDING_REWARDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Convert back to PendingReward object
            result = {}
            for uid, info in data.items():
                result[int(uid)] = PendingReward(
                    int(uid),
                    info["reward_info"],
                    datetime.fromisoformat(info["expiry_time"])
                )
            return result
        return {}

    def save_pending_rewards(self):
        data = {}
        for uid, reward in self.pending_rewards.items():
            data[str(uid)] = {
                "reward_info": reward.reward_info,
                "expiry_time": reward.expiry_time.isoformat()
            }
        with open(PENDING_REWARDS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    async def send_reward_confirmation(self, user: discord.User, reward_info: Dict[str, Any]) -> bool:
        try:
            await user.send(
                f"🎁 You have a new reward to claim!\n"
                f"Reward type: {reward_info['type']}\n"
                f"Reward details: {reward_info['description']}\n"
                f"Please use the `/rewards claim` command within 24 hours to claim your reward."
            )
            expiry_time = datetime.now() + timedelta(seconds=self.confirmation_timeout)
            self.pending_rewards[user.id] = PendingReward(user.id, reward_info, expiry_time)
            self.save_pending_rewards()
            return True
        except discord.Forbidden:
            return False  # Unable to send private message
            
    async def check_pending_reward(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Check if a user has pending rewards to confirm
        
        Args:
            user_id: User ID
            
        Returns:
            Optional[Dict[str, Any]]: Reward information, returns None if none
        """
        if user_id not in self.pending_rewards:
            return None
            
        reward = self.pending_rewards[user_id]
        if datetime.now() > reward.expiry_time:
            del self.pending_rewards[user_id]
            self.save_pending_rewards()
            return None
            
        return reward.reward_info
            
    async def distribute_rewards(
        self,
        bot: commands.Bot,
        reward_type: str,
        reward_description: str,
        rarity_range: Optional[tuple] = None,
        specific_balls: Optional[List[Ball]] = None,
        target_users: Optional[List[discord.User]] = None,
        reward_count: int = 1,
        interaction: Optional[discord.Interaction] = None
    ) -> Dict[str, Any]:
        """
        Distribute rewards to specified users, distribute in batches asynchronously and report progress in real-time
        """
        results = {
            "total_users": 0,
            "notified_users": 0,
            "failed_users": 0
        }
        progress_message = None
        batch_size = 10
        # If no target users are specified, distribute to all players
        if not target_users:
            bot_id = bot.user.id
            players = await PlayerModel.all()
            target_users = []
            for player in players:
                if player.discord_id == bot_id:
                    continue
                user = bot.get_user(player.discord_id)
                if not user:
                    try:
                        user = await bot.fetch_user(player.discord_id)
                    except Exception:
                        user = None
                if user and not user.bot:
                    target_users.append(user)
        results["total_users"] = len(target_users)
        total = len(target_users)
        notified = 0
        failed = 0
        if interaction:
            progress_message = await interaction.followup.send(f"🎁 Distributing rewards...\nNotified: 0\nFailed: 0\nRemaining: {total}", ephemeral=True)
        for i in range(0, total, batch_size):
            batch = target_users[i:i+batch_size]
            tasks = [self.send_reward_confirmation(user, {
                "type": reward_type,
                "description": reward_description,
                "rarity_range": rarity_range,
                "specific_balls": [b.id for b in specific_balls] if specific_balls else None,
                "reward_count": reward_count
            }) for user in batch]
            results_list = await asyncio.gather(*tasks)
            notified += sum(1 for r in results_list if r)
            failed += sum(1 for r in results_list if not r)
            if interaction and progress_message:
                await interaction.followup.send(
                    f"🎁 Distributing rewards...\nNotified: {notified}\nFailed: {failed}\nRemaining: {max(0, total - (i+batch_size))}", ephemeral=True
                )
            await asyncio.sleep(1)
        results["notified_users"] = notified
        results["failed_users"] = failed
        return results

class Rewards(commands.GroupCog, group_name="rewards"):
    """
    Reward system related commands.
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reward_manager = RewardManager()
        
    async def station_type_autocomplete(self, interaction: discord.Interaction, current: str):
        economies = await Economy.all()
        return [
            discord.app_commands.Choice(name=e.name, value=e.name)
            for e in economies if current.lower() in e.name.lower()
        ][:25]

    async def line_type_autocomplete(self, interaction: discord.Interaction, current: str):
        regimes = await Regime.all()
        return [
            discord.app_commands.Choice(name=r.name, value=r.name)
            for r in regimes if current.lower() in r.name.lower()
        ][:25]

    @app_commands.command()
    @app_commands.default_permissions(administrator=True)
    async def distribute(
        self,
        interaction: discord.Interaction,
        reward_type: str,
        reward_description: str,
        reward_count: int = 1,
        economy_type: Optional[str] = None,
        regime_type: Optional[str] = None,
        min_rarity: Optional[int] = None,
        max_rarity: Optional[int] = None,
        target_role: Optional[discord.Role] = None,
        target_user_ids: Optional[str] = None
    ):
        """
        Distribute rewards to specified users.
        
        Parameters
        ----------
        reward_type: str
            Reward type
        reward_description: str
            Reward description
        reward_count: int
            Number of rewards each user receives
        economy_type: Optional[str]
            Economy type (automatically retrieves all economy names)
        regime_type: Optional[str]
            Regime type (automatically retrieves all regime names)
        min_rarity: Optional[int]
            Minimum rarity
        max_rarity: Optional[int]
            Maximum rarity
        target_role: Optional[discord.Role]
            Target role (if specified, only sends to users with that role)
        target_user_ids: Optional[str]
            Target user IDs (can enter multiple IDs, separated by commas or spaces, takes precedence over target_role)
        """
        await interaction.response.defer(thinking=True)
        
        # Check reward count
        if reward_count < 1:
            await interaction.followup.send("Reward count must be greater than 0!", ephemeral=True)
            return
        if reward_count > 10:
            await interaction.followup.send("You can only distribute up to 10 rewards at a time!", ephemeral=True)
            return
            
        # Check rarity range
        rarity_range = None
        if (min_rarity is not None and max_rarity is None) or (min_rarity is None and max_rarity is not None):
            await interaction.followup.send("Please provide both minimum and maximum rarity!", ephemeral=True)
            return
        if min_rarity is not None and max_rarity is not None:
            if min_rarity > max_rarity:
                await interaction.followup.send("Minimum rarity cannot be greater than maximum rarity!", ephemeral=True)
                return
            rarity_range = (min_rarity, max_rarity)
            
        # Parse target user IDs
        target_users = None
        if target_user_ids:
            # Support comma or space separated
            id_list = [i.strip() for i in target_user_ids.replace(',', ' ').split() if i.strip().isdigit()]
            if not id_list:
                await interaction.followup.send("Please enter valid user IDs!", ephemeral=True)
                return
            target_users = []
            for uid in id_list:
                try:
                    user = self.bot.get_user(int(uid))
                    if not user:
                        user = await self.bot.fetch_user(int(uid))
                    if user:
                        target_users.append(user)
                except Exception:
                    continue
            if not target_users:
                await interaction.followup.send("No valid user IDs found!", ephemeral=True)
                return
        elif target_role:
            target_users = target_role.members
            
        # Filter available balls based on selected economy or regime
        available_balls = None
        if economy_type:
            available_balls = await Ball.filter(economy__name=economy_type)
            if not available_balls:
                await interaction.followup.send(f"No balls found for economy type {economy_type}!", ephemeral=True)
                return
        elif regime_type:
            available_balls = await Ball.filter(regime__name=regime_type)
            if not available_balls:
                await interaction.followup.send(f"No balls found for regime type {regime_type}!", ephemeral=True)
                return
        # If neither is selected, available_balls remains None, representing random
        
        # Distribute rewards
        results = await self.reward_manager.distribute_rewards(
            self.bot,
            reward_type,
            reward_description,
            rarity_range=rarity_range,
            specific_balls=available_balls,
            target_users=target_users,
            reward_count=reward_count,
            interaction=interaction
        )
        
        # Send result statistics
        await interaction.followup.send(
            f"🎁 Reward distribution complete!\n"
            f"Total users: {results['total_users']}\n"
            f"Notified: {results['notified_users']}\n"
            f"Failed: {results['failed_users']}\n"
            f"Reward count per user: {reward_count}"
        )

    distribute.autocomplete("economy_type")(station_type_autocomplete)
    distribute.autocomplete("regime_type")(line_type_autocomplete)

    @app_commands.command()
    async def claim(self, interaction: discord.Interaction):
        """
        Claim pending rewards to confirm.
        """
        # Check if there are pending rewards to confirm
        reward_info = await self.reward_manager.check_pending_reward(interaction.user.id)
        if not reward_info:
            await interaction.response.send_message("You currently have no pending rewards!", ephemeral=True)
            return
            
        await interaction.response.defer(thinking=True)
        
        try:
            # Get user's Player instance
            player = await PlayerModel.get(discord_id=interaction.user.id)
            
            # Generate ball based on reward type
            if reward_info.get("specific_balls"):
                ball_id = random.choice(reward_info["specific_balls"])
                ball = await Ball.get(id=ball_id)
            elif reward_info.get("rarity_range"):
                # Randomly select ball based on rarity range
                min_rarity, max_rarity = reward_info["rarity_range"]
                available_balls = await Ball.filter(rarity__gte=min_rarity, rarity__lte=max_rarity)
                if not available_balls:
                    await interaction.followup.send("Unable to generate a ball that meets the criteria!", ephemeral=True)
                    return
                ball = random.choice(available_balls)
            else:
                # Use original random generation method
                ball = await BallSpawnView.get_random(self.bot)
            
            # Create ball instance
            instance = await BallInstance.create(
                ball=ball,
                player=player,
                attack_bonus=random.randint(-5, 5),
                health_bonus=random.randint(-5, 5),
            )
            
            # Remove pending rewards
            del self.reward_manager.pending_rewards[interaction.user.id]
            self.reward_manager.save_pending_rewards()
            
            # Send reward message
            await interaction.followup.send(
                f"🎉 Congratulations!\n"
                f"You received: {ball.country} (ATK:{instance.attack} HP:{instance.health})"
            )
            
        except Exception as e:
            print(f"Error while distributing reward: {str(e)}")
            await interaction.followup.send("An error occurred while distributing the reward. Please try again later!", ephemeral=True) 