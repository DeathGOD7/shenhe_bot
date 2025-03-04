from typing import Dict, List

import discord
from discord import ui

import ambr.models as ambr_models
import dev.asset as asset
import dev.config as config
from ambr import AmbrTopAPI
from apps.draw import main_funcs
from apps.text_map import text_map
from data.game.elements import get_element_emoji
from data.game.fight_prop import percentage_fight_props
from dev.base_ui import BaseView
from dev.models import DefaultEmbed, DrawInput, Inter
from utils import (
    divide_chunks,
    get_fight_prop,
    get_weekday_int_with_name,
    get_weekday_name,
)


class View(BaseView):
    def __init__(
        self,
        embeds: List[discord.Embed],
        options: List[discord.SelectOption],
        placeholder: str,
        all_materials,
        lang: discord.Locale | str,
        dark_mode: bool,
        character_element: str,
    ):
        super().__init__(timeout=config.long_timeout)
        self.add_item(QuickNavigation(options, placeholder))
        self.embeds = embeds
        self.all_materials = all_materials
        self.lang = lang
        self.dark_mode = dark_mode
        self.character_element = character_element


class QuickNavigation(ui.Select):
    def __init__(self, options: List[discord.SelectOption], placeholder: str):
        super().__init__(placeholder=placeholder, options=options)
        self.view: View

    async def callback(self, i: Inter):
        await i.response.defer()
        if self.values[0] == "1":
            fp = await main_funcs.draw_material_card(
                DrawInput(
                    loop=i.client.loop,
                    session=i.client.session,
                    lang=self.view.lang,
                    dark_mode=self.view.dark_mode,
                ),
                self.view.all_materials,
                text_map.get(320, self.view.lang),
            )
            fp.seek(0)
            file_ = discord.File(fp, filename="ascension.png")
            await i.edit_original_response(
                embed=self.view.embeds[1], attachments=[file_]
            )
        else:
            await i.edit_original_response(
                embed=self.view.embeds[int(self.values[0])], attachments=[]
            )


class BookVolView(BaseView):
    def __init__(
        self,
        embeds: Dict[str, discord.Embed],
        options: List[discord.SelectOption],
        placeholder: str,
    ):
        super().__init__(timeout=config.long_timeout)
        divided_options = list(divide_chunks(options, 25))
        current = 1
        for div in divided_options:
            self.add_item(BookVolumeNav(div, f"{placeholder} ({current}~{len(div)})"))
            current += len(div)
        self.embeds = embeds


class BookVolumeNav(ui.Select):
    def __init__(self, options: List[discord.SelectOption], placeholder: str):
        super().__init__(placeholder=placeholder, options=options)
        self.view: BookVolView

    async def callback(self, i: Inter):
        await i.response.edit_message(embed=self.view.embeds[self.values[0]])


async def parse_character_wiki(
    character: ambr_models.CharacterDetail,
    i: Inter,
    lang: discord.Locale | str,
    client: AmbrTopAPI,
    dark_mode: bool,
) -> None:
    embeds: List[discord.Embed] = []

    # basic info
    embed = DefaultEmbed(title=character.name)
    embed.set_thumbnail(url=character.icon)
    embed.add_field(
        name=text_map.get(315, lang),
        value=f"{text_map.get(316, lang)}: {character.birthday}\n"
        f"{text_map.get(317, lang)}: {character.info.title}\n"
        f"{text_map.get(318, lang)}: {character.info.constellation}\n"
        f"{text_map.get(467, lang).capitalize()}: {character.rarity} {asset.white_star_emoji}\n"
        f"{text_map.get(703, lang)}: {get_element_emoji(character.element)}\n",
        inline=False,
    )
    cv_str = ""
    for key, value in character.info.cv.items():
        cv_str += f"VA ({key}): {value}\n"
    if cv_str != "":
        embed.add_field(name="CV", value=cv_str, inline=False)
    embed.set_footer(text=character.info.description)
    embeds.append(embed)

    # ascension
    embed = DefaultEmbed(
        description=text_map.get(184, lang).format(
            command="</calc character:1020188057628065862>"
        )
    )
    embed.set_author(name=text_map.get(320, lang), icon_url=character.icon)
    embed.set_image(url="attachment://ascension.png")
    all_materials = []
    for material in character.ascension_materials:
        full_material = await client.get_material(int(material.id))
        if not isinstance(full_material, ambr_models.Material):
            continue
        all_materials.append((full_material, ""))
    embeds.append(embed)

    # talents
    count = 0
    passive_count = 0
    for talent in character.talents:
        if talent.type is ambr_models.CharacterTalentType.PASSIVE:
            passive_count += 1
        else:
            count += 1
        embed = DefaultEmbed(talent.name, talent.description)
        embed.set_author(
            name=text_map.get(
                323 if talent.type is ambr_models.CharacterTalentType.PASSIVE else 94,
                lang,
            )
            + f" {passive_count if talent.type is ambr_models.CharacterTalentType.PASSIVE else count}",
            icon_url=character.icon,
        )
        embed.set_thumbnail(url=talent.icon)
        embeds.append(embed)

    # constellations
    count = 0
    for constellation in character.constellations:
        count += 1
        embed = DefaultEmbed(constellation.name, constellation.description)
        embed.set_author(
            name=text_map.get(318, lang) + f" {count}",
            icon_url=character.icon,
        )
        embed.set_thumbnail(url=constellation.icon)
        embeds.append(embed)

    # namecard
    if character.other is not None:
        embed = DefaultEmbed(
            character.other.name_card.name,
            character.other.name_card.description,
        )
        embed.set_image(url=character.other.name_card.icon)
        embed.set_author(name=text_map.get(319, lang), icon_url=character.icon)
        embeds.append(embed)

    # select options
    options = []
    for index, embed in enumerate(embeds):
        prefix = embed.author.name if embed.author.name else ""
        suffix = f" | {embed.title}" if embed.title else ""
        options.append(
            discord.SelectOption(
                label=f"{prefix}{suffix}",
                value=str(index),
            )
        )
    view = View(
        embeds,
        options,
        text_map.get(325, lang),
        all_materials,
        lang,
        dark_mode,
        character.element,
    )
    view.author = i.user
    await i.edit_original_response(embed=embeds[0], view=view)
    view.message = await i.original_response()


def format_stat(curve: float, initial_value: float, percentage: bool = False) -> str:
    multiplier = 100 if percentage else 1
    rounded_value = round(curve * initial_value * multiplier, 1 if percentage else None)
    percent_symbol = "%" if percentage else ""
    return f"{rounded_value}{percent_symbol}"


async def parse_weapon_wiki(
    weapon: ambr_models.WeaponDetail,
    i: Inter,
    lang: discord.Locale | str,
    client: AmbrTopAPI,
    dark_mode: bool,
):
    rarity_str = ""
    for _ in range(weapon.rarity):
        rarity_str += asset.white_star_emoji
    embed = DefaultEmbed(weapon.name, f"{rarity_str}")
    embed.set_footer(text=weapon.description)
    embed.add_field(
        name=text_map.get(529, lang),
        value=weapon.type,
        inline=False,
    )
    if weapon.effect is not None:
        embed.add_field(
            name=f"{weapon.effect.name} (R1)",
            value=weapon.effect.descriptions[0],
            inline=False,
        )
        if len(weapon.effect.descriptions) > 4:
            embed.add_field(
                name=f"{weapon.effect.name} (R5)",
                value=weapon.effect.descriptions[4],
                inline=False,
            )

    max_level = weapon.upgrade.ascensions[-1].new_max_level
    for stat in weapon.upgrade.stats:
        if stat.prop_id is None:
            continue

        level_one_curve = await client.get_weapon_curve(stat.grow_type, 1)
        level_max_curve = await client.get_weapon_curve(stat.grow_type, max_level)
        percentage = stat.prop_id in percentage_fight_props

        embed.add_field(
            name=text_map.get(get_fight_prop(id=stat.prop_id).text_map_hash, lang),
            value=f"""
            Lv.1: {format_stat(level_one_curve, stat.initial_value, percentage)}
            Lv.{max_level}: {format_stat(level_max_curve, stat.initial_value, percentage)}
            """,
            inline=False,
        )

    embed.set_thumbnail(url=weapon.icon)

    # ascension
    embed.set_image(url="attachment://ascension.png")
    all_materials = []
    for material in weapon.ascension_materials:
        full_material = await client.get_material(int(material.id))
        if not isinstance(full_material, ambr_models.Material):
            continue
        all_materials.append((full_material, ""))
    fp = await main_funcs.draw_material_card(
        DrawInput(
            loop=i.client.loop,
            session=i.client.session,
            lang=lang,
            dark_mode=dark_mode,
        ),
        all_materials,
        text_map.get(320, lang),
    )
    fp.seek(0)

    embed.add_field(
        name=text_map.get(320, lang),
        value=text_map.get(188, lang).format(
            command="</calc weapon:1020188057628065862>"
        ),
        inline=False,
    )
    await i.followup.send(embed=embed, file=discord.File(fp, "ascension.png"))


async def parse_material_wiki(
    material: ambr_models.MaterialDetail,
    i: Inter,
    lang: discord.Locale | str,
    client: AmbrTopAPI,
    dark_mode: bool,
):
    rarity_str = ""
    for _ in range(material.rarity):
        rarity_str += asset.white_star_emoji
    embed = DefaultEmbed(material.name, f"{rarity_str}\n\n{material.description}")
    embed.add_field(
        name=text_map.get(529, lang),
        value=material.type,
        inline=False,
    )
    if material.sources is not None and material.sources:
        source_str = ""
        for index, source in enumerate(material.sources):
            if index == 10:
                break
            day_str = ""
            if len(source.days) != 0:
                day_list = [
                    get_weekday_name(get_weekday_int_with_name(day), lang)
                    for day in source.days
                ]
                day_str = ", ".join(day_list)
            day_str = "" if len(source.days) == 0 else f"({day_str})"
            source_str += f"• {source.name} {day_str}\n"
        embed.add_field(
            name=text_map.get(530, lang),
            value=source_str,
            inline=False,
        )
    files = []
    upgrades = [
        await client.get_character_upgrade(),
        await client.get_weapon_upgrade(),
    ]
    matches: List[ambr_models.CharacterUpgrade | ambr_models.WeaponUpgrade] = []
    for upgrade in upgrades:
        for u in upgrade:
            material_ids = [m.name for m in u.items]
            if material.name in material_ids:
                matches.append(u)
    if matches:
        objects = []
        for match in matches:
            if isinstance(match, ambr_models.CharacterUpgrade):
                character = await client.get_character(match.character_id)
                if not isinstance(character, ambr_models.Character):
                    continue
                objects.append((character, ""))
            else:
                weapon = await client.get_weapon(match.weapon_id)
                if not isinstance(weapon, ambr_models.Weapon):
                    continue
                objects.append((weapon, ""))
        fp = await main_funcs.draw_material_card(
            DrawInput(
                loop=i.client.loop,
                session=i.client.session,
                lang=lang,
                dark_mode=dark_mode,
            ),
            objects,
            text_map.get(587, lang),
        )
        fp.seek(0)
        embed.set_image(url="attachment://characters.png")
        files = [discord.File(fp, "characters.png")]
    embed.set_thumbnail(url=material.icon)
    await i.followup.send(embed=embed, files=files)


async def parse_artifact_wiki(
    artifact: ambr_models.ArtifactDetail,
    i: Inter,
    lang: discord.Locale | str,
):
    rarity_str = ""
    for _ in range(artifact.rarities[-1]):
        rarity_str += asset.white_star_emoji
    embed = DefaultEmbed(artifact.name, rarity_str)
    embed.add_field(
        name=text_map.get(640, lang),
        value=artifact.effects.two_piece,
        inline=False,
    )
    embed.add_field(
        name=text_map.get(641, lang),
        value=artifact.effects.four_piece,
        inline=False,
    )
    embed.set_thumbnail(url=artifact.icon)
    await i.followup.send(embed=embed)


async def parse_monster_wiki(
    monster: ambr_models.MonsterDetail,
    i: Inter,
    lang: discord.Locale | str,
    client: AmbrTopAPI,
    dark_mode: bool,
):
    embed = DefaultEmbed(monster.name, monster.description)
    embed.set_author(name=monster.type)
    embed.set_thumbnail(url=monster.icon)
    files = []
    if monster.data.drops is not None and monster.data.drops:
        materials = []
        for ingredient in monster.data.drops:
            mat = await client.get_material(int(ingredient.id))
            if not isinstance(mat, ambr_models.Material):
                continue
            materials.append((mat, ingredient.count or ""))
        fp = await main_funcs.draw_material_card(
            DrawInput(
                loop=i.client.loop,
                session=i.client.session,
                lang=lang,
                dark_mode=dark_mode,
            ),
            materials,
            text_map.get(622, lang),
        )
        fp.seek(0)
        discord_file = discord.File(fp, "monster_drop.png")
        embed.set_image(url="attachment://monster_drop.png")
        files.append(discord_file)
    await i.followup.send(embed=embed, files=files)


async def parse_food_wiki(
    food: ambr_models.FoodDetail,
    i: Inter,
    lang: discord.Locale | str,
    client: AmbrTopAPI,
    dark_mode: bool,
):
    rarity_str = ""
    for _ in range(food.rarity):
        rarity_str += asset.white_star_emoji
    embed = DefaultEmbed(food.name, rarity_str)
    embed.set_thumbnail(url=food.icon)
    embed.set_footer(text=food.description)
    embed.set_author(name=food.type)
    files = []
    if food.recipe is not None:
        effect_str = "\n".join([s.effect for s in food.recipe.effects])
        embed.add_field(name=text_map.get(347, lang), value=effect_str)
        if food.recipe.input is not None and food.recipe.input:
            materials = []
            for ingredient in food.recipe.input:
                mat = await client.get_material(int(ingredient.id))
                if not isinstance(mat, ambr_models.Material):
                    continue
                materials.append((mat, ingredient.count))
            fp = await main_funcs.draw_material_card(
                DrawInput(
                    loop=i.client.loop,
                    session=i.client.session,
                    lang=lang,
                    dark_mode=dark_mode,
                ),
                materials,
                text_map.get(626, lang),
            )
            fp.seek(0)
            discord_file = discord.File(fp, "furniture_recipe.png")
            embed.set_image(url="attachment://furniture_recipe.png")
            files.append(discord_file)
    if food.sources is not None and food.sources:
        embed.add_field(
            name=text_map.get(621, lang),
            value="\n".join([s.name for s in food.sources]),
        )
    await i.followup.send(embed=embed, files=files)


async def parse_furniture_wiki(
    furniture: ambr_models.FurnitureDetail,
    i: Inter,
    lang: discord.Locale | str,
    client: AmbrTopAPI,
    dark_mode: bool,
):
    embed = DefaultEmbed(furniture.name)
    embed.description = f"""
        {furniture.description}

        {asset.comfort_emoji} {text_map.get(255, lang)}: {furniture.comfort or 0}
        {asset.load_emoji} {text_map.get(456, lang)}: {furniture.cost or 0}
    """
    embed.set_thumbnail(url=furniture.icon)
    embed.set_author(name=f"{furniture.categories[0]} - {furniture.types[0]}")
    files = []
    if furniture.recipe is not None and furniture.recipe.input is not None:
        materials = []
        for ingredient in furniture.recipe.input:
            mat = await client.get_material(int(ingredient.id))
            if not isinstance(mat, ambr_models.Material):
                continue
            materials.append((mat, ingredient.count))
        fp = await main_funcs.draw_material_card(
            DrawInput(
                loop=i.client.loop,
                session=i.client.session,
                lang=lang,
                dark_mode=dark_mode,
            ),
            materials,
            text_map.get(626, lang),
        )
        fp.seek(0)
        discord_file = discord.File(fp, "furniture_recipe.png")
        embed.set_image(url="attachment://furniture_recipe.png")
        files.append(discord_file)
    await i.followup.send(embed=embed, files=files)


async def parse_namecard_wiki(
    namecard: ambr_models.NameCardDetail,
    i: Inter,
    lang: discord.Locale | str,
):
    rarity_str = ""
    for _ in range(namecard.rarity):
        rarity_str += asset.white_star_emoji
    embed = DefaultEmbed(namecard.name, rarity_str)
    embed.set_author(name=namecard.type)
    embed.set_image(url=namecard.icon)
    embed.add_field(name=text_map.get(530, lang), value=namecard.source)
    await i.followup.send(embed=embed)


async def parse_book_wiki(
    book: ambr_models.BookDetail,
    i: Inter,
    lang: discord.Locale | str,
    client: AmbrTopAPI,
):
    rarity_str = ""
    for _ in range(book.rarity):
        rarity_str += asset.white_star_emoji
    book_embed = DefaultEmbed(book.name, rarity_str)
    book_embed.set_thumbnail(url=book.icon)
    book_embeds: Dict[str, discord.Embed] = {}
    options = [discord.SelectOption(label=book.name, value="book_info")]
    for volume in book.volumes:
        story = await client.get_book_story(volume.story_id)
        embed = DefaultEmbed(volume.name, story)
        embed.set_footer(text=volume.description)
        options.append(discord.SelectOption(label=volume.name, value=str(volume.id)))
        book_embeds[str(volume.id)] = embed
    book_embeds["book_info"] = book_embed
    view = BookVolView(
        book_embeds,
        options,
        text_map.get(501, lang),
    )
    view.author = i.user
    await i.followup.send(embed=book_embed, view=view)
    view.message = await i.original_response()
