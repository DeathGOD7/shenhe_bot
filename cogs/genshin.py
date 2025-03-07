import json
import random
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import aiofiles
import discord
from discord import app_commands
from discord.app_commands import locale_str as _
from discord.ext import commands
from discord.utils import format_dt
from dotenv import load_dotenv
from enkanetwork import Assets
from genshin import Client
from genshin.models import Notes

import dev.asset as asset
import dev.exceptions as exceptions
import dev.models as models
import ui
import utils.general as general
from ambr import AmbrTopAPI, Character, Material, Weapon
from apps.db.json import read_json
from apps.db.tables.user_settings import Settings
from apps.draw import main_funcs
from apps.genshin import enka, leaderboard
from apps.genshin_data import abyss
from apps.text_map import convert_locale, text_map
from data.cards.dice_element import get_dice_emoji
from dev.enum import GameType
from ui.others import manage_accounts
from utils import disable_view_items, get_character_emoji, get_uid_region_hash
from utils.genshin import update_talents_json
from utils.text_map import get_game_name

load_dotenv()


class GenshinCog(commands.Cog, name="genshin"):
    def __init__(self, bot):
        self.bot: models.BotModel = bot
        self.debug = self.bot.debug

        # Right click commands
        self.search_uid_context_menu = app_commands.ContextMenu(
            name=_("UID"), callback=self.search_uid_ctx_menu
        )
        self.profile_context_menu = app_commands.ContextMenu(
            name=_("Profile", hash=498), callback=self.profile_ctx_menu
        )
        self.characters_context_menu = app_commands.ContextMenu(
            name=_("Characters", hash=499), callback=self.characters_ctx_menu
        )
        self.stats_context_menu = app_commands.ContextMenu(
            name=_("Stats", hash=56), callback=self.stats_ctx_menu
        )
        self.check_context_menu = app_commands.ContextMenu(
            name=_("Realtime notes", hash=24), callback=self.check_ctx_menu
        )
        self.bot.tree.add_command(self.search_uid_context_menu)
        self.bot.tree.add_command(self.profile_context_menu)
        self.bot.tree.add_command(self.characters_context_menu)
        self.bot.tree.add_command(self.stats_context_menu)
        self.bot.tree.add_command(self.check_context_menu)

    async def cog_load(self) -> None:
        async with self.bot.session.get(
            "https://genshin-db-api.vercel.app/api/languages"
        ) as r:
            languages = await r.json()

        self.card_data: Dict[str, List[Dict[str, Any]]] = {}
        for lang in languages:
            try:
                async with aiofiles.open(
                    f"data/cards/card_data_{lang}.json", "r", encoding="utf-8"
                ) as f:
                    self.card_data[lang] = json.loads(await f.read())
            except FileNotFoundError:
                self.card_data[lang] = []

        maps_to_open = (
            "avatar",
            "weapon",
            "material",
            "reliquary",
            "monster",
            "food",
            "furniture",
            "namecard",
            "book",
        )
        self.text_map_files: List[Dict[str, Any]] = []
        for map_ in maps_to_open:
            try:
                async with aiofiles.open(
                    f"text_maps/{map_}.json", "r", encoding="utf-8"
                ) as f:
                    data = json.loads(await f.read())
            except FileNotFoundError:
                data = {}
            self.text_map_files.append(data)
        try:
            async with aiofiles.open(
                "text_maps/item_name.json", "r", encoding="utf-8"
            ) as f:
                self.item_names = json.loads(await f.read())
        except FileNotFoundError:
            self.item_names = {}

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(
            self.search_uid_context_menu.name, type=self.search_uid_context_menu.type
        )
        self.bot.tree.remove_command(
            self.profile_context_menu.name, type=self.profile_context_menu.type
        )
        self.bot.tree.remove_command(
            self.characters_context_menu.name, type=self.characters_context_menu.type
        )
        self.bot.tree.remove_command(
            self.stats_context_menu.name, type=self.stats_context_menu.type
        )
        self.bot.tree.remove_command(
            self.check_context_menu.name, type=self.check_context_menu.type
        )

    @app_commands.command(
        name="register",
        description=_(
            "Register your genshin account in shenhe's database to use commands that require one",
            hash=410,
        ),
    )
    async def slash_register(self, inter: discord.Interaction):
        i: models.Inter = inter  # type: ignore
        view = manage_accounts.View()
        await view.start(i)

    @app_commands.command(
        name="check",
        description=_("Check resin, pot, and expedition status", hash=414),
    )
    @app_commands.rename(member=_("user", hash=415), acc=_("account", hash=791))
    @app_commands.describe(
        member=_("Check other user's data", hash=416),
        acc=_("Check data of your other accounts", hash=792),
    )
    async def slash_check(
        self,
        i: discord.Interaction,
        member: Optional[discord.User | discord.Member] = None,
        acc: Optional[int] = None,
    ):
        await self.check_command(i, member or i.user, acc=acc)

    async def check_ctx_menu(self, i: discord.Interaction, member: discord.User):
        await self.check_command(i, member, ephemeral=True)

    async def check_command(
        self,
        i: discord.Interaction,
        member: Optional[discord.User | discord.Member] = None,
        ephemeral: bool = False,
        acc: Optional[int] = None,
    ):
        await i.response.defer(ephemeral=ephemeral)
        member = member or i.user

        if acc:
            try:
                user = await self.bot.db.users.get(member.id, uid=acc)
            except exceptions.AccountNotFound:
                raise exceptions.AutocompleteError
        else:
            user = await self.bot.db.users.get(member.id)
        supported = (GameType.GENSHIN, GameType.HSR)
        if user.game not in supported:
            raise exceptions.GameNotSupported(user.game, supported)

        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG)
        lang = lang or str(i.locale)
        dark_mode = await self.bot.db.settings.get(i.user.id, Settings.DARK_MODE)
        draw_input = models.DrawInput(
            loop=self.bot.loop,
            session=self.bot.session,
            lang=lang,
            dark_mode=dark_mode,
        )

        client = await user.client
        client.lang = convert_locale.to_genshin_py(lang)
        if user.game is GameType.GENSHIN:
            notes = await client.get_genshin_notes(user.uid)
            fp = await main_funcs.draw_realtime_card(
                draw_input,
                notes,
            )
        else:
            notes = await client.get_starrail_notes(user.uid)
            fp = await main_funcs.draw_hsr_check_card(draw_input, notes)

        fp.seek(0)
        if isinstance(notes, Notes):
            await i.followup.send(
                embed=self.parse_notes_embed(notes, lang),
                file=discord.File(fp, filename="realtime_notes.webp"),
                ephemeral=ephemeral,
            )
        else:
            await i.followup.send(
                file=discord.File(fp, filename="hsr_check.webp"), ephemeral=ephemeral
            )

    @staticmethod
    def parse_notes_embed(notes: Notes, lang: str) -> models.DefaultEmbed:
        if notes.current_resin == notes.max_resin:
            resin_recover_time = text_map.get(1, lang)
        else:
            resin_recover_time = format_dt(notes.resin_recovery_time, "R")

        if notes.current_realm_currency == notes.max_realm_currency:
            realm_recover_time = text_map.get(1, lang)
        else:
            realm_recover_time = format_dt(notes.realm_currency_recovery_time, "R")
        if (
            notes.remaining_transformer_recovery_time is None
            or notes.transformer_recovery_time is None
        ):
            transformer_recover_time = text_map.get(11, lang)
        else:
            if notes.remaining_transformer_recovery_time.total_seconds() <= 0:
                transformer_recover_time = text_map.get(9, lang)
            else:
                transformer_recover_time = format_dt(
                    notes.transformer_recovery_time, "R"
                )
        result = models.DefaultEmbed(
            text_map.get(24, lang),
            f"""
            {asset.resin_emoji} {text_map.get(15, lang)}: {resin_recover_time}
            {asset.realm_currency_emoji} {text_map.get(15, lang)}: {realm_recover_time}
            {asset.pt_emoji} {text_map.get(8, lang)}: {transformer_recover_time}
            """,
        )
        if notes.expeditions:
            expedition_str = ""
            for expedition in notes.expeditions:
                if expedition.remaining_time.total_seconds() > 0:
                    expedition_str += (
                        f'- {format_dt(expedition.completion_time, "R")}\n'
                    )
            if expedition_str:
                result.add_field(
                    name=text_map.get(20, lang),
                    value=expedition_str,
                    inline=False,
                )
        result.set_image(url="attachment://realtime_notes.png")
        return result

    @slash_check.autocomplete("acc")
    async def autocomplete(self, i: discord.Interaction, current: str):
        return await self.acc_autocomplete(i, current)

    async def acc_autocomplete(self, i: discord.Interaction, current: str):
        choices: List[app_commands.Choice] = []
        user: Optional[Union[discord.Member, discord.User]] = i.namespace.user
        user = user or i.user
        accs = await self.bot.db.users.get_all_of_user(user.id)
        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG)
        lang = lang or str(i.locale)
        for acc in accs:
            if not current or str(acc.uid).startswith(current):
                name = f"{acc.uid}"
                if acc.nickname:
                    name += f" ({acc.nickname})"
                game_name = get_game_name(acc.game, lang)
                name += f" - {game_name}"
                choices.append(app_commands.Choice(name=name, value=str(acc.uid)))

        return choices[:25]

    @app_commands.command(
        name="stats",
        description=_(
            "View your genshin stats: Active days, oculi number, and number of chests obtained",
            hash=417,
        ),
    )
    @app_commands.rename(member=_("user", hash=415))
    @app_commands.describe(
        member=_("Check other user's data", hash=416),
    )
    async def stats(
        self,
        i: discord.Interaction,
        member: Optional[discord.User | discord.Member] = None,
    ):
        await self.stats_command(i, member)

    async def stats_ctx_menu(self, i: discord.Interaction, member: discord.User):
        await self.stats_command(i, member, context_command=True)

    async def stats_command(
        self,
        i: discord.Interaction,
        member: Optional[discord.User | discord.Member] = None,
        context_command: bool = False,
    ) -> None:
        await i.response.defer()
        member = member or i.user

        user = await self.bot.db.users.get(member.id)
        if user.game is not GameType.GENSHIN:
            raise exceptions.GameNotSupported(user.game, [GameType.GENSHIN])

        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG)
        lang = lang or str(i.locale)
        dark_mode = await self.bot.db.settings.get(i.user.id, Settings.DARK_MODE)

        enka_info = await enka.get_enka_info(user.uid, self.bot.session)
        namecard_id = enka_info.player_info.name_card_id
        assets = Assets()
        namecard = assets.namecards(namecard_id)
        if namecard is None:
            raise AssertionError("Namecard not found")

        fp = self.bot.stats_card_cache.get(user.uid)
        if fp is None:
            client = await user.client
            client.lang = convert_locale.to_genshin_py(lang)
            genshin_user = await client.get_partial_genshin_user(user.uid)
            ambr = AmbrTopAPI(self.bot.session)
            characters = await ambr.get_character(
                include_beta=False, include_traveler=False
            )
            if not isinstance(characters, List):
                raise TypeError("Characters is not a list")

            fp = await main_funcs.draw_stats_card(
                models.DrawInput(
                    loop=self.bot.loop, session=self.bot.session, dark_mode=dark_mode
                ),
                namecard,
                genshin_user.stats,
                member.display_avatar,
                len(characters),
            )
            self.bot.stats_card_cache[user.uid] = fp

        fp.seek(0)
        _file = discord.File(fp, "stat_card.png")
        await i.followup.send(
            ephemeral=context_command,
            file=_file,
        )

    @app_commands.command(
        name="area",
        description=_("View exploration rates of different areas in genshin", hash=419),
    )
    @app_commands.rename(member=_("user", hash=415))
    @app_commands.describe(
        member=_("Check other user's data", hash=416),
    )
    async def area(
        self,
        i: discord.Interaction,
        member: Optional[discord.User | discord.Member] = None,
    ):
        await i.response.defer()
        member = member or i.user

        user = await self.bot.db.users.get(member.id)
        if user.game is not GameType.GENSHIN:
            raise exceptions.GameNotSupported(user.game, [GameType.GENSHIN])

        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG)
        lang = lang or str(i.locale)
        dark_mode = await self.bot.db.settings.get(i.user.id, Settings.DARK_MODE)

        client = await user.client
        client.lang = convert_locale.to_genshin_py(lang)
        genshin_user = await client.get_partial_genshin_user(user.uid)
        explorations = genshin_user.explorations

        fp = self.bot.area_card_cache.get(user.uid)
        if fp is None:
            fp = await main_funcs.draw_area_card(
                models.DrawInput(
                    loop=self.bot.loop, session=self.bot.session, dark_mode=dark_mode
                ),
                list(explorations),
            )
        fp.seek(0)

        file_ = discord.File(fp, "area.png")
        await i.followup.send(file=file_)

    @app_commands.command(
        name="claim",
        description=_(
            "View info about your Hoyolab daily check-in rewards",
            hash=420,
        ),
    )
    async def claim(self, inter: discord.Interaction):
        i: models.Inter = inter  # type: ignore
        view = ui.daily_checkin.View()
        await view.start(i)

    @app_commands.command(
        name="characters",
        description=_(
            "View all owned characters (need /register)",
            hash=421,
        ),
    )
    @app_commands.rename(member=_("user", hash=415))
    @app_commands.describe(member=_("Check other user's data", hash=416))
    async def characters(
        self,
        i: discord.Interaction,
        member: Optional[discord.User | discord.Member] = None,
    ):
        await self.characters_comamnd(i, member, False)

    async def characters_ctx_menu(self, i: discord.Interaction, member: discord.User):
        await self.characters_comamnd(i, member)

    async def characters_comamnd(
        self,
        inter: discord.Interaction,
        member: Optional[discord.User | discord.Member] = None,
        ephemeral: bool = True,
    ):
        i: models.Inter = inter  # type: ignore
        member = member or i.user

        user = await self.bot.db.users.get(member.id)
        if user.game is not GameType.GENSHIN:
            raise exceptions.GameNotSupported(user.game, [GameType.GENSHIN])

        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG)
        lang = lang or str(i.locale)

        await i.response.send_message(
            embed=models.DefaultEmbed().set_author(
                name=text_map.get(765, lang), icon_url=asset.loader
            ),
            ephemeral=ephemeral,
        )

        client = await user.client
        client.lang = convert_locale.to_genshin_py(lang)
        g_characters = await client.get_genshin_characters(user.uid)
        g_characters = list(g_characters)

        talents = await read_json(self.bot.pool, f"talents/{user.uid}.json")
        if talents is None:
            await update_talents_json(
                g_characters, client, self.bot.pool, user.uid, self.bot.session
            )

        client = AmbrTopAPI(self.bot.session)
        characters = await client.get_character(
            include_beta=False, include_traveler=False
        )
        if not isinstance(characters, list):
            raise TypeError("Characters is not a list")

        view = ui.show_all_characters.View(lang, g_characters, member, characters)
        await view.start(i)

    @app_commands.command(
        name="diary",
        description=_(
            "View your traveler's diary: primo and mora income (needs /register)",
            hash=422,
        ),
    )
    @app_commands.rename(member=_("user", hash=415))
    @app_commands.describe(
        member=_("Check other user's data", hash=416),
    )
    async def diary(
        self,
        inter: discord.Interaction,
        member: Optional[discord.User | discord.Member] = None,
    ):
        i: models.Inter = inter  # type: ignore
        member = member or i.user
        view = ui.diary_view.View()
        await view.start(i, member)

    @app_commands.command(
        name="abyss",
        description=_("View abyss information", hash=428),
    )
    @app_commands.rename(
        previous=_("season", hash=430),
        member=_("user", hash=415),
    )
    @app_commands.describe(
        previous=_("Which abyss season?", hash=432),
        member=_("Check other user's data", hash=416),
    )
    @app_commands.choices(
        previous=[
            app_commands.Choice(name=_("Current season", hash=435), value=0),
            app_commands.Choice(name=_("Last season", hash=436), value=1),
        ],
    )
    async def abyss(
        self,
        i: discord.Interaction,
        previous: int = 0,
        member: Optional[discord.User | discord.Member] = None,
    ):
        member = member or i.user
        await i.response.defer()

        user = await self.bot.db.users.get(member.id)
        if user.game is not GameType.GENSHIN:
            raise exceptions.GameNotSupported(user.game, [GameType.GENSHIN])

        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG)
        lang = lang or str(i.locale)
        dark_mode = await self.bot.db.settings.get(i.user.id, Settings.DARK_MODE)

        client = await user.client
        abyss_data = await client.get_genshin_spiral_abyss(
            user.uid, previous=bool(previous)
        )
        if not abyss_data.ranks.most_kills:
            raise exceptions.AbyssDataNotFound
        g_user = await client.get_partial_genshin_user(user.uid)
        characters = await client.get_genshin_characters(user.uid)

        overview = models.DefaultEmbed()
        overview.set_image(url="attachment://overview_card.png")
        overview.set_author(
            name=f"{text_map.get(85, lang)} | {text_map.get(77, lang)} {abyss_data.season}",
            icon_url=member.display_avatar.url,
        )
        overview.set_footer(text=text_map.get(254, lang))

        cache = self.bot.abyss_overview_card_cache
        fp = cache.get(user.uid)
        if fp is None:
            fp = await main_funcs.draw_abyss_overview_card(
                models.DrawInput(
                    loop=self.bot.loop,
                    session=self.bot.session,
                    lang=lang,
                    dark_mode=dark_mode,
                ),
                abyss_data,
                g_user,
            )
            cache[user.uid] = fp

        abyss_result = models.AbyssResult(
            embed_title=f"{text_map.get(47, lang)} | {text_map.get(77, lang)} {abyss_data.season}",
            abyss=abyss_data,
            genshin_user=g_user,
            discord_user=member,
            overview_embed=overview,
            overview_file=fp,
            abyss_floors=list(abyss_data.floors),
            characters=list(characters),
            uid=user.uid,
        )
        view = ui.abyss_view.View(i.user, abyss_result, lang)
        fp.seek(0)
        image = discord.File(fp, "overview_card.png")
        await i.followup.send(
            embed=abyss_result.overview_embed, view=view, files=[image]
        )
        view.message = await i.original_response()

        if abyss_result.abyss.max_floor != "0-0":
            await leaderboard.update_user_abyss_leaderboard(
                abyss_result.abyss,
                abyss_result.genshin_user,
                abyss_result.characters,
                abyss_result.uid,
                abyss_result.genshin_user.info.nickname,
                i.user.id,
                previous,
                self.bot.pool,
            )

    @app_commands.command(name="stuck", description=_("Data not public?", hash=149))
    async def stuck(self, i: discord.Interaction):
        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)
        embed = models.DefaultEmbed(
            text_map.get(149, lang),
            text_map.get(150, lang),
        )
        embed.set_image(url="https://i.imgur.com/w6Q7WwJ.gif")
        await i.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="remind", description=_("Set reminders", hash=438))
    async def remind(self, inter: discord.Interaction):
        i: models.Inter = inter  # type: ignore
        view = ui.reminder_menu.View()
        await view.start(i)

    @app_commands.command(
        name="farm", description=_("View today's farmable items", hash=446)
    )
    async def farm(self, inter: discord.Interaction):
        i: models.Inter = inter  # type: ignore
        await ui.domain_view.return_farm_interaction(i)

    @app_commands.command(
        name="build",
        description=_(
            "View character builds: Talent levels, artifacts, weapons", hash=447
        ),
    )
    async def build(self, i: discord.Interaction):
        view = ui.build_view.View()
        view.author = i.user
        await i.response.send_message(view=view)
        view.message = await i.original_response()

    @app_commands.command(
        name="uid",
        description=_(
            "Search a user's genshin UID (if they are registered in shenhe)", hash=448
        ),
    )
    @app_commands.rename(player=_("user", hash=415))
    async def search_uid(self, i: discord.Interaction, player: discord.User):
        await self.search_uid_command(i, player, False)

    async def search_uid_ctx_menu(self, i: discord.Interaction, player: discord.User):
        await self.search_uid_command(i, player)

    async def search_uid_command(
        self, inter: discord.Interaction, player: discord.User, ephemeral: bool = True
    ):
        i: models.Inter = inter  # type: ignore
        lang = await i.client.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)
        uid = await self.bot.db.users.get_uid(player.id)

        embed = models.DefaultEmbed()
        embed.add_field(
            name=f"{text_map.get(167, lang).format(name=player.display_name)}",
            value=str(uid),
            inline=False,
        )
        embed.add_field(
            name=text_map.get(727, lang),
            value=text_map.get(get_uid_region_hash(uid), lang),
            inline=False,
        )
        embed.set_thumbnail(url=player.display_avatar.url)

        view = ui.uid_command.View(lang, uid)
        await i.response.send_message(embed=embed, ephemeral=ephemeral, view=view)
        view.message = await i.original_response()

    @app_commands.command(
        name="profile",
        description=_(
            "View your in-game profile with UID",
            hash=449,
        ),
    )
    @app_commands.choices(
        game=[
            app_commands.Choice(name=_("Genshin Impact", hash=313), value="genshin"),
            app_commands.Choice(name=_("Honkai: Star Rail", hash=770), value="hsr"),
        ]
    )
    @app_commands.rename(
        member=_("user", hash=415),
        custom_uid="uid",
        game=_("game", hash=784),
        account=_("account", hash=791),
    )
    @app_commands.describe(
        member=_("Check other user's data", hash=416),
        custom_uid=_("Specify the UID to search the profile with", hash=799),
        game=_("Specify the game to search the profile with", hash=800),
        account=_("Check data of your other accounts", hash=792),
    )
    async def profile(
        self,
        inter: discord.Interaction,
        member: Optional[discord.User | discord.Member] = None,
        custom_uid: Optional[int] = None,
        game: Optional[str] = None,
        account: Optional[str] = None,
    ):
        i: models.Inter = inter  # type: ignore
        await self.profile_command(
            i,
            member=member,
            custom_uid=custom_uid,
            game=game,
            account=account,
            ephemeral=False,
        )

    @profile.autocomplete("account")
    async def profile_account_autocomplete(self, i: discord.Interaction, current: str):
        return await self.acc_autocomplete(i, current)

    async def profile_ctx_menu(self, inter: discord.Interaction, member: discord.User):
        i: models.Inter = inter  # type: ignore
        await self.profile_command(i, member=member, ephemeral=False)

    async def profile_command(
        self,
        i: models.Inter,
        *,
        member: Optional[Union[discord.User, discord.Member]] = None,
        custom_uid: Optional[int] = None,
        game: Optional[str] = None,
        account: Optional[str] = None,
        ephemeral: bool = True,
    ):
        await i.response.defer(ephemeral=ephemeral)
        member = member or i.user

        uid = custom_uid
        game_ = GameType(game) if game else GameType.GENSHIN

        if uid is None:
            try:
                if account:
                    user = await self.bot.db.users.get(member.id, uid=int(account))
                else:
                    user = await self.bot.db.users.get(member.id)
            except exceptions.AccountNotFound as e:
                if account:
                    raise exceptions.AutocompleteError
                raise e
            else:
                uid = user.uid
                game_ = user.game
        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)

        if game_ is GameType.HSR:
            view = ui.mihomo_profile.View()
            await view.start(i, uid, lang)
        elif game_ is GameType.GENSHIN:
            data, en_data, card_data = await enka.get_enka_data(
                uid, convert_locale.ENKA_LANGS.get(lang, "en"), self.bot.pool
            )

            embeds = [
                models.DefaultEmbed()
                .set_author(
                    name=text_map.get(644, lang),
                    icon_url=asset.loader,
                )
                .set_image(url="https://i.imgur.com/3U1bJ0Z.gif"),
                models.DefaultEmbed()
                .set_author(
                    name=text_map.get(644, lang),
                    icon_url=asset.loader,
                )
                .set_image(url="https://i.imgur.com/25pdyUG.gif"),
            ]

            options: List[discord.SelectOption] = []
            non_cache_ids: List[int] = []
            if card_data and card_data.characters:
                non_cache_ids = [c.id for c in card_data.characters]

            for c in data.characters:
                if c.id not in non_cache_ids:
                    description = text_map.get(543, lang)
                else:
                    description = None
                label = f"{c.name} | Lv.{c.level} | C{c.constellations_unlocked}R{c.equipments[-1].refinement}"
                emoji = get_character_emoji(str(c.id))
                options.append(
                    discord.SelectOption(
                        label=label,
                        description=description,
                        value=str(c.id),
                        emoji=emoji,
                    )
                )

            view = ui.enka_profile.View([], lang)
            disable_view_items(view)

            await i.edit_original_response(
                embeds=embeds,
                attachments=[],
                view=view,
            )

            in_x_seconds = format_dt(
                general.get_dt_now() + timedelta(seconds=data.ttl), "R"
            )
            embed = models.DefaultEmbed(
                text_map.get(144, lang),
                f"""
                {asset.link_emoji} [{text_map.get(588, lang)}](https://enka.cc/u/{uid})
                {asset.time_emoji} {text_map.get(589, lang).format(in_x_seconds=in_x_seconds)}
                """,
            )
            embed.set_image(url="attachment://profile.png")
            embed_two = models.DefaultEmbed(text_map.get(145, lang))
            embed_two.set_image(url="attachment://character.png")
            embed_two.set_footer(text=text_map.get(511, lang))

            dark_mode = await self.bot.db.settings.get(i.user.id, Settings.DARK_MODE)
            fp, fp_two = await main_funcs.draw_profile_overview_card(
                models.DrawInput(
                    loop=self.bot.loop,
                    session=self.bot.session,
                    lang=lang,
                    dark_mode=dark_mode,
                ),
                card_data or data,
            )
            fp.seek(0)
            fp_two.seek(0)

            view = ui.enka_profile.View(options, lang)
            view.overview_embeds = [embed, embed_two]
            view.overview_fps = [fp, fp_two]
            view.data = data
            view.en_data = en_data
            view.card_data = card_data
            view.member = member
            view.author = i.user
            view.lang = lang

            file_one = discord.File(fp, filename="profile.png")
            file_two = discord.File(fp_two, filename="character.png")
            await i.edit_original_response(
                embeds=[embed, embed_two],
                view=view,
                attachments=[file_one, file_two],
            )
            view.message = await i.original_response()
        else:
            raise exceptions.GameNotSupported(game_, [GameType.GENSHIN, GameType.HSR])

    @app_commands.command(name="redeem", description=_("Redeem a gift code", hash=450))
    async def redeem(self, inter: discord.Interaction):
        i: models.Inter = inter  # type: ignore
        view = ui.redeem.View()
        await view.start(i)

    @app_commands.command(
        name="events", description=_("View ongoing genshin events", hash=452)
    )
    async def events(self, inter: discord.Interaction):
        i: models.Inter = inter  # type: ignore
        await ui.event_type_chooser.return_events(i)

    @app_commands.command(
        name="leaderboard", description=_("The Shenhe leaderboard", hash=252)
    )
    async def leaderboard(self, inter: discord.Interaction):
        i: models.Inter = inter  # type: ignore
        view = ui.leaderboard_view.View()
        await view.start(i)

    @app_commands.command(
        name="search", description=_("Search anything related to genshin", hash=508)
    )
    @app_commands.rename(query=_("query", hash=509))
    async def search(self, inter: discord.Interaction, query: str):
        i: models.Inter = inter  # type: ignore

        if not query.isdigit():
            raise exceptions.AutocompleteError

        await i.response.defer()

        user_locale = await self.bot.db.settings.get(i.user.id, Settings.LANG)
        lang = user_locale or i.locale
        ambr_top_locale = convert_locale.to_ambr_top(lang)
        dark_mode = await self.bot.db.settings.get(i.user.id, Settings.DARK_MODE)
        client = AmbrTopAPI(self.bot.session, ambr_top_locale)

        item_type = None
        for index, file in enumerate(self.text_map_files):
            if query in file:
                item_type = index
                break
        if item_type is None:
            raise exceptions.ItemNotFound

        if item_type == 0:  # character
            character = await client.get_character_detail(query)
            if character is None:
                raise exceptions.ItemNotFound
            await ui.search_nav.parse_character_wiki(
                character, i, lang, client, dark_mode
            )

        elif item_type == 1:  # weapon
            weapon = await client.get_weapon_detail(int(query))
            if weapon is None:
                raise exceptions.ItemNotFound
            await ui.search_nav.parse_weapon_wiki(weapon, i, lang, client, dark_mode)

        elif item_type == 2:  # material
            material = await client.get_material_detail(int(query))
            if material is None:
                raise exceptions.ItemNotFound
            await ui.search_nav.parse_material_wiki(
                material, i, lang, client, dark_mode
            )

        elif item_type == 3:  # artifact
            artifact = await client.get_artifact_detail(int(query))
            if artifact is None:
                raise exceptions.ItemNotFound
            await ui.search_nav.parse_artifact_wiki(artifact, i, lang)

        elif item_type == 4:  # monster
            monster = await client.get_monster_detail(int(query))
            if monster is None:
                raise exceptions.ItemNotFound
            await ui.search_nav.parse_monster_wiki(monster, i, lang, client, dark_mode)

        elif item_type == 5:  # food
            food = await client.get_food_detail(int(query))
            if food is None:
                raise exceptions.ItemNotFound
            await ui.search_nav.parse_food_wiki(food, i, lang, client, dark_mode)

        elif item_type == 6:  # furniture
            furniture = await client.get_furniture_detail(int(query))
            if furniture is None:
                raise exceptions.ItemNotFound
            await ui.search_nav.parse_furniture_wiki(
                furniture, i, lang, client, dark_mode
            )

        elif item_type == 7:  # namecard
            namecard = await client.get_name_card_detail(int(query))
            if namecard is None:
                raise exceptions.ItemNotFound
            await ui.search_nav.parse_namecard_wiki(namecard, i, lang)

        elif item_type == 8:  # book
            book = await client.get_book_detail(int(query))
            if book is None:
                raise exceptions.ItemNotFound
            await ui.search_nav.parse_book_wiki(book, i, lang, client)

    @search.autocomplete("query")
    async def query_autocomplete(
        self, i: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG)
        lang = lang or str(i.locale)
        ambr_top_locale = convert_locale.to_ambr_top(lang)
        result: List[app_commands.Choice] = []
        for queries in self.text_map_files:
            for item_id, query_names in queries.items():
                if item_id in ("10000005", "10000007"):
                    continue

                item_name = query_names[ambr_top_locale]
                if current.lower() in item_name.lower() and item_name:
                    result.append(app_commands.Choice(name=item_name, value=item_id))
                elif " " in current:
                    splited = current.split(" ")
                    all_match = True
                    for word in splited:
                        if word.lower() not in item_name.lower():
                            all_match = False
                            break
                    if all_match and item_name != "":
                        result.append(
                            app_commands.Choice(name=item_name, value=item_id)
                        )
        if not current:
            random.shuffle(result)
        return result[:25]

    @app_commands.command(
        name="beta",
        description=_("View the list of current beta items in Genshin", hash=434),
    )
    async def view_beta_items(self, i: discord.Interaction):
        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG)
        lang = lang or str(i.locale)

        client = AmbrTopAPI(self.bot.session, convert_locale.to_ambr_top(lang))
        result = ""
        first_icon_url = ""
        characters = await client.get_character()
        weapons = await client.get_weapon()
        materials = await client.get_material()
        things = [characters, weapons, materials]
        for thing in things:
            result, first_icon_url = self.get_beta_items(result, thing, first_icon_url)
        if result == "":
            result = text_map.get(445, lang)
        embed = models.DefaultEmbed(text_map.get(437, lang), result)
        if first_icon_url != "":
            embed.set_thumbnail(url=first_icon_url)
        embed.set_footer(text=text_map.get(444, lang))
        await i.response.send_message(embed=embed)

    @staticmethod
    def get_beta_items(
        result: str,
        items: List[Character | Weapon | Material],
        first_icon_url: str,
    ) -> Tuple[str, str]:
        for item in items:
            if item.beta:
                if item.name == "？？？":
                    continue
                result += f"• {item.name}\n"
                if first_icon_url == "":
                    first_icon_url = item.icon
        return result, first_icon_url

    @app_commands.command(
        name="banners", description=_("View ongoing Genshin banners", hash=375)
    )
    async def banners(self, i: discord.Interaction):
        await i.response.defer()

        lang = await self.bot.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)
        lang = convert_locale.to_genshin_py(lang)
        client = Client()

        zh_tw_annoucements = await client.get_genshin_announcements(lang="zh-tw")
        annoucements = await client.get_genshin_announcements(lang=lang)
        now = general.get_dt_now(True)
        banner_ids = [
            a.id for a in zh_tw_annoucements if "祈願" in a.title and a.end_time > now
        ]
        banners = [a for a in annoucements if a.id in banner_ids]
        banners.sort(key=lambda x: x.end_time)
        if not banners:
            return await i.followup.send(
                embed=models.DefaultEmbed(
                    description=text_map.get(376, lang)
                ).set_author(name=text_map.get(23, lang))
            )

        fp = await main_funcs.draw_banner_card(
            models.DrawInput(loop=self.bot.loop, session=self.bot.session, lang=lang),
            [w.banner for w in banners],
        )
        fp.seek(0)

        await i.followup.send(
            embed=models.DefaultEmbed(
                text_map.get(746, lang),
                text_map.get(381, lang).format(
                    time=format_dt(
                        banners[0].end_time,
                        "R",
                    )
                ),
            ).set_image(url="attachment://banner.png"),
            file=discord.File(fp, "banner.png"),
        )

    @app_commands.command(
        name="abyss-enemies",
        description=_("View the list of enemies in the current abyss phases", hash=294),
    )
    async def abyss_enemies(self, inter: discord.Interaction):
        i: models.Inter = inter  # type: ignore
        await i.response.defer()
        lang = await i.client.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)
        floors = await abyss.get_abyss_enemies(self.bot.gd_text_map, lang)

        ley_line_disorders = await abyss.get_ley_line_disorders(
            self.bot.gd_text_map, lang
        )

        embeds: Dict[str, discord.Embed] = {}
        enemies: Dict[str, List[models.AbyssHalf]] = {}
        for floor in floors:
            for chamber in floor.chambers:
                embed = models.DefaultEmbed(
                    f"{text_map.get(146, lang).format(a=floor.num)} - {text_map.get(177, lang).format(a=chamber.num)}"
                )
                embed.add_field(
                    name=text_map.get(706, lang),
                    value=general.add_bullet_points(
                        ley_line_disorders.get(floor.num, [])
                    ),
                    inline=False,
                )
                embed.add_field(
                    name=text_map.get(295, lang),
                    value=chamber.enemy_level,
                    inline=False,
                )
                embed.set_image(url="attachment://enemies.png")
                embeds[f"{floor.num}-{chamber.num}"] = embed
                enemies[f"{floor.num}-{chamber.num}"] = chamber.halfs

        embed = models.DefaultEmbed()
        embed.set_image(url=asset.abyss_image)
        embed.set_author(
            name=f"{text_map.get(705, lang)}",
            icon_url=i.user.display_avatar.url,
        )

        buff_name, buff_desc = await abyss.get_abyss_blessing(
            self.bot.gd_text_map, lang
        )
        buff_embed = models.DefaultEmbed(text_map.get(733, lang))
        buff_embed.add_field(
            name=buff_name,
            value=buff_desc,
        )

        view = ui.abyss_enemy.View(lang, enemies, embeds, buff_embed)
        view.author = i.user
        await i.followup.send(embed=embed, view=view)
        view.message = await i.original_response()

    @app_commands.command(
        name="lineup",
        description=_(
            "Search Genshin lineups with Hoyolab's lineup simulator", hash=38
        ),
    )
    async def slash_lineup(self, inter: discord.Interaction):
        i: models.Inter = inter  # type: ignore
        lang = await i.client.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)

        user = await i.client.db.users.get(i.user.id)
        if user.game is not GameType.GENSHIN:
            raise exceptions.GameNotSupported(user.game, [GameType.GENSHIN])

        client = await user.client
        scenarios = await client.get_lineup_scenarios()

        scenarios_to_search = [
            scenarios.abyss.spire,
            scenarios.abyss.corridor,
            scenarios.world.battles,
            scenarios.world.domain_challenges,
            scenarios.world.trounce_domains,
        ]
        options = []
        scenario_dict = {}
        for scenario in scenarios_to_search:
            options.append(
                discord.SelectOption(label=scenario.name, value=str(scenario.id))
            )
            scenario_dict[str(scenario.id)] = scenario

        ambr = AmbrTopAPI(self.bot.session, convert_locale.to_ambr_top(lang))
        characters = await ambr.get_character(include_beta=False)

        if isinstance(characters, List):
            view = ui.lineup_view.View(lang, options, scenario_dict, characters)
            view.author = i.user
            await ui.lineup_view.search_lineup(i, view)
            view.message = await i.original_response()

    @app_commands.command(
        name="tcg", description=_("Search a card in the Genshin TCG", hash=717)
    )
    @app_commands.rename(card_id=_("card", hash=718))
    async def slash_tcg(self, inter: discord.Interaction, card_id: str):
        if not card_id.isdigit():
            raise exceptions.AutocompleteError

        i: models.Inter = inter  # type: ignore
        lang = await i.client.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)
        genshin_db_locale = convert_locale.GENSHIN_DB_LANGS.get(lang, "English")

        the_card = None
        card_type = None

        for card in self.card_data[genshin_db_locale]:
            if card["id"] == int(card_id):
                the_card = card
                card_type = card["cardType"]
                break

        if the_card is None:
            raise exceptions.CardNotFound

        card = the_card

        if card_type == "tcgcharactercards":
            embed = models.DefaultEmbed(card["name"])
            embed.set_author(name=card["storytitle"])
            embed.set_footer(text=card["source"])
            embed.set_image(
                url=f"https://res.cloudinary.com/genshin/image/upload/sprites/{card['images']['filename_cardface_HD']}.png"
            )

            for skill in card["skills"]:
                cost_str = f"**{text_map.get(710, lang)}: **"
                cost_str += " / ".join(
                    [
                        f"{get_dice_emoji(cost['costtype'])} ({cost['count']})"
                        for cost in skill["playcost"]
                    ]
                )
                embed.add_field(
                    name=skill["name"],
                    value=general.parse_html(skill["description"]) + "\n" + cost_str,
                    inline=False,
                )
        elif card_type == "tcgactioncards":
            embed = models.DefaultEmbed(
                card["name"],
                card["description"],
            )
            embed.set_author(name=card["cardtypetext"])
            if "storytext" in card:
                embed.set_footer(text=card["storytext"])
            embed.set_image(
                url=f"https://res.cloudinary.com/genshin/image/upload/sprites/{card['images']['filename_cardface_HD']}.png"
            )

            if card["playcost"]:
                cost_str = " / ".join(
                    [
                        f"{get_dice_emoji(cost['costtype'])} ({cost['count']})"
                        for cost in card["playcost"]
                    ]
                )
                embed.add_field(name=text_map.get(710, lang), value=cost_str)
        elif card_type == "tcgcardbacks":
            embed = models.DefaultEmbed(card["name"], card["description"])
            embed.set_footer(text=card["source"])
            embed.set_image(
                url=f"https://res.cloudinary.com/genshin/image/upload/sprites/{card['images']['filename_icon_HD']}.png"
            )
        elif card_type == "tcgcardboxes":
            embed = models.DefaultEmbed(card["name"], card["description"])
            embed.set_footer(text=card["source"])
            embed.set_image(
                url=f"https://res.cloudinary.com/genshin/image/upload/sprites/{card['images']['filename_bg']}.png"
            )
        elif card_type == "tcgstatuseffects":
            embed = models.DefaultEmbed(card["name"], card["description"])
            embed.set_author(name=card["statustypetext"])
        else:  # card_type == "tcgsummons"
            embed = models.DefaultEmbed(card["name"], card["description"])
            embed.set_author(name=card["cardtypetext"])
            embed.set_image(
                url=f"https://res.cloudinary.com/genshin/image/upload/sprites/{card['images']['filename_cardface_HD']}.png"
            )

        await i.response.send_message(embed=embed)

    @slash_tcg.autocomplete("card_id")
    async def card_autocomplete(
        self, inter: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        i: models.Inter = inter  # type: ignore
        lang = await i.client.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)
        genshin_db_locale = convert_locale.GENSHIN_DB_LANGS.get(lang, "English")

        choices: List[app_commands.Choice] = []

        cards = self.card_data[genshin_db_locale]
        for card in cards:
            if current.lower() in card["name"].lower():
                choices.append(
                    app_commands.Choice(name=card["name"], value=str(card["id"]))
                )

        if not current:
            choices = random.choices(choices, k=25)

        return choices[:25]


async def setup(bot: commands.AutoShardedBot) -> None:
    await bot.add_cog(GenshinCog(bot))
