from typing import Any, List, Union

import discord
import enkanetwork as enka
from discord import ui, utils

import dev.asset as asset
import dev.config as config
import dev.models as models
from apps.db.tables.user_settings import Settings
from apps.draw.main_funcs import draw_artifact_card
from apps.text_map import text_map
from dev.base_ui import EnkaView
from dev.exceptions import FeatureDisabled
from ui.genshin import enka_damage_calc, profile_settings
from ui.others.settings import custom_image
from utils import divide_chunks, get_dt_now
from yelan.damage_calculator import return_current_status


class View(EnkaView):
    def __init__(
        self,
        character_options: List[discord.SelectOption],
        lang: Union[discord.Locale, str],
    ):
        super().__init__(timeout=config.mid_timeout)

        options: List[List[discord.SelectOption]] = list(
            divide_chunks(character_options, 25)
        )

        self.add_item(OverviewButton(text_map.get(43, lang)))
        self.add_item(BoxButton(options, text_map.get(105, lang)))
        self.add_item(CalculateDamageButton(text_map.get(348, lang)))
        self.add_item(SetCustomImage(lang))
        self.add_item(ShowArtifacts(text_map.get(92, lang)))
        self.add_item(InfoButton())
        self.add_item(CardSettings())

        self.original_children = self.children.copy()
        self.character_options = character_options


class InfoButton(ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary, emoji=asset.info_emoji, row=1
        )
        self.view: View

    async def callback(self, i: models.Inter):
        await i.response.send_message(
            embed=models.DefaultEmbed(description=text_map.get(399, self.view.lang)),
            ephemeral=True,
        )


class OverviewButton(ui.Button):
    def __init__(self, label: str):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=label,
            custom_id="overview",
            disabled=True,
            row=0,
            emoji=asset.overview_emoji,
        )
        self.view: View

    async def callback(self, i: models.Inter):
        set_custom_image = utils.get(self.view.children, custom_id="set_custom_image")
        calculate = utils.get(self.view.children, custom_id="calculate")
        show_artifacts = utils.get(self.view.children, custom_id="show_artifacts")

        self.disabled = True
        set_custom_image.disabled = True  # type: ignore
        calculate.disabled = True  # type: ignore
        show_artifacts.disabled = True  # type: ignore

        [fp, fp_two] = self.view.overview_fps
        fp.seek(0)
        fp_two.seek(0)
        attachments = [
            discord.File(fp, filename="profile.png"),
            discord.File(fp_two, filename="character.png"),
        ]
        await i.response.edit_message(
            embeds=self.view.overview_embeds,
            attachments=attachments,
            view=self.view,
        )


class SetCustomImage(ui.Button):
    def __init__(self, lang: discord.Locale | str):
        super().__init__(
            style=discord.ButtonStyle.green,
            label=text_map.get(62, lang),
            custom_id="set_custom_image",
            disabled=True,
            row=1,
            emoji=asset.image_emoji,
        )
        self.view: EnkaView

    async def callback(self, i: models.Inter) -> Any:
        character = utils.get(self.view.data.characters, id=int(self.view.character_id))
        if character is None:
            raise AssertionError

        await custom_image.return_custom_image_interaction(
            self.view, i, int(self.view.character_id), character.element.name
        )


class BoxButton(ui.Button):
    def __init__(self, options: List[List[discord.SelectOption]], label: str):
        super().__init__(
            emoji=asset.character_emoji,
            style=discord.ButtonStyle.blurple,
            row=0,
            label=label,
            custom_id="box",
        )
        self.options = options
        self.view: EnkaView

    async def callback(self, i: models.Inter):
        self.view.clear_items()
        count = 1
        for option in self.options:
            character_num = len(option)
            self.view.add_item(
                PageSelect(
                    option,
                    text_map.get(157, self.view.lang)
                    + f" ({count}~{count+character_num-1})",
                )
            )
            count += character_num

        await i.response.edit_message(view=self.view)


class PageSelect(ui.Select):
    def __init__(self, character_options: list[discord.SelectOption], plceholder: str):
        super().__init__(placeholder=plceholder, options=character_options)
        self.view: EnkaView

    async def callback(self, i: models.Inter) -> Any:
        self.view.character_id = self.values[0]
        await enka_damage_calc.go_back_callback(i, self.view)


class CalculateDamageButton(ui.Button):
    def __init__(self, label: str):
        super().__init__(
            style=discord.ButtonStyle.blurple,
            label=label,
            disabled=True,
            custom_id="calculate",
            row=0,
            emoji=asset.calculator_emoji,
        )
        self.view: EnkaView

    async def callback(self, i: models.Inter) -> Any:
        now = get_dt_now()
        if now.month == 4 and now.day == 1:
            raise FeatureDisabled

        view = enka_damage_calc.View(self.view, self.view.lang, i.client.browsers)
        view.author = i.user
        await return_current_status(i, view)
        view.message = await i.original_response()


class ShowArtifacts(ui.Button):
    def __init__(self, label: str):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.blurple,
            custom_id="show_artifacts",
            disabled=True,
            emoji=asset.artifact_emoji,
            row=1,
        )
        self.view: EnkaView

    async def callback(self, i: models.Inter) -> Any:
        character = utils.get(self.view.data.characters, id=int(self.view.character_id))
        if not character:
            raise AssertionError

        await i.response.defer()
        fp = await draw_artifact_card(
            models.DrawInput(
                loop=i.client.loop,
                session=i.client.session,
                lang=self.view.lang,
                dark_mode=await i.client.db.settings.get(i.user.id, Settings.DARK_MODE),
            ),
            [e for e in character.equipments if e.type is enka.EquipmentsType.ARTIFACT],
            character,
        )
        fp.seek(0)

        file_ = discord.File(fp, filename="artifact.png")
        await i.edit_original_response(attachments=[file_])


class CardSettings(ui.Button):
    def __init__(self):
        super().__init__(emoji=asset.settings_emoji, row=1, disabled=True)
        self.view: EnkaView

    async def callback(self, i: models.Inter) -> Any:
        view = profile_settings.View(self.view.lang, self.view)
        view.author = i.user
        await i.response.edit_message(
            embed=view.gen_settings_embed(), view=view, attachments=[]
        )
        view.message = await i.original_response()
