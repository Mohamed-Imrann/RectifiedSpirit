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
from info import ADMINS, REQ_CHANNEL, AUTH_CHANNEL, LIMIT
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
    
     
    dbi = db()
    chat = await dbi.get_next_fsub_chat()
    if chat and LIMIT and (LIMIT <= await dbi.get_all_users_count()):
        await dbi.delete_fsub_chat(chat["chat_id"])
        is_req_fsub = await dbi.get_typeof_fsub()
        
        chat = await dbi.get_next_fsub_chat()
        if chat:
            auth_channel = chat["chat_id"]
            limit = chat["limit"]
            req_channel = False
            if is_req_fsub:
                req_channel = chat["chat_id"]
        else:
            auth_channel = False
            req_channel = False
            limit = None

        with open("./dynamic.env", "wt+") as f:
            f.write(f"AUTH_CHANNEL={auth_channel}\nREQ_CHANNEL={req_channel}\nLIMIT={limit}\n")
            
        logger.info("Limit threshold passed, Restarting...!")
        try:
            os.remove("TelegramBot.txt")
        except:
            pass
        os.execl(sys.executable, sys.executable, "bot.py")


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
