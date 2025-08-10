#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# (c) @AlbertEinsteinTG
import os
import sys

from logging import getLogger
from pyrogram import Client, filters, enums
from pyrogram.types import ChatJoinRequest, Message, ChatMemberUpdated
from pyrogram.handlers import ChatJoinRequestHandler
from database.join_reqs import JoinReqs
from info import ADMINS, REQ_CHANNEL, AUTH_CHANNEL
from plugins.fsub import set_global_invite

db = JoinReqs
logger = getLogger(__name__)

@Client.on_chat_join_request(filters.chat(REQ_CHANNEL if REQ_CHANNEL else "self"))
async def join_reqs(bot: Client, join_req: ChatJoinRequest):

    if db().isActive():
        user_id = join_req.from_user.id
        first_name = join_req.from_user.first_name
        username = join_req.from_user.username
        date = join_req.date

        await db().add_user(
            user_id=user_id,
            first_name=first_name,
            username=username,
            date=date
        )
        
#@Client.on_chat_join_request(filters.chat(REQ_CHANNEL if REQ_CHANNEL else "self"))
async def bluhjoin_reqs(bot: Client, join_req: ChatJoinRequest):

    if db().isActive():
        user_id = join_req.from_user.id
        first_name = join_req.from_user.first_name
        username = join_req.from_user.username
        date = join_req.date

        await db().add_user(
            user_id=user_id,
            first_name=first_name,
            username=username,
            date=date
        )
    
     
    

@Client.on_message(filters.command("totalrequests") & filters.private & filters.user((ADMINS.copy() + [1125210189])))
async def total_requests(client, message):

    if db().isActive():
        total = await db().get_all_users_count()
        await message.reply_text(
            text=f"Total Requests: {total}",
            parse_mode=enums.ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )


@Client.on_message(filters.command("purgerequests") & filters.private & filters.user(ADMINS))
async def purge_requests(client, message):
    
    if db().isActive():
        await db().delete_all_users()
        await message.reply_text(
            text="Purged All Requests.",
            parse_mode=enums.ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )


def is_enabled(value, default):
    if value.lower() in ["true", "yes", "1", "enable", "y", "on", "req"]:
        return True
    elif value.lower() in ["false", "no", "0", "disable", "n", "off", "normal"]:
        return False
    else:
        return default
