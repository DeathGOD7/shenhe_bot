from typing import Dict, List, Literal, Optional, Tuple
import aiosqlite
import genshin
import sentry_sdk
from discord import Embed, Locale, SelectOption, User, Asset
from discord.utils import format_dt
import enkanetwork
from ambr.client import AmbrTopAPI
from apps.genshin.custom_model import ShenheBot, ShenheUser
from apps.genshin.utils import get_shenhe_user, get_uid
from apps.text_map.text_map_app import text_map
from apps.text_map.utils import get_element_name, get_month_name, get_user_locale
from data.game.elements import element_emojis
from utility.utils import default_embed, error_embed, get_user_appearance_mode, log
from yelan.draw import (
    draw_abyss_overview_card,
    draw_area_card,
    draw_big_character_card,
    draw_diary_card,
    draw_realtime_notes_card,
    draw_stats_card,
)


class CookieInvalid(Exception):
    pass


class UIDNotFound(Exception):
    pass


def genshin_error_handler(func):
    async def inner_function(*args, **kwargs):
        genshin_app: GenshinApp = args[0]
        user_id = args[1]
        author_id = args[2]
        locale = args[-1]
        user = genshin_app.bot.get_user(user_id) or await genshin_app.bot.fetch_user(
            user_id
        )
        uid = await get_uid(user_id, genshin_app.bot.db)
        author_locale = await get_user_locale(author_id, genshin_app.bot.db)
        locale = author_locale or locale
        try:
            return await func(*args, **kwargs)
        except genshin.errors.DataNotPublic:
            embed = error_embed(message=f"{text_map.get(21, locale)}\nUID: {uid}")
            embed.set_author(
                name=text_map.get(22, locale),
                icon_url=user.display_avatar.url,
            )
            return embed, False
        except genshin.errors.InvalidCookies:
            embed = error_embed(message=f"{text_map.get(35, locale)}\nUID: {uid}")
            embed.set_author(
                name=text_map.get(36, locale),
                icon_url=user.display_avatar.url,
            )
            return embed, False
        except genshin.errors.GenshinException as e:
            log.warning(
                f"[Genshin App][GenshinException] in {func.__name__}: [e]{e} [code]{e.retcode} [msg]{e.msg}"
            )
            if e.retcode == -400005:
                embed = error_embed().set_author(name=text_map.get(14, locale))
                return embed, False
            else:
                sentry_sdk.capture_exception(e)
                embed = error_embed(message=f"```{e}```")
                embed.set_author(
                    name=text_map.get(10, locale),
                    icon_url=user.display_avatar.url,
                )
                return embed, False
        except Exception as e:
            log.warning(f"[Genshin App] Error in {func.__name__}: {e}")
            sentry_sdk.capture_exception(e)
            embed = error_embed(message=text_map.get(513, locale, author_locale))
            if embed.description is not None:
                embed.description += f"\n\n```{e}```"
            embed.set_author(
                name=text_map.get(135, locale), icon_url=user.display_avatar.url
            )
            embed.set_thumbnail(url="https://i.imgur.com/Xi51hSe.gif")
            return embed, False

    return inner_function


class GenshinApp:
    def __init__(self, db: aiosqlite.Connection, bot) -> None:
        self.db = db
        self.bot: ShenheBot = bot

    @genshin_error_handler
    async def claim_daily_reward(self, user_id: int, author_id: int, locale: Locale):
        shenhe_user = await self.get_user_cookie(user_id, author_id, locale)
        try:
            reward = await shenhe_user.client.claim_daily_reward()
        except genshin.errors.AlreadyClaimed:
            return (
                error_embed().set_author(
                    name=text_map.get(40, locale, shenhe_user.user_locale),
                    icon_url=shenhe_user.discord_user.display_avatar.url,
                ),
                False,
            )
        else:
            return (
                default_embed(
                    message=f"{text_map.get(41, locale, shenhe_user.user_locale)} {reward.amount}x {reward.name}"
                ).set_author(
                    name=text_map.get(42, locale, shenhe_user.user_locale),
                    icon_url=shenhe_user.discord_user.display_avatar.url,
                ),
                True,
            )

    @genshin_error_handler
    async def get_real_time_notes(self, user_id: int, author_id: int, locale: Locale):
        shenhe_user = await self.get_user_cookie(user_id, author_id, locale)
        notes = await shenhe_user.client.get_genshin_notes(shenhe_user.uid)
        fp = await draw_realtime_notes_card(
            notes,
            shenhe_user.user_locale or str(locale),
            self.bot.session,
            await get_user_appearance_mode(author_id, self.db),
        )
        embed = await self.parse_resin_embed(notes, locale, shenhe_user.user_locale)
        return ({"embed": embed, "file": fp}, True)

    async def parse_resin_embed(
        self,
        notes: genshin.models.Notes,
        locale: Locale,
        user_locale: Optional[str] = None,
    ) -> Embed:
        if notes.current_resin == notes.max_resin:
            resin_recover_time = text_map.get(1, locale, user_locale)
        else:
            resin_recover_time = format_dt(notes.resin_recovery_time, "R")

        if notes.current_realm_currency == notes.max_realm_currency:
            realm_recover_time = text_map.get(1, locale, user_locale)
        else:
            realm_recover_time = format_dt(notes.realm_currency_recovery_time, "R")
        if (
            notes.remaining_transformer_recovery_time is None
            or notes.transformer_recovery_time is None
        ):
            transformer_recover_time = text_map.get(11, locale, user_locale)
        else:
            if notes.remaining_transformer_recovery_time.total_seconds() <= 0:
                transformer_recover_time = text_map.get(9, locale, user_locale)
            else:
                transformer_recover_time = format_dt(
                    notes.transformer_recovery_time, "R"
                )
        result = default_embed(
            message=f"<:resin:1004648472995168326> {text_map.get(15, locale, user_locale)}: {resin_recover_time}\n"
            f"<:realm:1004648474266062880> {text_map.get(15, locale, user_locale)}: {realm_recover_time}\n"
            f"<:transformer:1004648470981902427> {text_map.get(8, locale, user_locale)}: {transformer_recover_time}"
        )
        result.set_image(url="attachment://realtime_notes.jpeg")
        return result

    @genshin_error_handler
    async def get_stats(
        self,
        user_id: int,
        author_id: int,
        namecard: enkanetwork.model.assets.IconAsset,
        avatar_url: Asset,
        locale: Locale,
    ) -> Tuple[Embed | Dict, bool]:
        shenhe_user = await self.get_user_cookie(user_id, author_id, locale)
        uid = shenhe_user.uid
        if uid is None:
            raise UIDNotFound
        embed = default_embed()
        embed.set_image(url="attachment://stat_card.jpeg")
        fp = self.bot.stats_card_cache.get(uid)
        if fp is None:
            genshin_user = await shenhe_user.client.get_partial_genshin_user(uid)
            ambr = AmbrTopAPI(self.bot.session)
            characters = await ambr.get_character(
                include_beta=False, include_traveler=False
            )
            if not isinstance(characters, List):
                raise TypeError("Characters is not a list")

            mode = await get_user_appearance_mode(author_id, self.db)
            fp = await draw_stats_card(
                genshin_user.stats,
                namecard,
                avatar_url,
                len(characters) + 2,
                mode,
                self.bot.session,
            )
            self.bot.stats_card_cache[uid] = fp
        return {"embed": embed, "fp": fp}, True

    @genshin_error_handler
    async def get_area(self, user_id: int, author_id: int, locale: Locale):
        shenhe_user = await self.get_user_cookie(user_id, author_id, locale)
        uid = shenhe_user.uid
        if uid is None:
            raise UIDNotFound
        embed = default_embed()
        embed.set_author(
            name=text_map.get(58, locale, shenhe_user.user_locale),
            icon_url=shenhe_user.discord_user.display_avatar.url,
        )
        embed.set_image(url="attachment://area.jpeg")
        genshin_user = await shenhe_user.client.get_partial_genshin_user(uid)
        explorations = genshin_user.explorations
        fp = self.bot.area_card_cache.get(uid)
        if fp is None:
            mode = await get_user_appearance_mode(author_id, self.db)
            fp = await draw_area_card(explorations, mode)
        result = {
            "embed": embed,
            "image": fp,
        }
        return (
            result,
            True,
        )

    @genshin_error_handler
    async def get_diary(self, user_id: int, author_id: int, month: int, locale: Locale):
        shenhe_user = await self.get_user_cookie(user_id, author_id, locale)
        if shenhe_user.china:
            shenhe_user.client.region = genshin.Region.CHINESE
        diary = await shenhe_user.client.get_diary(month=month)
        if shenhe_user.uid is None:
            raise UIDNotFound
        user = await shenhe_user.client.get_partial_genshin_user(shenhe_user.uid)
        result = {}
        embed = default_embed()
        fp = await draw_diary_card(
            diary,
            user,
            shenhe_user.user_locale or locale,
            month,
            await get_user_appearance_mode(author_id, self.db),
        )
        fp.seek(0)
        embed.set_image(url="attachment://diary.jpeg")
        embed.set_author(
            name=f"{text_map.get(69, locale, shenhe_user.user_locale)} • {get_month_name(month, locale, shenhe_user.user_locale)}",
            icon_url=shenhe_user.discord_user.display_avatar.url,
        )
        result["embed"] = embed
        result["fp"] = fp
        return result, True

    @genshin_error_handler
    async def get_diary_logs(
        self, user_id: int, author_id: int, primo: bool, locale: Locale
    ):
        shenhe_user = await self.get_user_cookie(user_id, author_id, locale)
        if shenhe_user.china:
            shenhe_user.client.region = genshin.Region.CHINESE
        if primo:
            primo_log = ""
            async for action in shenhe_user.client.diary_log(limit=30):
                primo_log = (
                    primo_log
                    + f"{format_dt(action.time, 'd')} {action.action} - {action.amount} {text_map.get(71, locale, shenhe_user.user_locale)}"
                    + "\n"
                )
            embed = default_embed(message=f"{primo_log}")
            embed.set_author(
                name=text_map.get(70, locale, shenhe_user.user_locale),
                icon_url=shenhe_user.discord_user.display_avatar.url,
            )
        else:
            mora_log = ""
            async for action in shenhe_user.client.diary_log(
                limit=30, type=genshin.models.DiaryType.MORA
            ):
                mora_log = (
                    mora_log
                    + f"{format_dt(action.time, 'd')} {action.action} - {action.amount} {text_map.get(73, locale, shenhe_user.user_locale)}"
                    + "\n"
                )
            embed = default_embed(message=f"{mora_log}")
            embed.set_author(
                name=text_map.get(72, locale, shenhe_user.user_locale),
                icon_url=shenhe_user.discord_user.display_avatar.url,
            )
        return embed, True

    @genshin_error_handler
    async def get_abyss(
        self, user_id: int, author_id: int, previous: bool, locale: Locale
    ):
        shenhe_user = await self.get_user_cookie(user_id, author_id, locale)
        if shenhe_user.uid is None:
            raise UIDNotFound
        user = await shenhe_user.client.get_partial_genshin_user(shenhe_user.uid)
        abyss = await shenhe_user.client.get_genshin_spiral_abyss(
            shenhe_user.uid, previous=previous
        )
        author_locale = await get_user_locale(author_id, self.db)
        new_locale = author_locale or shenhe_user.user_locale or locale
        if not abyss.ranks.most_kills:
            embed = error_embed(message=text_map.get(74, new_locale))
            embed.set_author(
                name=text_map.get(76, new_locale),
                icon_url=shenhe_user.discord_user.display_avatar.url,
            )
            return embed, False
        result = {}
        result["abyss"] = abyss
        result["user"] = user
        overview = default_embed()
        overview.set_image(url="attachment://overview_card.jpeg")
        overview.set_author(
            name=f"{text_map.get(85, new_locale)} | {text_map.get(77, new_locale)} {abyss.season}",
            icon_url=shenhe_user.discord_user.display_avatar.url,
        )
        result[
            "title"
        ] = f"{text_map.get(47, new_locale)} | {text_map.get(77, new_locale)} {abyss.season}"
        result["overview"] = overview
        dark_mode = await get_user_appearance_mode(author_id, self.db)
        cache = self.bot.abyss_overview_card_cache
        fp = cache.get(shenhe_user.uid)
        if fp is None:
            fp = await draw_abyss_overview_card(
                new_locale, dark_mode, abyss, user, self.bot.session, self.bot.loop
            )
            cache[shenhe_user.uid] = fp
        result["overview_card"] = fp
        result["floors"] = [floor for floor in abyss.floors if floor.floor >= 9]
        return result, True

    @genshin_error_handler
    async def get_all_characters(
        self, user_id: int, author_id: int, locale: Locale
    ) -> Tuple[Dict | Embed, bool]:
        shenhe_user = await self.get_user_cookie(user_id, author_id, locale)
        if shenhe_user.uid is None:
            raise UIDNotFound
        characters = await shenhe_user.client.get_genshin_characters(shenhe_user.uid)
        author_locale = await get_user_locale(author_id, self.db)
        new_locale = author_locale or shenhe_user.user_locale or str(locale)
        # organize characters according to elements
        result = {
            "embed": default_embed().set_image(url="attachment://characters.jpeg"),
            "options": [SelectOption(label=text_map.get(701, new_locale), value="All")],
        }
        elements = []
        for character in characters:
            if character.element not in elements:
                elements.append(character.element)

        for element in elements:
            result["options"].append(
                SelectOption(
                    emoji=element_emojis.get(element),
                    label=(
                        text_map.get(19, new_locale)
                        if element == "All"
                        else text_map.get(52, new_locale).format(
                            element=get_element_name(element, new_locale)
                        )
                    ),
                    value=element,
                )
            )
        fp = await draw_big_character_card(
            list(characters),
            self.bot.session,
            await get_user_appearance_mode(author_id, self.db),
            new_locale,
            "All",
        )
        result["file"] = fp
        result["characters"] = characters

        return result, True

    @genshin_error_handler
    async def redeem_code(
        self, user_id: int, author_id: int, code: str, locale: Locale
    ):
        shenhe_user = await self.get_user_cookie(user_id, author_id, locale)
        try:
            await shenhe_user.client.redeem_code(code)
        except genshin.errors.RedemptionClaimed:
            return (
                error_embed().set_author(
                    name=text_map.get(106, locale, shenhe_user.user_locale),
                    icon_url=shenhe_user.discord_user.display_avatar.url,
                ),
                False,
            )
        except genshin.errors.RedemptionInvalid:
            return (
                error_embed().set_author(
                    name=text_map.get(107, locale, shenhe_user.user_locale),
                    icon_url=shenhe_user.discord_user.display_avatar.url,
                ),
                False,
            )
        else:
            return (
                default_embed(
                    message=f"{text_map.get(108, locale, shenhe_user.user_locale)}: {code}"
                ).set_author(
                    name=text_map.get(109, locale, shenhe_user.user_locale),
                    icon_url=shenhe_user.discord_user.display_avatar.url,
                ),
                True,
            )

    @genshin_error_handler
    async def get_activities(self, user_id: int, author_id: int, locale: Locale):
        shenhe_user = await self.get_user_cookie(user_id, author_id, locale)
        uid = shenhe_user.uid
        if uid is None:
            raise UIDNotFound
        activities = await shenhe_user.client.get_genshin_activities(uid)
        summer = activities.summertime_odyssey
        if summer is None:
            return (
                error_embed().set_author(
                    name=text_map.get(110, locale, shenhe_user.user_locale),
                    icon_url=shenhe_user.discord_user.display_avatar.url,
                ),
                False,
            )
        result = await self.parse_summer_embed(
            summer,
            shenhe_user.discord_user,
            locale,
            shenhe_user.user_locale,
        )
        return result, True

    async def parse_summer_embed(
        self,
        summer: genshin.models.Summer,
        user: User,
        locale: Locale,
        user_locale: Literal["str", None],
    ) -> list[Embed]:
        embeds = []
        embed = default_embed().set_author(
            name=text_map.get(111, locale, user_locale),
            icon_url=user.display_avatar.url,
        )
        embed.add_field(
            name=f"<:SCORE:983948729293897779> {text_map.get(43, locale, user_locale)}",
            value=f"{text_map.get(112, locale, user_locale)}: {summer.waverider_waypoints}/13\n"
            f"{text_map.get(113, locale, user_locale)}: {summer.waypoints}/10\n"
            f"{text_map.get(114, locale, user_locale)}: {summer.treasure_chests}",
        )
        embed.set_image(url="https://i.imgur.com/Zk1tqxA.png")
        embeds.append(embed)
        embed = default_embed().set_author(
            name=text_map.get(111, locale, user_locale),
            icon_url=user.display_avatar.url,
        )
        surfs = summer.surfpiercer
        value = ""
        for surf in surfs:
            if surf.finished:
                minutes, seconds = divmod(surf.time, 60)
                time_str = (
                    f"{minutes} {text_map.get(7, locale, user_locale)} {seconds} {text_map.get(8, locale, user_locale)}"
                    if minutes != 0
                    else f"{seconds}{text_map.get(12, locale, user_locale)}"
                )
                value += f"{surf.id}. {time_str}\n"
            else:
                value += f"{surf.id}. *{text_map.get(115, locale, user_locale)}* \n"
        embed.add_field(name=text_map.get(116, locale, user_locale), value=value)
        embed.set_thumbnail(url="https://i.imgur.com/Qt4Tez0.png")
        embeds.append(embed)
        memories = summer.memories
        for memory in memories:
            embed = default_embed().set_author(
                name=text_map.get(117, locale, user_locale),
                icon_url=user.display_avatar.url,
            )
            embed.set_thumbnail(url="https://i.imgur.com/yAbpUF8.png")
            embed.set_image(url=memory.icon)
            embed.add_field(
                name=memory.name,
                value=f"{text_map.get(119, locale, user_locale)}: {memory.finish_time}",
            )
            embeds.append(embed)
        realms = summer.realm_exploration
        for realm in realms:
            embed = default_embed().set_author(
                name=text_map.get(118, locale, user_locale),
                icon_url=user.display_avatar.url,
            )
            embed.set_thumbnail(url="https://i.imgur.com/0jyBciz.png")
            embed.set_image(url=realm.icon)
            embed.add_field(
                name=realm.name,
                value=f"{text_map.get(119, locale, user_locale)}: {realm.finish_time if realm.finished else text_map.get(115, locale, user_locale)}\n"
                f"{text_map.get(120, locale, user_locale)} {realm.success} {text_map.get(121, locale, user_locale)}\n"
                f"{text_map.get(122, locale, user_locale)} {realm.skills_used} {text_map.get(121, locale, user_locale)}",
            )
            embeds.append(embed)
        return embeds

    async def get_user_uid(self, user_id: int) -> int | None:
        uid = await get_uid(user_id, self.db)
        return uid

    async def get_user_cookie(
        self, user_id: int, author_id: int, locale: Optional[Locale] = None
    ) -> ShenheUser:
        author_locale = await get_user_locale(author_id, self.db)
        shenhe_user = await get_shenhe_user(
            user_id, self.db, self.bot, locale, author_locale=author_locale
        )
        return shenhe_user
