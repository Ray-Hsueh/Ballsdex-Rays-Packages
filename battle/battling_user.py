from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    import discord
    from ballsdex.core.models import BallInstance, Player


@dataclass(slots=True)
class BattlingUser:
    user: "discord.User | discord.Member"
    player: "Player"
    proposal: List["BallInstance"] = field(default_factory=list)
    locked: bool = False