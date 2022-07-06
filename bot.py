#!/usr/bin/env python
# coding: utf-8

import io
import json
import os
import re
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import discord
import requests
from discord.ext import commands  # noqa: F401
from dotenv import load_dotenv
from minio import Minio


class _UploadFile:

    def __init__(self, raw_data, object_name):
        self.raw_data = raw_data
        self.object_name = object_name

    def get_compressed_file_object(self):
        with tempfile.NamedTemporaryFile(suffix='.zip') as f:
            with zipfile.ZipFile(f, mode='w') as zf:
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
        object = client.put_object(os.getenv('S3_BUCKET_NAME'),
                                   self.object_name,
                                   object_data,
                                   object_data.getbuffer().nbytes,
                                   content_type='application/zip')
        presigned_url = client.presigned_get_object(object.bucket_name,
                                                    object.object_name)
        return presigned_url

    def shorten_url(self, long_url):
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
    GET_DATA = False  # todo; if true, can only export as pickle.

    load_dotenv()
    intents = discord.Intents.default()
    try:
        intents.message_content = True
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

    async def backup_channel(channel):
        regular_types = [
            'activity', 'application', 'clean_content', 'content', 'id',
            'jump_url', 'mention_everyone', 'pinned', 'system_content', 'tts',
            'webhook_id', 'raw_channel_mentions', 'raw_mentions',
            'raw_role_mentions'
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
                elif attr in ['created_at', 'edited_at']:
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
        return history

    @bot.command()
    @commands.has_permissions(administrator=True)
    async def backup(ctx, arg=None):
        clean_guild_name = re.sub(r'\W', '_', ctx.guild.name)
        data_dict = {'channels': {}}

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
            description='The status of the current backup process...',
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

            data_dict['channels'].update({channel.id: channel_history})

        ts = datetime.now().strftime('%Y-%m-%d_%H.%M.%S')
        data_fname = f'{clean_guild_name}_data_{ts}.json.zip'

        uf = _UploadFile(data_dict, data_fname)
        data_obj = uf.get_compressed_file_object()
        if '--use-all-services' in sys.argv:
            presign_url = uf.upload_s3_object(data_obj)
            data_url = uf.shorten_url(presign_url)
        else:
            data_url = uf.fileio_upload(data_obj)

        ebed = embed.insert_field_at(index=3,
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
