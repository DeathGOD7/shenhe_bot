import json
from typing import Any, Dict, List

import aiofiles
import discord
from dateutil import parser
from discord import ui
from discord.utils import format_dt

import dev.asset as asset
import dev.config as config
from apps.db.tables.user_settings import Settings
from apps.hoyolab_rss_feeds.create_feed import create_feed
from apps.text_map import text_map, to_genshin_py
from dev.base_ui import BaseView
from dev.models import DefaultEmbed, Inter
from utils import parse_html
from utils.paginators import GeneralPaginator, GeneralPaginatorView


class View(BaseView):
    def __init__(self, lang: discord.Locale | str):
        super().__init__(timeout=config.short_timeout)
        self.lang = lang
        self.add_item(Hoyolab())
        self.add_item(Genshin(lang))


class Hoyolab(ui.Button):
    def __init__(self):
        super().__init__(label="HoYoLAB", emoji=asset.hoyolab_emoji)
        self.view: View

    async def callback(self, i: Inter):
        await i.response.defer()

        lang = await i.client.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)
        genshin_locale = to_genshin_py(lang)

        await create_feed(genshin_locale)

        async with aiofiles.open(
            f"apps/hoyolab_rss_feeds/feeds/{genshin_locale}.json"
        ) as f:
            events = json.loads(await f.read())

        select_options = []
        tags = []
        embeds = {}
        events = events["items"]
        for event in events:
            date_published = parser.parse(event["date_published"])
            embed = DefaultEmbed(event["title"])
            embed.add_field(
                name=text_map.get(625, lang),
                value=format_dt(date_published, "R"),  # type: ignore
                inline=False,
            )
            embed.add_field(
                name=text_map.get(408, lang),
                value=f"{parse_html(event['content_html'])[:200]}...\n\n[{text_map.get(454, lang)}]({event['url']})",
                inline=False,
            )
            if "image" in event:
                embed.set_image(url=event["image"])
            for tag in event["tags"]:
                if tag not in tags:
                    tags.append(tag)
                if tag not in embeds:
                    embeds[tag] = []
                embeds[tag].append(embed)
            embed.set_author(
                name="Hoyolab",
                icon_url="https://play-lh.googleusercontent.com/5_vh9y9wp8s8Agr7_bjTIz5syyp_jYxGgbTCcPDj3VaA-nilI6Fd75xsBqHHXUxMyB8",
            )

        for tag in tags:
            select_options.append(discord.SelectOption(label=tag, value=tag))
        await GeneralPaginator(
            i,
            embeds[list(embeds.keys())[0]],
            [
                EventTypeSelect(select_options, embeds, self.view.lang),
                GOBack(self.view.lang),
            ],
        ).start(edit=True)


class Genshin(ui.Button):
    def __init__(self, lang: discord.Locale | str):
        super().__init__(
            label=text_map.get(313, lang), emoji="<:genshin_icon:1025630733068423169>"
        )
        self.view: View

    async def callback(self, i: Inter):
        await i.response.defer()
        genshin_py_locale = to_genshin_py(self.view.lang)
        event_overview_api = f"https://sg-hk4e-api.hoyoverse.com/common/hk4e_global/announcement/api/getAnnList?game=hk4e&game_biz=hk4e_global&lang={genshin_py_locale}&announcement_version=1.21&auth_appid=announcement&bundle_id=hk4e_global&channel_id=1&level=8&platform=pc&region=os_asia&sdk_presentation_style=fullscreen&sdk_screen_transparent=true&uid=901211014"
        event_details_api = f"https://sg-hk4e-api-static.hoyoverse.com/common/hk4e_global/announcement/api/getAnnContent?game=hk4e&game_biz=hk4e_global&lang={genshin_py_locale}&bundle_id=hk4e_global&platform=pc&region=os_asia&t=1659877813&level=7&channel_id=0"
        async with i.client.session.get(event_overview_api) as r:
            overview: Dict[str, Any] = await r.json()
        async with i.client.session.get(event_details_api) as r:
            details: Dict[str, Any] = await r.json()
        type_list = overview["data"]["type_list"]
        options = []
        for type_ in type_list:
            options.append(
                discord.SelectOption(label=type_["mi18n_name"], value=type_["id"])
            )
        # get a dict of details
        detail_dict = {}
        for event in details["data"]["list"]:
            detail_dict[event["ann_id"]] = event["content"]
        first_id = None
        embeds = {}
        for event in overview["data"]["list"]:
            event_list = event["list"]
            if event_list[0]["type"] not in embeds:
                embeds[str(event_list[0]["type"])] = []
            if first_id is None:
                first_id = str(event_list[0]["type"])
            for e in event_list:
                embed = DefaultEmbed(e["title"])
                embed.set_author(name=e["type_label"], icon_url=e["tag_icon"])
                embed.set_image(url=e["banner"])
                embed.add_field(
                    name=text_map.get(406, self.view.lang),
                    value=format_dt(parser.parse(e["start_time"]), "R"),  # type: ignore
                )
                embed.add_field(
                    name=text_map.get(407, self.view.lang),
                    value=format_dt(parser.parse(e["end_time"]), "R"),  # type: ignore
                )
                embed.add_field(
                    name=text_map.get(408, self.view.lang),
                    value=parse_html(detail_dict[e["ann_id"]])[:500] + "...",
                    inline=False,
                )
                embeds[str(e["type"])].append(embed)
        await GeneralPaginator(
            i,
            embeds[first_id],
            [
                EventTypeSelect(options, embeds, self.view.lang),
                GOBack(self.view.lang),
            ],
        ).start(edit=True)


class EventTypeSelect(ui.Select):
    def __init__(
        self,
        options: List[discord.SelectOption],
        embeds: Dict[str, List[discord.Embed]],
        lang: discord.Locale | str,
    ) -> None:
        super().__init__(options=options, placeholder=text_map.get(409, lang))
        self.embeds = embeds
        self.view: GeneralPaginatorView

    async def callback(self, i: Inter) -> Any:
        self.view.current_page = 0
        self.view.embeds = self.embeds[self.values[0]]
        await self.view.update_children(i)


class GOBack(ui.Button):
    def __init__(self, lang: discord.Locale | str):
        super().__init__(
            label=text_map.get(282, lang), style=discord.ButtonStyle.green, row=3
        )

    async def callback(self, i: Inter):
        await return_events(i)


async def return_events(i: Inter):
    await i.response.defer()
    lang = await i.client.db.settings.get(i.user.id, Settings.LANG) or str(i.locale)
    view = View(lang)
    embed = DefaultEmbed().set_author(
        name=text_map.get(361, lang),
        icon_url=i.user.display_avatar.url,
    )
    await i.edit_original_response(embed=embed, view=view)
    view.message = await i.original_response()
