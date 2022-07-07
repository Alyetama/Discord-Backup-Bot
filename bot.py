#!/usr/bin/env python
# coding: utf-8

import inspect
import io
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

import discord
import requests
from discord.ext import commands  # noqa: F401
from dotenv import load_dotenv
from loguru import logger
from minio import Minio


class _UploadFile:

    def __init__(self, raw_data, object_name):
        self.raw_data = raw_data
        self.object_name = object_name

    def get_compressed_file_object(self):
        with tempfile.NamedTemporaryFile(suffix='.zip') as f:
            with zipfile.ZipFile(f,
                                 mode='w',
                                 compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=9) as zf:
                with tempfile.NamedTemporaryFile() as rf:
                    rf.write(json.dumps(self.raw_data).encode('utf-8'))
                    rf.seek(0)
                    zf.write(rf.name, arcname=Path(self.object_name).stem)
            f.flush()
            f.seek(0)
            obj = io.BytesIO(f.read())
        return obj

    def upload_s3_object(self, object_data):
        client = Minio(os.getenv('S3_ENDPOINT'), os.getenv('S3_ACCESS_KEY'),
                       os.getenv('S3_SECRET_KEY'))
        s3_object = client.put_object(os.getenv('S3_BUCKET_NAME'),
                                      self.object_name,
                                      object_data,
                                      object_data.getbuffer().nbytes,
                                      content_type='application/zip')
        presigned_url = client.presigned_get_object(s3_object.bucket_name,
                                                    s3_object.object_name)
        return presigned_url

    @staticmethod
    def shorten_url(long_url):
        request_data = {
            'key': os.getenv('POLR_KEY'),
            'url': long_url,
            'is_secret': False
        }
        res = requests.post(
            f'{os.getenv("POLR_SERVER")}/api/v2/action/shorten',
            json=request_data)
        if res.status_code != 200:
            return long_url
        return res.text

    def fileio_upload(self, object_data):
        url = 'https://file.io'
        r = requests.post(
            url,
            files={'file': (self.object_name, object_data, 'application/zip')})
        if r.status_code == 200:
            return r.json()['link']


def update_embed(embed, cur_progress, total_channels, num_messages, message):
    embed.set_field_at(index=0,
                       name='Number of backed up channels:',
                       value=f'{cur_progress}/{total_channels}',
                       inline=False)
    embed.set_field_at(index=1,
                       name='Number of backed up messages (total):',
                       value=num_messages,
                       inline=False)
    embed.set_field_at(index=2,
                       name='Latest update:',
                       value=message,
                       inline=False)
    return embed


def main():
    config = {
        'handlers': [
            {
                'sink': sys.stdout,
                'format': '{extra[server_id]} {extra[user_id]} {message}'
            },
            {
                'sink': 'logs.log',
                'serialize': True
            },
        ]
    }

    logger.configure(**config)

    GET_DATA = False  # todo; if true, can only export as pickle.

    load_dotenv()
    intents = discord.Intents.default()
    try:
        intents.message_content = True
        intents.members = True
    except AttributeError:
        print(f'WARNING: detected version: {discord.__version__}! '
              'Stickers data will not be exported...')

    bot = commands.Bot(
        command_prefix='!',
        intents=intents,
        description='A Discord bot to automatically back up the server '
        'messages data.')

    @bot.event
    async def on_ready():
        print(f'Logged in as {bot.user.name} ({bot.user.id})')
        print('-' * 80)

    def get_guild(guild):
        guild_dict = {}
        guild_attr_get_id_name = [
            'system_channel', 'voice_channels', 'text_channels',
            'default_role', 'categories', 'stage_channels',
            'premium_subscribers', 'channels', 'premium_subscriber_role',
            'rules_channel', 'owner', 'self_role', 'public_updates_channel',
            'members', 'me'
        ]
        special_guild_attrs = [
            'afk_channel', 'verification_level', 'explicit_content_filter',
            'default_notifications', 'voice_client'
        ]
        guild_is_level_attrs = ['nsfw_level', 'mfa_level']
        for attr in dir(guild):
            if attr.startswith('_') or inspect.ismethod(getattr(guild, attr)):
                continue

            val = getattr(guild, attr)

            if attr in guild_is_level_attrs:
                guild_dict[attr] = {
                    x: getattr(val, x)
                    for x in ['name', 'value']
                }

            elif attr == 'system_channel_flags':
                guild_dict[attr] = {
                    k: getattr(val, k)
                    for k in dir(val) if not k.startswith('_')
                    if k not in ['count', 'index']
                }

            elif attr in special_guild_attrs:
                if val:
                    try:
                        guild_dict[attr] = val.name
                    except AttributeError:
                        guild_dict[attr] = None
                else:
                    guild_dict[attr] = val

            elif attr in ['region', 'created_at']:
                guild_dict[attr] = str(val)

            elif attr == 'roles':
                _vals = []
                for _val in val:
                    _d = {
                        x: getattr(_val, x)
                        for x in dir(_val)
                        if (not x.startswith('_') and not inspect.ismethod(
                            getattr(_val, x)) and x != 'guild')
                    }
                    _d.pop('members')
                    for _k, _v in _d.items():
                        if _k == 'created_at':
                            _d[_k] = str(_d[_k])
                        elif _k == 'color':
                            _d[_k] = _d[_k].to_rgb()
                        elif _k == 'permissions':
                            _d[_k] = _d[_k].value
                        elif _k == 'tags':
                            _tags = {
                                _tag: getattr(_d[_k], _tag)
                                for _tag in dir(_d[_k]) if _tag in [
                                    'bot_id', 'integration_id',
                                    'premium_subscriber', 'unicode_emoji'
                                ]
                            }
            elif attr in ['emojis', 'stickers']:
                _vals = []
                for _val in val:
                    _d = {
                        x: getattr(_val, x)
                        for x in dir(_val)
                        if (not x.startswith('_') and not inspect.ismethod(
                            getattr(_val, x)) and x != 'guild')
                    }
                    _d['created_at'] = str(_d['created_at'])
                    _vals.append(_d)

                guild_dict[attr] = _vals

            elif attr == 'icon':
                if val:
                    guild_dict[attr] = val.url
                else:
                    guild_dict[attr] = None

            elif attr == 'preferred_locale':
                guild_dict[attr] = val.name

            elif attr == 'guild':
                guild_dict[attr] = {
                    x: getattr(val, x)
                    for x in dir(val)
                    if (not x.startswith('_')
                        and not inspect.ismethod(getattr(val, x)))
                }
            elif attr in guild_attr_get_id_name:
                if not val:
                    continue
                try:
                    iter(val)
                except TypeError:
                    guild_dict[attr] = {
                        x: getattr(val, x)
                        for x in ['id', 'name']
                    }
                    continue

                _vals = []
                for _val in val:
                    _vals.append({x: getattr(_val, x) for x in ['id', 'name']})
                guild_dict[attr] = _vals
            else:
                guild_dict[attr] = val
        return guild_dict

    async def get_members(members_iterator):
        members_dicts = []

        members_as_is_attrs = [
            'activities', 'bot', 'desktop_status', 'discriminator',
            'display_name', 'id', 'joined_at', 'mention', 'mobile_status',
            'mutual_guilds', 'name', 'pending', 'raw_status', 'roles',
            'status', 'system', 'web_status'
        ]

        async for member in members_iterator:
            member_dict = {}
            guild_permissions = {}
            for x in dir(member.guild_permissions):
                if not x.startswith('_'):
                    _val = getattr(member.guild_permissions, x)
                    if not inspect.ismethod(_val):
                        guild_permissions[x] = _val
            member_dict['guild_permissions'] = guild_permissions
            member_dict['roles'] = [{
                'id': x.id,
                'name': x.name
            } for x in member.roles]

            for attr in members_as_is_attrs:
                if attr in ['created_at', 'joined_at']:
                    val = str(getattr(member, attr))
                elif 'status' in attr:
                    continue
                elif attr in ['roles', 'mutual_guilds']:
                    if attr == 'mutual_guilds' and not hasattr(
                            member, 'mutual_guilds'):
                        val = None
                    else:
                        _val = getattr(member, attr)
                        val = [{'id': x.id, 'name': x.name} for x in _val]
                else:
                    val = getattr(member, attr)
                member_dict[attr] = val

            members_dicts.append(member_dict)

        members_dicts = {x['id']: x for x in members_dicts}
        return members_dicts

    async def backup_channel(channel):
        regular_types = [
            'activity', 'application', 'clean_content', 'content', 'id',
            'jump_url', 'mention_everyone', 'pinned', 'system_content', 'tts',
            'webhook_id', 'raw_channel_mentions', 'raw_mentions',
            'raw_role_mentions', 'created_at'
        ]  # as it is
        cls_methods = [
            'clear_reaction', 'delete', 'pin', 'reply', 'publish',
            'to_message_reference_dict', 'is_system', 'to_reference', 'unpin',
            'ack', 'edit', 'add_reaction', 'remove_reaction', 'clear_reactions'
        ]  # ignore these attrs
        ignore = ['call', 'nonce'
                  ]  # "call" is deprecated, "nonce" is almost always None

        public_attrs = []
        history = []

        async for x in channel.history(limit=None):
            d = {}
            if not public_attrs:
                public_attrs = [
                    x for x in dir(x)
                    if not x.startswith('_') and x not in cls_methods + ignore
                ]

            for attr in public_attrs:
                val = getattr(x, attr)
                if attr in regular_types:
                    val_content = val
                elif attr in ['author', 'channel', 'guild']:
                    # .name, .id (more details can be accessed through each key
                    #   in the global dict)
                    val_content = {'id': val.id, 'name': val.name}
                elif attr == 'edited_at':
                    val_content = str(val)
                elif attr in ['channel_mentions', 'mentions', 'role_mentions']:
                    # iterable; .name and .id
                    val_content = [{'id': v.id, 'name': v.name} for v in val]
                elif attr == 'attachments':
                    # iterable; .id, .filename, .url --> can be saved to bytes
                    #   object with .read()
                    val_content = []
                    for v in val:
                        if GET_DATA:
                            attachments_data = v.read()
                        else:
                            attachments_data = None
                        val_content.append({
                            'id': v.id,
                            'filename': v.filename,
                            'url': v.url,
                            'data': attachments_data
                        })
                elif attr == 'embeds':
                    # iterable; access .to_dict()
                    val_content = [v.to_dict() for v in val]
                elif attr == 'reference':
                    # .message_id, .channel_id, .guild_id,
                    #   cached_message.system_content: optional
                    if val:
                        val_content = {
                            attr: {
                                'message_id': val.message_id,
                                'channel_id': val.channel_id,
                                'guild_id': val.guild_id
                            }
                        }
                        if val.cached_message:
                            val_content.update({
                                'cached_message':
                                val.cached_message.system_content
                            })
                        else:
                            val_content.update(
                                {'cached_message': val.cached_message})
                    else:
                        val_content = None
                elif attr == 'reactions':
                    # iterable; .emoji, .is_custom_emoji, .me, .count. If
                    #   custom_emoji: [v.emoji.id, v.emoji.name,
                    #   v.emoji.animated, v.emoji.animated, v.emoji.managed]
                    val_content = []
                    for v in val:
                        if not hasattr(v, 'is_custom_emoji'):
                            # For compatibility with discord.py <= 1.7.3
                            is_custom_emoji = None
                        else:
                            is_custom_emoji = v.is_custom_emoji()

                        _d = {
                            'is_custom_emoji': is_custom_emoji,
                            'me': v.me,
                            'count': v.count
                        }
                        if isinstance(v.emoji, str):
                            _d.update({'emoji': v.emoji})
                        else:
                            if hasattr(v.emoji, 'managed'):
                                emoji_managed = v.emoji.managed
                            else:
                                emoji_managed = None
                            _d.update({
                                'emoji': {
                                    'id': v.emoji.id,
                                    'name': v.emoji.name,
                                    'animated': v.emoji.animated,
                                    'managed': emoji_managed
                                }
                            })
                        val_content.append(_d)
                elif attr == 'stickers':
                    # iterable; .name, .id, .url --> can be saved to bytes
                    #   object with .read()
                    val_content = []
                    if val:  # For compatibility with discord.py <= 1.7.3
                        for v in val:
                            if GET_DATA:
                                stickers_data = v.read()
                            else:
                                stickers_data = None
                            val_content.append({
                                'id': v.id,
                                'name': v.name,
                                'url': v.url,
                                'data': stickers_data
                            })
                elif attr in ['flags', 'type']:
                    # get all public attrs
                    val_content = {
                        k: getattr(val, k)
                        for k in dir(val) if not k.startswith('_')
                        if k not in ['count', 'index']
                    }
                else:
                    continue

                d.update({attr: val_content})

            history.append(d)

        history = {x['created_at']: x for x in history}

        history = dict(sorted(history.items()))
        history = {str(k): v for k, v in history.items()}
        for k, v in history.items():
            v['created_at'] = str(v['created_at'])
        return history

    @bot.command()
    @commands.has_permissions(administrator=True)
    async def backup(ctx, arg=None):
        logger.info(
            f'Backup requested from {ctx.author.name} in {ctx.guild.name}.',
            server_id=ctx.author.id,
            user_id=ctx.guild.id)

        clean_guild_name = re.sub(r'\W', '_', ctx.guild.name)

        if not arg:
            await ctx.send(
                '❌ Specify at least one channel, or `!backup all` to backup '
                'all channels.')
            return

        channel_id = None
        LEN_CHANNELS = len(ctx.guild.text_channels)
        if arg != 'all':
            if arg.isdigit():
                channel_id = int(arg)
            elif arg[2:-1].isdigit():
                channel_id = int(arg[2:-1])
            else:
                await ctx.send(f'❌ `{arg}` is not a valid channel!')
                return

            LEN_CHANNELS = 1

        LEN_MESSAGES = 0
        FINISHED_CHANNELS = 0

        global_start = time.time()
        success = []
        fail = []

        embed = discord.Embed(
            title='Backup Status',
            description='The status of the current backup process.',
            color=discord.Color.gold())
        embed.set_thumbnail(url='https://i.imgur.com/FCpL3hl.png')
        embed.insert_field_at(index=0,
                              name='Number of backed up channels:',
                              value=f'{FINISHED_CHANNELS}/{LEN_CHANNELS}',
                              inline=False)
        embed.insert_field_at(index=1,
                              name='Number of backed up messages (total):',
                              value=LEN_MESSAGES,
                              inline=False)
        embed.insert_field_at(
            index=2,
            name='Latest update:',
            value='Starting the backup process in 10 seconds... '
            'This might take several minutes/hours depending on how '
            'many messages are on the server/channel.',
            inline=False)
        status_message = await ctx.send(embed=embed)
        time.sleep(10)

        embed.set_field_at(index=2,
                           name='Latest update:',
                           value='Getting guild data...',
                           inline=False)

        SERVER = {'channels': {}}

        guild_dict = get_guild(ctx.guild)
        SERVER.update({'guild': guild_dict})

        embed.set_field_at(index=2,
                           name='Latest update:',
                           value='Getting members data...',
                           inline=False)

        members_dicts = await get_members(ctx.guild.fetch_members())
        SERVER.update({'members': members_dicts})

        for channel in ctx.guild.text_channels:
            if channel_id:
                if channel.id != channel_id:
                    continue
            start = time.time()
            try:
                channel_history = await backup_channel(channel)
            except discord.errors.Forbidden:
                FINISHED_CHANNELS += 1
                embed = update_embed(
                    embed, FINISHED_CHANNELS, LEN_CHANNELS, LEN_MESSAGES,
                    f'Could not access channel: [ {channel.name} ]! '
                    'Skipping!\nResuming in 5 seconds...')
                await status_message.edit(embed=embed)
                fail.append(channel.mention)
                time.sleep(5)
                continue

            FINISHED_CHANNELS += 1
            LEN_MESSAGES += len(channel_history)
            embed = update_embed(
                embed, FINISHED_CHANNELS, LEN_CHANNELS, LEN_MESSAGES,
                f'There were {len(channel_history)} messages in '
                f'{channel.mention} (took {round(time.time() - start, 2)}s).')

            await status_message.edit(embed=embed)
            success.append(channel.mention)

            SERVER['channels'].update({channel.id: channel_history})

        ts = datetime.now().strftime('%Y-%m-%d_%H.%M.%S')
        data_fname = f'{clean_guild_name}_data_{ts}.json.zip'

        uf = _UploadFile(SERVER, data_fname)
        data_obj = uf.get_compressed_file_object()
        if '--use-all-services' in sys.argv:
            presign_url = uf.upload_s3_object(data_obj)
            data_url = uf.shorten_url(presign_url)
        else:
            data_url = uf.fileio_upload(data_obj)

        embed = embed.insert_field_at(index=3,
                                      name='Data download link:',
                                      value=data_url,
                                      inline=False)

        await status_message.edit(embed=embed)

        if not fail:
            fail = ['None']

        embed = update_embed(
            embed, FINISHED_CHANNELS, LEN_CHANNELS, LEN_MESSAGES,
            f'Backup finished!\nSuccessfully backed up: '
            f'{", ".join(success)}\nFailed to backup the following channels: '
            f'{", ".join(fail)}\n'
            f'Took: {round(time.time() - global_start, 2)}s')
        await status_message.edit(embed=embed)

    token = os.getenv('BOT_TOKEN')
    bot.run(token)


if __name__ == '__main__':
    main()
