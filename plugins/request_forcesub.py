import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.request_forcesub_db import is_requested_one, is_requested_two, add_req_one, add_req_two
from info import REQ_CHANNEL_ONE, REQ_CHANNEL_TWO
from utils import temp

@Client.on_message(filters.private & filters.incoming & ~filters.service & ~filters.edited & ~filters.command(["start", "help", "about", "stats", "restart", "totalusers", "viewall", "deleteseries", "deleteallseries", "gfilters", "gdel", "gdelall", "genlink", "get_file_id", "admin_ui"]))
async def check_force_subscribe(client, message: Message):
    if REQ_CHANNEL_ONE and not await is_requested_one(message.from_user.id):
        await message.reply_text(
            "You must join our channel to use this bot.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=temp.LINK_ONE)]
            ])
        )
        return
    
    if REQ_CHANNEL_TWO and not await is_requested_two(message.from_user.id):
        await message.reply_text(
            "You must join our second channel to use this bot.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=temp.LINK_TWO)]
            ])
        )
        return
    
    # If both checks pass, or no channels are configured, proceed with the message
    # This function is meant to be a pre-filter. Actual message processing happens elsewhere.
    pass
