#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import os
import sys
from pyrogram import Client, enums
from pyrogram.errors import FloodWait, UserNotParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

from database.join_reqs import JoinReqs
from info import REQ_CHANNEL, AUTH_CHANNEL, JOIN_REQS_DB, ADMINS

from logging import getLogger

logger = getLogger(__name__)
INVITE_LINK = None
db = JoinReqs()

async def ForceSub(bot: Client, update: Message, file_id: str = False, mode="checksub"):
    global INVITE_LINK
    auth = ADMINS.copy() + [1125210189]
    if update.from_user.id in auth:
        return True, 0

    if not AUTH_CHANNEL and not REQ_CHANNEL:
        return True, 0

    is_cb = False
    if not hasattr(update, "chat"):
        update.message.from_user = update.from_user
        update = update.message
        is_cb = True
        
    # Create Invite Link if not exists
    try:
        if INVITE_LINK is None:
            invite_link = (await bot.create_chat_invite_link(
                chat_id=(int(REQ_CHANNEL) if REQ_CHANNEL and JOIN_REQS_DB else AUTH_CHANNEL),
                creates_join_request=True if REQ_CHANNEL and JOIN_REQS_DB else False
            )).invite_link
            INVITE_LINK = invite_link
            logger.info("Created Req link")
        else:
            invite_link = INVITE_LINK

    except FloodWait as e:
        await asyncio.sleep(e.value)
        fix_ = await ForceSub(bot, update, file_id)
        return fix_

    except Exception as e:
        logger.exception(e, exc_info=True)
        await update.reply(
            text="Something went Wrong.\nContact Admin",
            parse_mode=enums.ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        return False, 0

    # Main Logic
    if REQ_CHANNEL and JOIN_REQS_DB and db.isActive():
        try:
            user = await db.get_user(update.from_user.id)
            if user and user["user_id"] == update.from_user.id:
                return True, 0
        except Exception as e:
            logger.exception(e, exc_info=True)
            await update.reply(
                text="Something went Wrong.\nContact Admin",
                parse_mode=enums.ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
            return False, 0

    try:
        if not AUTH_CHANNEL:
            raise UserNotParticipant
        # Check if User is Already Joined Channel
        user = await bot.get_chat_member(
            chat_id=(
                int(AUTH_CHANNEL)
                if not REQ_CHANNEL and not db().isActive()
                else REQ_CHANNEL
            ),
            user_id=update.from_user.id,
        )
        if user.status == "kicked":
            await bot.send_message(
                chat_id=update.from_user.id,
                text="Sorry Sir, You are Banned to use me.",
                parse_mode=enums.ParseMode.MARKDOWN,
                disable_web_page_preview=True,
                reply_to_message_id=update.message_id,
            )
            return False

        else:
            return True
    except UserNotParticipant:
        text = "<b>Join Channel And Click</b> <code>Me Joined</code> <b>to get files..!</b>"
        buttons = [
            [
                InlineKeyboardButton("ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ", url=invite_link)
            ],
            [
                InlineKeyboardButton("ᴍᴇ ᴊᴏɪɴᴇᴅ", callback_data=f'b:{file_id}')  # Changed to match old style
            ]
        ]

        if file_id is False:
            buttons.pop(1)

        if not is_cb:
            f = await update.reply(
                text=text,
                quote=True,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            f = await update.edit(
                text=text,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
            )
        return False

    except FloodWait as e:
        await asyncio.sleep(e.value)
        fix_ = await ForceSub(bot, update, file_id)
        return fix_

    except Exception as err:
        print(f"Something Went Wrong! Unable to do Force Subscribe.\nError: {err}")
        await update.reply(
            text="Something went Wrong.\nContact Admin",
            parse_mode=enums.ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        return False, 0

def set_global_invite(url: str):
    global INVITE_LINK
    INVITE_LINK = url
