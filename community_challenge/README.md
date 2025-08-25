# Community Challenge Package

> [!IMPORTANT]  
> Please make sure you read this guide thoroughly, otherwise the package will not be valid, and I will laugh at you if you ask me about this issue.

## Overview

This custom pack is a major breakthrough for me. I finished it in early May 2025, but I didn't plan to release it because I encountered a bottleneck in the automatic reward distribution part. Later, due to my busy school schedule, I decided not to try to update it anymore, so I released this version first.

## Known Issues

This version has several flaws, including:

- If the goal is not achieved by the deadline, the administrator must manually terminate the challenge
- Rewards cannot be automatically distributed to participants, and manual distribution via packages such as rewards is required

## Special Installation Instructions

**Another thing that sets this package apart from others you'll find in this repo is that you'll need to edit countryball.py, where we'll insert a small piece of code.**

Next, I will teach you how to insert the following code in the correct place.

```py
        # trigger community challenge events
        challenge_cog = self.bot.get_cog("CommunityChallengeEvents")
        if challenge_cog:
            import asyncio
            asyncio.create_task(challenge_cog.on_ball_catch(ball))
        else:
            print("[catch_ball] Cannot find CommunityChallengeEvents cog, cannot trigger on_ball_catch")
```

### Modification Steps

The file we need to modify is `ballsdex/packages/countryballs/countryball.py`. Please locate it.

I cannot guarantee where this line of code will be located when you see it, but you can refer to the image below to find the `ball = await BallInstance.create` block and the `logging and stats` block. Insert three spaces between them and ensure that the cursor is in the far left position, as the code snippet I provided has already been indented. In summary, ensure that everything matches what is shown in the image.

![Code insertion location](https://upload.cc/i1/2025/08/25/TMEFqI.png)

## Installation Complete

At this point, you have basically completed this rather special installation process. Next, please follow the basic installation instructions to download the folder and modify the config.

## Function Introduction

As you know, many games have community challenges, whether they are called that or not. So I won't go into detail about that. I will mainly focus on how deep this pack can go.

First, you can decide on the collection targets. There are four options in total: specific ball type, specific regime, specific economy, and specified rarity range. However, I have never used the last option, and it has some flaws, namely that you can only use my fixed rarity range. I know this is unreasonable, but I have no plans to update it at the moment. Therefore, if you are willing, a PR would be great.

Next, you can decide how many balls you need and how long the activity will last, in days.

Once the event has started, you can check the overall progress and your own progress using the commands `/challenge info` and `/challenge progress`. Even after the challenge has ended, `/challenge info` is still available, allowing you to view information about the previous challenge.

Below the embed displayed by these commands, there will be an automatically drawn progress bar that allows users to visually understand the current progress.

> [!NOTE]  
> Only balls that are spawned will be included in the calculation, which means that balls that skip the `def catch_ball` step, such as those from the give command and daily rewards, will not be counted.

Next, let's talk about the record. There are two JSON files responsible for all records, namely `challenges.json` and `challenge_progress.json`. Currently, the way to distribute rewards to all participants is to find `challenge_progress.json` and copy the IDs of each participant one by one.

That should be about it. Also, there will be no automatic notification to inform players when the event starts, so it is best to use a broadcast or announcement channel to let everyone know about it.