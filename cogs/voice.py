import aiosqlite
from discord import Interaction, Member, NotFound, VoiceChannel, VoiceState, app_commands, InviteTarget
from discord.ext import commands
from utility.utils import defaultEmbed, errEmbed
import wavelink


class VoiceCog(commands.GroupCog, name='vc'):
    def __init__(self, bot):
        self.bot: commands.Bot = bot
        super().__init__()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: Member, before: VoiceState, after: VoiceState):
        vc: VoiceChannel = self.bot.get_channel(
            980772222148952064) if not self.bot.debug_toggle else self.bot.get_channel(980779246035271700)
        vc_role = member.guild.get_role(
            980774103344640000) if not self.bot.debug_toggle else member.guild.get_role(980774369771008051)
        old_channel: VoiceChannel = before.channel
        new_channel: VoiceChannel = after.channel
        c: aiosqlite.Cursor = await self.bot.db.cursor()
        if new_channel is None and old_channel is not None and len(old_channel.members) == 1 and old_channel.members[0].id == self.bot.user.id:
            vc: wavelink.Player = member.guild.voice_client
            vc.queue.clear()
            await vc.stop()
            await vc.disconnect()
        if new_channel is not None:
            await member.add_roles(vc_role)
        if new_channel == vc:
            member_vc = await member.guild.create_voice_channel(name=f'{member.name}的語音台', category=vc.category)
            await member.move_to(member_vc)
            await member.add_roles(vc_role)
            await c.execute('INSERT INTO voice (owner_id, channel_id) VALUES (?, ?)', (member.id, member_vc.id))
        if new_channel is None:
            await member.remove_roles(vc_role)
            await c.execute('SELECT * FROM voice WHERE owner_id = ? AND channel_id = ?', (member.id, old_channel.id))
            owner = await c.fetchone()
            if owner is not None and len(old_channel.members) != 0:
                await c.execute('UPDATE voice SET owner_id = ? WHERE channel_id = ?', (old_channel.members[0].id, old_channel.id))
        if old_channel is not None and old_channel != vc and len(old_channel.members) == 0:
            try:
                await old_channel.delete()
            except NotFound:
                pass
            await c.execute('DELETE FROM voice WHERE channel_id = ?', (old_channel.id,))
        await self.bot.db.commit()

    async def check_owner(self, channel_id: int, user_id: int):
        c: aiosqlite.Cursor = await self.bot.db.cursor()
        await c.execute('SELECT owner_id FROM voice WHERE channel_id = ?', (channel_id,))
        owner_id = await c.fetchone()
        owner_id = owner_id[0]
        if user_id == owner_id:
            return True, None
        else:
            return False, errEmbed().set_author(name='你不是這個語音台的擁有者', icon_url=self.bot.get_user(user_id).avatar)

    @app_commands.command(name='rename命名', description='重新命名語音台')
    @app_commands.rename(new='新名稱')
    @app_commands.describe(new='新的語音台名稱')
    async def vc_rename(self, i: Interaction, new: str):
        if i.user.voice is None:
            return await i.response.send_message(embed=errEmbed().set_author(name='你必須在語音台裡才能用這個指令', icon_url=i.user.avatar), ephemeral=True)
        current_vc = i.user.voice.channel
        owner, err_msg = await self.check_owner(current_vc.id, i.user.id)
        if not owner:
            return await i.response.send_message(embed=err_msg, ephemeral=True)
        await current_vc.edit(name=new)
        await i.response.send_message(embed=defaultEmbed(message=f'新名稱: {new}').set_author(name='語音台名稱更改成功', icon_url=i.user.avatar))

    @app_commands.command(name='lock鎖上', description='鎖上語音台')
    async def vc_lock(self, i: Interaction):
        if i.user.voice is None:
            return await i.response.send_message(embed=errEmbed().set_author(name='你必須在語音台裡才能用這個指令', icon_url=i.user.avatar), ephemeral=True)
        current_vc = i.user.voice.channel
        owner, err_msg = await self.check_owner(current_vc.id, i.user.id)
        if not owner:
            return await i.response.send_message(embed=err_msg, ephemeral=True)
        for member in current_vc.members:
            await current_vc.set_permissions(member, connect=True)
        traveler = i.guild.get_role(
            978532779098796042) if not self.bot.debug_toggle else i.guild.default_role
        await current_vc.set_permissions(traveler, connect=False)
        await i.response.send_message(embed=defaultEmbed(f'{current_vc.name}被鎖上了'))

    @app_commands.command(name='unlock解鎖', description='解鎖語音台')
    async def vc_unlock(self, i: Interaction):
        if i.user.voice is None:
            return await i.response.send_message(embed=errEmbed().set_author(name='你必須在語音台裡才能用這個指令', icon_url=i.user.avatar), ephemeral=True)
        current_vc = i.user.voice.channel
        owner, err_msg = await self.check_owner(current_vc.id, i.user.id)
        if not owner:
            return await i.response.send_message(embed=err_msg, ephemeral=True)
        traveler = i.guild.get_role(
            978532779098796042) if not self.bot.debug_toggle else i.guild.default_role
        await current_vc.set_permissions(traveler, connect=True)
        await i.response.send_message(embed=defaultEmbed(f'{current_vc.name}的封印被解除了'))

    @app_commands.command(name='transfer移交', description='移交房主權')
    @app_commands.rename(new='新房主')
    @app_commands.describe(new='新的房主')
    async def vc_unlock(self, i: Interaction, new: Member):
        if i.user.voice is None:
            return await i.response.send_message(embed=errEmbed().set_author(name='你必須在語音台裡才能用這個指令', icon_url=i.user.avatar), ephemeral=True)
        current_vc = i.user.voice.channel
        owner, err_msg = await self.check_owner(current_vc.id, i.user.id)
        if not owner:
            return await i.response.send_message(embed=err_msg, ephemeral=True)
        c: aiosqlite.Cursor = await self.bot.db.cursor()
        await c.execute('UPDATE voice SET owner_id = ? WHERE channel_id = ?', (new.id, current_vc.id))
        await self.bot.db.commit()
        await i.response.send_message(content=f'{i.user.mention} {new.mention}', embed=defaultEmbed(f'房主換人啦', f' {i.user.mention} 將 {current_vc.name} 的房主權移交給了 {new.mention}'))

    @app_commands.command(name='youtube播放器', description='為當前的語音台創建一個 youtube 播放器')
    async def vc_activity(self, i: Interaction):
        if i.user.voice is None:
            return await i.response.send_message(embed=errEmbed().set_author(name='你必須在語音台裡才能用這個指令', icon_url=i.user.avatar), ephemeral=True)
        vc = i.user.voice.channel
        invite = await vc.create_invite(
            max_age=0,
            max_uses=0,
            target_application_id=880218394199220334,
            target_type=InviteTarget.embedded_application
        )
        await i.response.send_message(embed=defaultEmbed('播放器已創建', f'{invite}\n\n點擊連結來啟用'), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceCog(bot))
