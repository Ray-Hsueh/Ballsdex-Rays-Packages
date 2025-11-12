# this is an easy one, just put it in the end of ballsdex/packages/balls/cog.py
# I made this command quite some time ago, but only now have I wanted to share it.
# I know there are many others on the market, and essentially my command is quite similar to theirs, as I was inspired by anythingdex and modelled it on their appearance.
# But I think my code is rather more concise ig?

# import this, you can put it below the "from typing import TYPE_CHECKING, cast"
from collections import defaultdict
from typing import Optional #add this to the original "from typing import TYPE_CHECKING, cast"

from ballsdex.core.utils.transformers import ( #add this to the original from ballsdex.core.utils.transformers import
    EconomyTransform,
    RegimeTransform,
)

# and here's the command
    @app_commands.command()
    @app_commands.describe(
        countryball="The ball to be queried",
        regime="Filter results by route",
        economy="Filter results by station type",
    )
    async def rarity(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        countryball: Optional[BallEnabledTransform] = None,
        regime: Optional[RegimeTransform] = None,
        economy: Optional[EconomyTransform] = None,
    ):
        """
        rarity list for balls, grouped by rarity level, or search for the rarity of a specific ball.

        Parameters
        ----------
        countryball: Ball
            Optional: Check the rarity of a specific ball
        """
        await interaction.response.defer(thinking=True)
        if countryball:
            if regime and countryball.regime_id != regime.id:
                await interaction.followup.send(
                    f"{countryball.country} does not belong to the {regime.name} route.",
                    ephemeral=True,
                )
                return
            if economy and countryball.economy_id != economy.id:
                await interaction.followup.send(
                    f"{countryball.country} does not belong to the {economy.name} station type.",
                    ephemeral=True,
                )
                return
            emoji = self.bot.get_emoji(countryball.emoji_id) or ""
            embed = discord.Embed(
                title=f"Rarity of {countryball.country}",
                description=f"{emoji} {countryball.country}\nRarity: {countryball.rarity}",
                color=discord.Color.blurple(),
            )
            filters = []
            if regime:
                filters.append(f"Route: {regime.name}")
            if economy:
                filters.append(f"Station type: {economy.name}")
            if filters:
                embed.set_footer(text="; ".join(filters))
            await interaction.followup.send(embed=embed)
            return
        balls_list = [ball for ball in balls.values() if ball.enabled]
        if regime:
            balls_list = [ball for ball in balls_list if ball.regime_id == regime.id]
        if economy:
            balls_list = [ball for ball in balls_list if ball.economy_id == economy.id]
        if not balls_list:
            filters = []
            if regime:
                filters.append(regime.name)
            if economy:
                filters.append(economy.name)
            filter_text = ", ".join(filters) if filters else "the selected filters"
            await interaction.followup.send(f"No balls match {filter_text}.")
            return
        balls_list.sort(key=lambda b: (b.rarity, b.country))
        rarity_map = defaultdict(list)
        for ball in balls_list:
            rarity_map[ball.rarity].append(ball)
        rarity_keys = sorted(rarity_map.keys())
        page_size = 5 # change this to adjust number of rarities per page
        pages = []
        for i in range(0, len(rarity_keys), page_size):
            page_rarities = rarity_keys[i:i+page_size]
            desc = ""
            for rarity in page_rarities:
                desc += f"▌Rarity: {rarity}\n"
                for ball in rarity_map[rarity]:
                    emoji = self.bot.get_emoji(ball.emoji_id) or ""
                    desc += f"{emoji} {ball.country}\n"
                desc += "\n"
            pages.append(desc.strip())
        from ballsdex.core.utils import menus
        class RarityPageSource(menus.ListPageSource):
            def __init__(self, pages):
                super().__init__(pages, per_page=1)
            async def format_page(self, menu, page):
                embed = discord.Embed(title="Rarity List", color=discord.Color.blurple())
                embed.description = page
                filters = []
                if regime:
                    filters.append(f"Route: {regime.name}")
                if economy:
                    filters.append(f"Station type: {economy.name}")
                if filters:
                    embed.set_footer(text="; ".join(filters))
                return embed
        source = RarityPageSource(pages)
        paginator = Pages(source=source, interaction=interaction, compact=True)
        await paginator.start()