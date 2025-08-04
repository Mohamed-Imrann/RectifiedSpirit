import asyncio
import logging
from pyrogram import Client
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardButton
from info import REQ_CHANNEL_ONE, REQ_CHANNEL_TWO

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def create_request_forcesub_buttons(user_id: int):
    buttons = []
    
    if REQ_CHANNEL_ONE:
        try:
            channel_one_id = int(REQ_CHANNEL_ONE)
            async with Client("temp_client", bot_token=Client.BOT_TOKEN) as temp_client: # Use a temporary client instance
                user_status = await temp_client.get_chat_member(channel_one_id, user_id)
                if user_status.status in ["left", "kicked", "banned"]:
                    invite_link = await temp_client.create_chat_invite_link(channel_one_id)
                    buttons.append([InlineKeyboardButton("Channel 1", url=invite_link.invite_link)])
        except UserNotParticipant:
            try:
                async with Client("temp_client", bot_token=Client.BOT_TOKEN) as temp_client:
                    invite_link = await temp_client.create_chat_invite_link(channel_one_id)
                    buttons.append([InlineKeyboardButton("Channel 1", url=invite_link.invite_link)])
            except Exception as e:
                logger.error(f"Error creating invite link for REQ_CHANNEL_ONE: {e}")
        except Exception as e:
            logger.error(f"Error checking REQ_CHANNEL_ONE: {e}")

    if REQ_CHANNEL_TWO:
        try:
            channel_two_id = int(REQ_CHANNEL_TWO)
            async with Client("temp_client", bot_token=Client.BOT_TOKEN) as temp_client: # Use a temporary client instance
                user_status = await temp_client.get_chat_member(channel_two_id, user_id)
                if user_status.status in ["left", "kicked", "banned"]:
                    invite_link = await temp_client.create_chat_invite_link(channel_two_id)
                    buttons.append([InlineKeyboardButton("Channel 2", url=invite_link.invite_link)])
        except UserNotParticipant:
            try:
                async with Client("temp_client", bot_token=Client.BOT_TOKEN) as temp_client:
                    invite_link = await temp_client.create_chat_invite_link(channel_two_id)
                    buttons.append([InlineKeyboardButton("Channel 2", url=invite_link.invite_link)])
            except Exception as e:
                logger.error(f"Error creating invite link for REQ_CHANNEL_TWO: {e}")
        except Exception as e:
            logger.error(f"Error checking REQ_CHANNEL_TWO: {e}")
            
    return buttons if buttons else None
