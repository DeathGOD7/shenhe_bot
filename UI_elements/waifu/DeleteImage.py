import config
from UI_base_models import BaseView
from discord.errors import Forbidden, NotFound
from discord import Interaction, User
from discord.ui import Button, button
from utility.utils import error_embed


class View(BaseView):
    def __init__(self, author: User):
        super().__init__(timeout=config.long_timeout)
        self.author = author

    @button(label="刪除圖片", emoji="🗑️")
    async def delete_image(self, i: Interaction, button: Button):
        try:
            await i.response.defer()
        except NotFound:
            return
        try:
            await i.message.delete()
        except Forbidden:
            await i.followup.send(
                embed=error_embed(message="申鶴沒有移除訊息的權限，請檢查權限設定。").set_author(
                    name="訊息刪除失敗", icon_url=i.user.display_avatar.url
                )
            )
        except NotFound:
            await i.followup.send(
                embed=error_embed(message="訊息已經被刪除了。").set_author(
                    name="訊息刪除失敗", icon_url=i.user.display_avatar.url
                )
            )
