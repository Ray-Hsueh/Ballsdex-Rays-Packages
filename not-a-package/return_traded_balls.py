# To avoid any misunderstanding, I shall explain the purpose of this command.
# I have personally only used this command once, and it was actually created for a specific case. The purpose of this command is to want to recover illicit gains,
# such as repeatedly using balls produced by farms as gifts and so on, this allows me to first ban the individual abusing the feature, 
# then designate them as `user: discord.User`, after which I can claw back the balls that user has gifted.


# However, it must be noted that this command indiscriminately retrieves all balls, 
# potentially causing unintended damage. It should therefore be used with extreme caution and verified via the admin panel.


# today we gonna edit ballsdex/packages/admin/cog.py
# first we need to add some imports, just two easy
import datetime
from tortoise.expressions import Q
# paste following codes to the end of the cog, and you are done
    @app_commands.command()
    @app_commands.checks.has_any_role(*settings.root_role_ids)
    async def return_traded_balls(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        user: discord.User,
        days: int | None = None,
    ):
        """
        Return the ball traded by the designated user to that user.

        Parameters
        ----------
        user: discord.User
            The user who needs to return the ball.
        days: int | None
            Only trades within the specified number of days will be returned; if no specified, all trades will be returned.
        """
        await interaction.response.defer()
        
        try:
            player = await Player.get(discord_id=user.id)
        except DoesNotExist:
            await interaction.followup.send("The user has not yet registered.")
            return

        queryset = Trade.filter(Q(player1=player) | Q(player2=player))
        if days is not None and days > 0:
            end_date = datetime.datetime.now()
            start_date = end_date - datetime.timedelta(days=days)
            queryset = queryset.filter(date__range=(start_date, end_date))
        
        trades = await queryset.prefetch_related("player1", "player2", "tradeobjects", "tradeobjects__ballinstance")
        
        if not trades:
            await interaction.followup.send("No trading records were found.")
            return

        returned_balls = 0
        for trade in trades:
            trade_objects = await trade.tradeobjects.filter(player=player).prefetch_related("ballinstance")
            for trade_object in trade_objects:
                ball = trade_object.ballinstance
                if ball.player_id != player.id:
                    ball.player = player
                    ball.trade_player = None
                    ball.favorite = False
                    await ball.save()
                    returned_balls += 1

        if returned_balls > 0:
            await interaction.followup.send(
                f"{returned_balls} balls have been successfully returned to {user}."
            )
        else:
            await interaction.followup.send(
                f"No ball requiring return has been found."
            )
