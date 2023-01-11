from typing import Optional
import asqlite
from apps.genshin.utils import get_uid
from apps.text_map.text_map_app import text_map
from apps.text_map.utils import get_user_locale
from discord import Interaction, app_commands, User, Member
from discord.errors import InteractionResponded
from utility.utils import error_embed


def check_account():
    """
    Checks if the user has an account. If the user has an account, they will have a UID, but they might not have a Cookie.
    """

    async def predicate(i: Interaction) -> bool:
        return await check_account_predicate(i)

    return app_commands.check(predicate)


async def check_account_predicate(
    i: Interaction, member: Optional[User | Member] = None, respond_message: bool = True
) -> bool:
    if "member" in i.namespace.__dict__:
        user = i.namespace["member"]
    elif "user" in i.namespace.__dict__:
        user = i.namespace["user"]
    else:
        user = i.user
    user = member or user
    locale = (await get_user_locale(i.user.id, i.client.pool)) or i.locale

    pool: asqlite.Pool = i.client.pool # type: ignore
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT uid FROM user_accounts WHERE user_id = ?", (user.id,)
        ) as c:
            uid = await c.fetchone()
    if uid is None:
        if respond_message:
            embed = error_embed(message=text_map.get(572, locale)).set_author(
                name=text_map.get(571 if user.id == i.user.id else 579, locale),
                icon_url=user.display_avatar.url,
            )
            try:
                await i.response.send_message(
                    embed=embed,
                    ephemeral=True,
                )
            except InteractionResponded:
                await i.followup.send(embed=embed, ephemeral=True)
        return False
    else:
        return True


def check_cookie():
    """Checks if the current user account has a cookie."""

    async def predicate(i: Interaction) -> bool:
        check = await check_cookie_predicate(i)
        return check

    return app_commands.check(predicate)


def check_wish_history():
    """Checks if the current user account has a wish history."""

    async def predicate(i: Interaction) -> bool:
        if "member" in i.namespace.__dict__:
            user = i.namespace["member"]
        elif "user" in i.namespace.__dict__:
            user = i.namespace["user"]
        else:
            user = i.user
        user_locale = await get_user_locale(i.user.id, i.client.pool)

        pool: asqlite.Pool = i.client.pool # type: ignore
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT wish_id FROM wish_history WHERE user_id = ? AND uid = ?",
                (user.id, await get_uid(i.user.id, pool)),
            ) as c:
                data = await c.fetchone()

        if data is None:
            await i.response.send_message(
                embed=error_embed(
                    message=text_map.get(368, i.locale, user_locale)
                ).set_author(
                    name=text_map.get(683, i.locale, user_locale),
                    icon_url=user.display_avatar.url,
                ),
                ephemeral=True,
            )
            return False
        else:
            return True

    return app_commands.check(predicate)


async def check_cookie_predicate(
    i: Interaction, member: Optional[User | Member] = None, respond_message: bool = True
) -> bool:
    check = await check_account_predicate(i, member)
    if not check:
        return False
    if "member" in i.namespace.__dict__:
        user = i.namespace["member"]
    elif "user" in i.namespace.__dict__:
        user = i.namespace["user"]
    else:
        user = i.user
    user = member or user
    locale = (await get_user_locale(i.user.id, i.client.pool)) or i.locale
    
    pool: asqlite.Pool = i.client.pool # type: ignore
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT ltuid FROM user_accounts WHERE user_id = ? AND current = 1",
            (user.id,),
        ) as c:
            data = await c.fetchone()
            if data is None or data[0] is None:
                await c.execute(
                    "SELECT ltuid FROM user_accounts WHERE user_id = ? AND current = 0",
                    (user.id,),
                )
                if (await c.fetchone()) is None:
                    embed = error_embed(message=text_map.get(572, locale)).set_author(
                        name=text_map.get(573 if user.id == i.user.id else 580, locale),
                        icon_url=user.display_avatar.url,
                    )
                    if respond_message:
                        try:
                            await i.response.send_message(
                                embed=embed,
                                ephemeral=True,
                            )
                        except InteractionResponded:
                            await i.followup.send(embed=embed, ephemeral=True)
                else:
                    embed = error_embed(message=text_map.get(575, locale)).set_author(
                        name=text_map.get(574 if user.id == i.user.id else 581, locale),
                        icon_url=user.display_avatar.url,
                    )
                    if respond_message:
                        try:
                            await i.response.send_message(
                                embed=embed,
                                ephemeral=True,
                            )
                        except InteractionResponded:
                            await i.followup.send(embed=embed, ephemeral=True)
                return False
            else:
                return True
