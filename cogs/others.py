import datetime
import inspect
import itertools
import json
import os
from typing import Dict, List, Optional, Union

import discord
import psutil
import pygit2
from discord import app_commands, utils
from discord.app_commands import locale_str as _
from discord.ext import commands
from discord.ui import Button, View
from dotenv import load_dotenv

import dev.asset as asset
from ambr import AmbrTopAPI, Character
from apps.db import custom_image
from apps.db.tables.user_settings import Settings
from apps.text_map import text_map, to_ambr_top
from dev.exceptions import AutocompleteError
from dev.models import BotModel, DefaultEmbed, ErrorEmbed, Inter
from ui.others import feedback_menu, manage_accounts, settings, settings_menu
from utils.general import upload_img

load_dotenv()


class OthersCog(commands.Cog, name="others"):
    def __init__(self, bot):
        self.bot: BotModel = bot
        try:
            with open("text_maps/avatar.json", "r", encoding="utf-8") as f:
                self.avatar: Dict[str, Dict[str, str]] = json.load(f)
        except FileNotFoundError:
            self.avatar = {}

    @app_commands.command(
        name="settings",
        description=_("View and change your user settings in Shenhe", hash=534),
    )
    async def settings(self, inter: discord.Interaction):
        i: Inter = inter  # type: ignore
        await settings_menu.return_settings(i)

    @app_commands.command(
        name="accounts", description=_("Manage your accounts in Shenhe", hash=544)
    )
    async def accounts_command(self, inter: discord.Interaction):
        i: Inter = inter  # type: ignore
        view = manage_accounts.View()
        await view.start(i)

    @app_commands.command(
        name="credits",
        description=_("Meet the awesome people that helped me!", hash=297),
    )
    async def view_credits(self, i: discord.Interaction):
        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)
        embed = DefaultEmbed(text_map.get(475, lang) + " 🎉")

        embed.add_field(
            name=text_map.get(298, lang),
            value="""
            [kakaka#7100](https://discord.com/users/425140480334888980) - 🇯🇵
            [Tedd#0660](https://discord.com/users/425140480334888980) - 🇯🇵
            [Ginn#4204](https://discord.com/users/274853284764975104) - 🇺🇸
            [狐狐#8888](https://discord.com/users/274853284764975104) - 🇺🇸
            [Dinnerbone_3rd#8828](https://discord.com/users/808396055879090267) - 🇨🇳
            [xiaokuai#2155](https://discord.com/users/780643463946698813) - 🇨🇳
            [Ayase#9296](https://discord.com/users/501325246390075394) - 🇮🇩
            [Korzzex#1381](https://discord.com/users/871456143216635994) - 🇺🇦            """,
            inline=False,
        )
        embed.add_field(
            name=text_map.get(466, lang),
            value="""
            [GauravM#6722](https://discord.com/users/327390030689730561)
            [KT#7777](https://discord.com/users/153087013447401472)
            [M-307#8132](https://discord.com/users/301178730196238339)
            """,
            inline=False,
        )
        embed.add_field(
            name=text_map.get(479, lang),
            value=text_map.get(497, lang),
            inline=False,
        )
        await i.response.send_message(embed=embed)

    @staticmethod
    def format_commit(commit: pygit2.Commit) -> str:
        short, _, _ = commit.message.partition("\n")
        short_sha2 = commit.hex[0:6]
        commit_tz = datetime.timezone(
            datetime.timedelta(minutes=commit.commit_time_offset)
        )
        commit_time = datetime.datetime.fromtimestamp(commit.commit_time).astimezone(
            commit_tz
        )

        # [`hash`](url) message (offset)
        offset = utils.format_dt((commit_time.astimezone(datetime.timezone.utc)), "R")
        return f"[`{short_sha2}`](https://github.com/seriaati/shenhe_bot/commit/{commit.hex}) {short} ({offset})"

    def get_last_commits(self, count: int = 5):
        repo = pygit2.Repository(".git")
        commits = list(
            itertools.islice(
                repo.walk(repo.head.target, pygit2.GIT_SORT_TOPOLOGICAL), count
            )
        )
        return "\n".join(self.format_commit(c) for c in commits)

    @app_commands.command(name="info", description=_("View the bot's info", hash=63))
    async def view_bot_info(self, i: discord.Interaction):
        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)

        revision = self.get_last_commits()
        embed = DefaultEmbed("申鶴 | Shenhe", f"{text_map.get(296, lang)}\n{revision}")

        seria = self.bot.get_user(410036441129943050) or await self.bot.fetch_user(
            410036441129943050
        )
        embed.set_author(name=str(seria), icon_url=seria.display_avatar.url)

        process = psutil.Process()
        memory_usage = process.memory_full_info().uss / 1024**2  # type: ignore
        cpu_usage = process.cpu_percent() / psutil.cpu_count()  # type: ignore
        embed.add_field(
            name=text_map.get(349, lang),
            value=f"{memory_usage:.2f} MB\n{cpu_usage:.2f}% CPU",
        )

        total = await self.bot.db.users.get_total()
        embed.add_field(
            name=text_map.get(524, lang),
            value=str(total),
        )

        total_members = 0
        total_unique = len(self.bot.users)

        guilds = 0
        for guild in self.bot.guilds:
            guilds += 1
            if guild.unavailable:
                continue
            total_members += guild.member_count or 0

        embed.add_field(
            name=text_map.get(528, lang),
            value=text_map.get(566, lang).format(
                total=total_members, unique=total_unique
            ),
        )

        embed.add_field(
            name=text_map.get(503, lang),
            value=str(guilds),
        )
        embed.add_field(
            name=text_map.get(564, lang),
            value=f"{round(self.bot.latency*1000, 2)} ms",
        )

        delta_uptime = datetime.datetime.utcnow() - self.bot.launch_time
        hours, remainder = divmod(int(delta_uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        embed.add_field(
            name=text_map.get(147, lang),
            value=f"{days}d {hours}h {minutes}m {seconds}s",
        )

        view = View()
        view.add_item(
            Button(
                label=text_map.get(642, lang),
                url="https://discord.gg/ryfamUykRw",
                emoji=asset.discord_emoji,
            )
        )
        view.add_item(
            Button(
                label="GitHub",
                url="https://github.com/seriaati/shenhe_bot",
                emoji=asset.github_emoji,
            )
        )
        await i.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="img-upload",
        description=_("Upload a custom image for /profile character cards", hash=68),
    )
    @app_commands.rename(
        image_file=_("image-file", hash=64),
        image_name=_("image-name", hash=86),
        character_id=_("character", hash=105),
    )
    @app_commands.describe(
        image_file=_("The image file to upload", hash=65),
        image_name=_("The nickname for the image", hash=66),
        character_id=_("The character to use the image", hash=67),
    )
    async def custom_image_upload(
        self,
        inter: discord.Interaction,
        image_file: discord.Attachment,
        image_name: str,
        character_id: str,
    ):
        i: Inter = inter  # type: ignore
        await i.response.defer()

        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)
        ambr = AmbrTopAPI(self.bot.session, to_ambr_top(lang))
        character = await ambr.get_character(character_id)
        if not isinstance(character, Character):
            raise AutocompleteError
        valid = await custom_image.validate_image_url(image_file.url, self.bot.session)
        if not valid:
            embed = ErrorEmbed()
            embed.set_title(274, lang, i.user)
            return await i.followup.send(embed=embed)

        link = await upload_img(
            image_file.url, self.bot.session
        )  # can raise a KeyError if the image is not valid
        converted_character_id = int(character_id.split("-")[0])
        await custom_image.add_user_custom_image(
            i.user.id,
            converted_character_id,
            link,
            image_name,
            self.bot.pool,
        )
        view = settings.custom_image.View(lang)
        view.author = i.user

        await settings.custom_image.return_custom_image_interaction(
            view, i, converted_character_id, character.element
        )

    @custom_image_upload.autocomplete(name="character_id")
    async def custom_image_upload_autocomplete(
        self, i: discord.Interaction, current: str
    ):
        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)
        options = []
        for character_id, character_names in self.avatar.items():
            if any(
                character_id in str(traveler_id) for traveler_id in asset.traveler_ids
            ):
                continue

            if current.lower() in character_names[to_ambr_top(lang)].lower():
                options.append(
                    app_commands.Choice(
                        name=character_names[to_ambr_top(lang)], value=character_id
                    )
                )
        return options[:25]

    @app_commands.command(
        name="feedback", description=_("Send feedback to the bot developer", hash=723)
    )
    async def feedback(self, i: discord.Interaction):
        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)
        await i.response.send_modal(feedback_menu.FeedbackModal(lang))

    @app_commands.command(
        name="source", description=_("View the bot source code", hash=739)
    )
    @app_commands.rename(command=_("command", hash=742))
    @app_commands.describe(
        command=_("Name of command to view the source code of", hash=743)
    )
    async def source(self, i: discord.Interaction, command: Optional[str] = None):
        source_url = "https://github.com/seriaati/shenhe_bot"
        branch = "main"

        if not command:
            return await i.response.send_message(f"<{source_url}>")

        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)

        command_map = self.get_command_map(self.bot.tree)
        obj = command_map.get(command)
        if obj is None:
            return await i.response.send_message(
                embed=ErrorEmbed().set_author(
                    name=text_map.get(740, lang), icon_url=i.user.display_avatar.url
                )
            )

        if not isinstance(
            obj, (app_commands.commands.Command, app_commands.commands.ContextMenu)
        ):
            raise AssertionError

        src = obj.callback.__code__
        module = obj.callback.__module__
        filename = src.co_filename

        lines, firstlineno = inspect.getsourcelines(src)
        if not module.startswith("discord"):
            if filename is None:
                return await i.response.send_message(
                    embed=ErrorEmbed().set_author(
                        name=text_map.get(741, lang),
                        icon_url=i.user.display_avatar.url,
                    )
                )

            location = os.path.relpath(filename).replace("\\", "/")
        else:
            location = module.replace(".", "/") + ".py"
            source_url = "https://github.com/Rapptz/discord.py"
            branch = "master"

        final_url = f"<{source_url}/blob/{branch}/{location}#L{firstlineno}-L{firstlineno + len(lines) - 1}>"
        await i.response.send_message(final_url)

    @source.autocomplete(name="command")
    async def source_autocomplete(
        self, _: discord.Interaction, current: str
    ) -> List[app_commands.Choice]:
        options: List[app_commands.Choice] = []
        command_map = self.get_command_map(self.bot.tree)
        for command_name in command_map:
            if current.lower() in command_name.lower():
                options.append(
                    app_commands.Choice(name=command_name, value=command_name)
                )

        return options[:25]

    @staticmethod
    def get_command_map(
        tree: app_commands.CommandTree,
    ) -> Dict[str, Union[app_commands.Command, app_commands.ContextMenu]]:
        command_map: Dict[
            str, Union[app_commands.commands.Command, app_commands.ContextMenu]
        ] = {}
        for command in tree.get_commands():
            if isinstance(command, app_commands.commands.Group):
                for subcommand in command.commands:
                    if isinstance(subcommand, app_commands.commands.Command):
                        command_map[f"{command.name} {subcommand.name}"] = subcommand
            else:
                command_map[command.name] = command

        return command_map


async def setup(bot: commands.AutoShardedBot) -> None:
    await bot.add_cog(OthersCog(bot))
