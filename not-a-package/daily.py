# today we gonna edit ballsdex/packages/balls/cog.py
# it uses a stupid method which called json, as I'm bad at DB, skip this if you don't like json

# put these import in the very beginning of the code
import json
import os
import random
import asyncio
import traceback
from datetime import datetime, timedelta, timezone
from ballsdex.packages.countryballs.countryball import BallSpawnView
#######################################################################################

# paste this into line 39 and change it to whatever you want
TIMEZONE_SETTING = timezone(timedelta(hours=8)) # Timezone configuration - change this to adjust timezone
######################################################################################

# paste the following into line 124
        self.daily_claims = {}
        self.daily_claims_file = os.path.join(os.path.dirname(__file__), "daily_claims.json")
        self.load_daily_claims()
    
    def load_daily_claims(self):
        """Load daily claim records"""
        if os.path.exists(self.daily_claims_file):
            try:
                with open(self.daily_claims_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for user_id, timestamp in data.items():
                        if isinstance(timestamp, str):
                            dt = datetime.fromisoformat(timestamp)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=TIMEZONE_SETTING)
                            self.daily_claims[int(user_id)] = dt
                        else:
                            dt = datetime.fromtimestamp(timestamp, tz=TIMEZONE_SETTING)
                            self.daily_claims[int(user_id)] = dt
            except Exception as e:
                print(f"Error occurred while loading daily claim records: {str(e)}")
                self.daily_claims = {}
                self.save_daily_claims()

    def save_daily_claims(self):
        """Save daily claim records"""
        try:
            data = {str(uid): ts.isoformat() for uid, ts in self.daily_claims.items()}
            with open(self.daily_claims_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error occurred while saving daily claim records: {str(e)}")
#######################################################################################

# actually you can paste this to anywhere, but if you don't know, then just paste in line 960
    @app_commands.command()
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction):
        """
        Daily check-in to claim rewards.
        """
        await interaction.response.defer(thinking=True)
        
        user_id = interaction.user.id
        now = datetime.now(TIMEZONE_SETTING)
        
        if user_id in self.daily_claims:
            last_claim = self.daily_claims[user_id]
            if last_claim.tzinfo is None:
                last_claim = last_claim.replace(tzinfo=TIMEZONE_SETTING)
            
            today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if last_claim >= today_midnight:
                next_midnight = today_midnight + timedelta(days=1)
                time_left = next_midnight - now
                hours = int(time_left.total_seconds() // 3600)
                minutes = int((time_left.total_seconds() % 3600) // 60)
                await interaction.followup.send(
                    f"You have already claimed today's reward!\n"
                    f"Please try again in {hours} hours and {minutes} minutes.",
                    ephemeral=True
                )
                return
                
        player, _ = await Player.get_or_create(discord_id=user_id)
            
        try:
            candidate_balls = await Ball.filter(enabled=True).all()
            
            if not candidate_balls:
                await interaction.followup.send(
                    "No balls are currently available!",
                    ephemeral=True
                )
                return
            
            weights = [float(b.rarity) for b in candidate_balls]
            visual_target = random.choices(candidate_balls, weights=weights, k=1)[0]

            spawn_view = await BallSpawnView.get_random(self.bot)
            special = spawn_view.get_random_special()

            total_spins = random.randint(4, 7)
            
            reel_sequence = []
            for _ in range(total_spins - 1):
                reel_sequence.append(random.choice(candidate_balls))
            
            if total_spins >= 6 and visual_target.rarity > 10:
                high_tier = [b for b in candidate_balls if b.rarity <= 10]
                if high_tier:
                    reel_sequence[total_spins - 2] = random.choice(high_tier)
            
            reel_sequence.append(visual_target)
            
            initial_embed = discord.Embed(
                title="🎰 Daily Check-in Drawing...",
                description="Drawing your daily reward...",
                color=discord.Color.gold()
            )
            message = await interaction.followup.send(embed=initial_embed)
            
            for step in range(total_spins):
                current_ball = reel_sequence[step]
                prev_ball = reel_sequence[step-1] if step > 0 else random.choice(candidate_balls)
                next_ball = reel_sequence[step+1] if step < total_spins - 1 else random.choice(candidate_balls)
                
                sleep_time = 0.6 + (step * 0.2)
                
                color = discord.Color.gold()
                if step == total_spins - 2 and current_ball.rarity <= 10:
                    color = discord.Color.red()
                
                prev_emoji = self.bot.get_emoji(prev_ball.emoji_id) or prev_ball.country
                current_emoji = self.bot.get_emoji(current_ball.emoji_id) or current_ball.country
                next_emoji = self.bot.get_emoji(next_ball.emoji_id) or next_ball.country
                
                embed = discord.Embed(
                    title="🎰 Daily Check-in Drawing...",
                    description=f"⬇️\n"
                                f"{prev_emoji} {prev_ball.country}\n"
                                f"👉 **{current_emoji} {current_ball.country}** 👈\n"
                                f"{next_emoji} {next_ball.country}\n"
                                f"⬆️",
                    color=color
                )
                await message.edit(embed=embed)
                await asyncio.sleep(sleep_time)
            
            instance = await BallInstance.create(
                ball=visual_target,
                player=player,
                special=special,
                attack_bonus=random.randint(-settings.max_attack_bonus, +settings.max_attack_bonus),
                health_bonus=random.randint(-settings.max_health_bonus, +settings.max_health_bonus),
            )
            
            self.daily_claims[user_id] = now
            self.save_daily_claims()
            
            content, file, view = await instance.prepare_for_message(interaction)
            file.filename = "daily_card.png"
            
            ball_info = f"{visual_target.country} (ATK:{instance.attack} HP:{instance.health})"
            if special:
                special_emoji = getattr(special, "emoji", "")
                ball_info = f"{special_emoji} {ball_info}"
            
            final_embed = discord.Embed(
                title="🎁 Daily Check-in Reward",
                description=f"Congratulations on claiming your daily reward!\n\nYou received: \n{ball_info}",
                color=discord.Color.green()
            )
            final_embed.set_image(url="attachment://daily_card.png")
            
            await message.edit(embed=final_embed, attachments=[file])
            
        except Exception as e:
            print(f"Error occurred while distributing daily reward: {str(e)}")
            traceback.print_exc()
            await interaction.followup.send(
                "An error occurred while distributing the reward. Please try again later!",
                ephemeral=True
            )
