from typing import Dict, List, Optional
from ambr.client import AmbrTopAPI
from apps.text_map.convert_locale import to_ambr_top, to_genshin_py
from utility.utils import default_embed
import asset
import yaml
from discord import Embed, Interaction, SelectOption
from discord.ui import Button, Select
import genshin
import config
from apps.genshin.utils import (
    get_character_builds,
    get_character_emoji,
    get_character_icon,
)
from apps.text_map.cond_text import cond_text
from apps.text_map.text_map_app import text_map
from apps.text_map.utils import get_user_locale
from data.game.elements import get_element_emoji, get_element_list
from UI_base_models import BaseView


class View(BaseView):
    def __init__(self):
        super().__init__(timeout=config.long_timeout)

        elements = get_element_list()
        for index, element in enumerate(elements):
            self.add_item(
                ElementButton(element, get_element_emoji(element), index // 4)
            )


class ElementButton(Button):
    def __init__(self, element: str, element_emoji: str, row: int):
        super().__init__(emoji=element_emoji, row=row)
        self.element = element

    async def callback(self, i: Interaction):
        self.view: View
        await element_button_callback(i, self.element, self.view)


class CharacterSelect(Select):
    def __init__(
        self, options: List[SelectOption], placeholder: str, builds: Dict, element: str
    ):
        super().__init__(options=options, placeholder=placeholder)
        self.builds = builds
        self.element = element

    async def callback(self, i: Interaction):
        self.view: View
        locale = await get_user_locale(i.user.id, i.client.db) or i.locale
        builds = get_character_builds(self.values[0], self.builds, locale)
        embeds = []
        options = []
        has_thought = False
        for index, build in enumerate(builds):
            if build.is_thought:
                has_thought = True
                continue
            embeds.append(build.embed)
            if build.weapon is not None and build.artifact is not None:
                weapon_id = text_map.get_id_from_name(build.weapon)
                if weapon_id is None:
                    raise ValueError(f"Could not find weapon {build.weapon}")
                options.append(
                    SelectOption(
                        label=f"{text_map.get(162, locale)} {index+1}",
                        description=f"{text_map.get_weapon_name(weapon_id, locale)} | {cond_text.get_text(str(locale), 'build', build.artifact)}",
                        value=str(index),
                    )
                )
        placeholder = text_map.get(163, locale)
        self.view.clear_items()
        self.view.add_item(BuildSelect(options, placeholder, embeds))
        if has_thought:
            self.view.add_item(ArtifactThoughtButton(builds[-1].embed))
        self.view.add_item(TeamButton(asset.team_emoji, int(self.values[0])))
        self.view.add_item(GoBack("character", self.element))
        await i.response.edit_message(embed=embeds[0], view=self.view)


class BuildSelect(Select):
    def __init__(
        self, options: List[SelectOption], placeholder: str, build_embeds: List[Embed]
    ):
        super().__init__(options=options, placeholder=placeholder)
        self.build_embeds = build_embeds

    async def callback(self, i: Interaction):
        await i.response.edit_message(embed=self.build_embeds[int(self.values[0])])


class ArtifactThoughtButton(Button):
    def __init__(self, thought_embed: Embed):
        super().__init__(emoji="🤔")
        self.embed = thought_embed

    async def callback(self, i: Interaction):
        await i.response.edit_message(embed=self.embed)


class TeamButton(Button):
    def __init__(self, emoji: str, character_id: int):
        super().__init__(emoji=emoji)
        self.character_id = character_id

    async def callback(self, i: Interaction):
        await i.response.defer()
        locale = await get_user_locale(i.user.id, i.client.db) or i.locale
        client: genshin.Client = i.client.genshin_client
        client.lang = to_genshin_py(locale)
        scenarios = await client.get_lineup_scenarios()

        embed = default_embed()
        embed.set_author(
            name=text_map.get(153, locale).format(
                character_name=text_map.get_character_name(
                    str(self.character_id), locale
                )
            ),
            icon_url=get_character_icon(str(self.character_id)),
        )

        scs = [scenarios.abyss.spire, scenarios.world]

        for sc in scs:
            lineups = client.get_lineups(
                lang=to_genshin_py(locale),
                characters=[self.character_id],
                limit=1,
                scenario=sc,
            )
            lineup = [l async for l in lineups][0]
            l_detail = await client.get_lineup_details(lineup)

            val = ""
            for _ in l_detail.characters:
                for character in _:
                    val += f"{get_character_emoji(str(character.id))} **{character.name}** - {character.role}\n"
                val += "\n"
            embed.add_field(name=sc.name, value=val, inline=False)

        await i.edit_original_response(embed=embed)


class GoBack(Button):
    def __init__(self, place_to_go_back: str, element: Optional[str] = None):
        super().__init__(emoji="<:left:982588994778972171>", row=4)
        self.place_to_go_back = place_to_go_back
        self.element = element

    async def callback(self, i: Interaction):
        self.view: View
        self.view.clear_items()
        if self.place_to_go_back == "element":
            elements = get_element_list()
            for index, element in enumerate(elements):
                self.view.add_item(
                    ElementButton(element, get_element_emoji(element), index // 4)
                )
            await i.response.edit_message(view=self.view)
        elif self.place_to_go_back == "character" and self.element is not None:
            await element_button_callback(i, self.element, self.view)


async def element_button_callback(i: Interaction, element: str, view: View):
    with open(f"data/builds/{element.lower()}.yaml", "r", encoding="utf-8") as f:
        builds = yaml.full_load(f)
    user_locale = await get_user_locale(i.user.id, i.client.db)
    options = []
    placeholder = text_map.get(157, i.locale, user_locale)
    user_locale = await get_user_locale(i.user.id, i.client.db)
    for character_name, character_builds in builds.items():
        character_id = text_map.get_id_from_name(character_name)
        localized_character_name = text_map.get_character_name(
            str(character_id), user_locale or i.locale
        )
        if localized_character_name is None:
            continue
        options.append(
            SelectOption(
                label=localized_character_name,
                emoji=get_character_emoji(str(character_id)),
                value=str(character_id),
                description=f'{len(character_builds["builds"])} {text_map.get(164, i.locale, user_locale)}',
            )
        )
    view.clear_items()
    view.add_item(CharacterSelect(options, placeholder, builds, element))
    view.add_item(GoBack("element"))
    await i.response.edit_message(embed=None, view=view)
    view.message = await i.original_response()
