from typing import List, Union

import discord
from discord import ui

import apps.db.custom_image as image
import dev.asset as asset
import dev.config as config
from ambr import AmbrTopAPI
from apps.text_map import text_map, to_ambr_top
from data.game.elements import get_element_emoji, get_element_list
from dev.base_ui import BaseModal, BaseView, EnkaView
from dev.models import DefaultEmbed, ErrorEmbed, Inter
from ui.genshin import enka_damage_calc
from utils import divide_chunks, get_character_emoji


class View(BaseView):
    def __init__(self, lang: discord.Locale | str):
        super().__init__(timeout=config.mid_timeout)

        elements = get_element_list()
        for index, element in enumerate(elements):
            self.add_item(
                ElementButton(get_element_emoji(element), element, index // 4)
            )
        self.lang = lang

    def gen_embed(self) -> discord.Embed:
        embed = DefaultEmbed(text_map.get(62, self.lang), text_map.get(276, self.lang))
        return embed


class ElementButton(ui.Button):
    def __init__(self, emoji: str, element: str, row: int):
        super().__init__(emoji=emoji, row=row)
        self.element = element
        self.view: View

    async def callback(self, i: Inter):
        await element_button_callback(i, self.view, self.element)


class GoBack(ui.Button):
    def __init__(self):
        super().__init__(emoji=asset.back_emoji)
        self.view: View

    async def callback(self, i: Inter):
        self.view.clear_items()
        elements = get_element_list()
        for index, element in enumerate(elements):
            self.view.add_item(
                ElementButton(get_element_emoji(element), element, index // 4)
            )
        await i.response.edit_message(view=self.view)


class GoBackCharacter(ui.Button):
    def __init__(self, element: str):
        super().__init__(emoji=asset.back_emoji)
        self.element = element
        self.view: View

    async def callback(self, i: Inter):
        await element_button_callback(i, self.view, self.element)


async def element_button_callback(i: Inter, view: View, element: str):
    ambr = AmbrTopAPI(i.client.session, to_ambr_top(view.lang))
    characters = await ambr.get_character()
    if not isinstance(characters, List):
        raise TypeError("characters is not a list")
    options = []
    for character in characters:
        if character.element == element:
            character_id = character.id.split("-")[0]
            image_options = await image.get_user_custom_image_options(
                int(character_id), i.client.pool, i.user.id, view.lang
            )
            options.append(
                discord.SelectOption(
                    label=character.name,
                    description=text_map.get(532, view.lang).format(
                        num=len(image_options)
                    ),
                    value=str(character_id),
                    emoji=get_character_emoji(character.id),
                )
            )
    view.clear_items()
    view.add_item(CharacterSelect(view.lang, options, element))
    view.add_item(GoBack())
    embed = DefaultEmbed(description=text_map.get(276, view.lang))
    embed.set_author(
        name=text_map.get(62, view.lang), icon_url=i.user.display_avatar.url
    )
    await i.response.edit_message(view=view, embed=embed)


class AddImage(ui.Button):
    def __init__(
        self,
        lang: discord.Locale | str,
        character_id: int,
        element: str,
        disabled: bool,
    ):
        super().__init__(
            label=text_map.get(413, lang),
            style=discord.ButtonStyle.green,
            disabled=disabled,
        )
        self.character_id = character_id
        self.element = element
        self.view: View

    async def callback(self, i: Inter):
        await i.response.send_modal(
            AddImageModal(self.view.lang, self.character_id, self.view, self.element)
        )


class AddImageModal(BaseModal):
    nickname = ui.TextInput(
        label="Nickname",
        placeholder="Type a nickname for the custom image",
        max_length=25,
    )
    url = ui.TextInput(
        label="Image URL", placeholder="https://i.imgur.com/8lO5xNk.jpg", max_length=100
    )

    def __init__(
        self, lang: discord.Locale | str, character_id: int, view: View, element: str
    ):
        super().__init__(timeout=config.long_timeout, title=text_map.get(413, lang))
        self.nickname.placeholder = text_map.get(45, lang)
        self.nickname.label = text_map.get(601, lang)
        self.url.label = text_map.get(60, lang)
        self.character_id = character_id
        self.view = view
        self.element = element

    async def on_submit(self, i: Inter) -> None:
        check = await image.validate_image_url(self.url.value, i.client.session)
        if not check:
            return await i.response.send_message(
                embed=ErrorEmbed(
                    description=text_map.get(568, self.view.lang)
                ).set_author(
                    name=text_map.get(274, self.view.lang),
                    icon_url=i.user.display_avatar.url,
                ),
                ephemeral=True,
            )
        await image.add_user_custom_image(
            i.user.id,
            self.character_id,
            self.url.value,
            self.nickname.value,
            i.client.pool,
        )

        await return_custom_image_interaction(
            self.view, i, self.character_id, self.element
        )


class RemoveImage(ui.Button):
    def __init__(
        self,
        lang: discord.Locale | str,
        character_id: int,
        disabled: bool,
        element: str,
    ):
        super().__init__(
            label=text_map.get(61, lang),
            style=discord.ButtonStyle.red,
            disabled=disabled,
        )
        self.character_id = character_id
        self.element = element
        self.lang = lang
        self.view: View

    async def callback(self, i: Inter):
        custom_image = await image.get_user_custom_image(
            i.user.id, self.character_id, i.client.pool
        )
        if custom_image is None:
            raise AssertionError

        await image.remove_user_custom_image(
            i.user.id, custom_image.url, custom_image.character_id, i.client.pool
        )
        await return_custom_image_interaction(
            self.view, i, self.character_id, self.element
        )


class ImageSelect(ui.Select):
    def __init__(
        self,
        lang: discord.Locale | str,
        options: List[discord.SelectOption],
        character_id: int,
        element: str,
    ):
        super().__init__(
            placeholder=text_map.get(562, lang),
            options=options
            if options
            else [discord.SelectOption(label="none", value="none")],
            disabled=not options,
        )
        self.character_id = character_id
        self.element = element
        self.view: View

    async def callback(self, i: Inter):
        await image.change_user_custom_image(
            i.user.id, self.character_id, self.values[0], i.client.pool
        )
        await return_custom_image_interaction(
            self.view, i, self.character_id, self.element
        )


class CharacterSelect(ui.Select):
    def __init__(
        self,
        lang: discord.Locale | str,
        options: List[discord.SelectOption],
        element: str,
    ):
        super().__init__(placeholder=text_map.get(157, lang), options=options)
        self.element = element
        self.view: View

    async def callback(self, i: Inter):
        await return_custom_image_interaction(
            self.view, i, int(self.values[0].split("-")[0]), self.element
        )


async def return_custom_image_interaction(
    view: Union[View, EnkaView],
    i: Inter,
    character_id: int,
    element: str,
):
    try:
        await i.response.defer()
    except discord.InteractionResponded:
        pass

    embeds: List[discord.Embed] = []
    view.clear_items()
    if not isinstance(view, EnkaView):
        view.add_item(GoBackCharacter(element))
    else:
        v = View(view.lang)
        embeds.append(v.gen_embed())
        view.add_item(enka_damage_calc.GoBack())

    options = await image.get_user_custom_image_options(
        character_id, i.client.pool, i.user.id, view.lang
    )
    view.add_item(AddImage(view.lang, character_id, element, len(options) == 125))
    view.add_item(
        remove_image := RemoveImage(view.lang, character_id, bool(not options), element)
    )
    div_options: List[List[discord.SelectOption]] = list(divide_chunks(options, 25))
    for d_options in div_options:
        view.add_item(ImageSelect(view.lang, d_options, character_id, element))

    custom_image = await image.get_user_custom_image(
        i.user.id, character_id, i.client.pool
    )
    if custom_image is None or (custom_image and custom_image.from_shenhe):
        remove_image.disabled = True  # skipcq: PYL-W0201

    embed = await image.get_user_custom_image_embed(
        i, view.lang, str(character_id), custom_image
    )
    embeds.append(embed)
    view.message = await i.edit_original_response(
        embeds=embeds, view=view, attachments=[]
    )
    view.author = i.user
