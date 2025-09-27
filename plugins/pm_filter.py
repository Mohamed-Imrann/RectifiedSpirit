#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import re
import logging
import random
import time
from typing import Dict, Optional, List

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto
)
from info import SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG, ADMINS
from database.crazy_db import (
    get_series, get_series_name, get_poster_manuel
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import temp, get_links_for_quality
from fuzzywuzzy import fuzz
from pyrogram.errors import MessageNotModified

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables
user_requestor: Dict[str, Dict] = {}  # Modified to store more complex data
request_timestamps: Dict[str, float] = {}  # Track when requests were made

# Helper functions
async def DeleteMessage(msg):
    await asyncio.sleep(temp.AUTO_DELETE_TIME)
    try:
        await msg.delete()
        logger.debug(f"Deleted message {msg.id} from chat {msg.chat.id}")
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")

async def clean_expired_requests():
    """Clean up user_requestor entries older than 30 minutes"""
    while True:
        await asyncio.sleep(600)  # Check every 10 minutes
        current_time = time.time()
        expired_keys = []
        
        for key, timestamp in request_timestamps.items():
            if current_time - timestamp > 1800:  # 30 minutes in seconds
                expired_keys.append(key)
        
        for key in expired_keys:
            if key in user_requestor:
                del user_requestor[key]
            if key in request_timestamps:
                del request_timestamps[key]
        
        if expired_keys:
            logger.info(f"Cleaned {len(expired_keys)} expired requests")

def create_user_layout_from_pattern(items: List[str], layout_pattern: List[int], callback_prefix: str = "user_item", add_back_button: bool = False, back_target: str = "") -> List[List[InlineKeyboardButton]]:
    """
    Create a user-facing layout without + buttons using saved layout pattern.
    
    Args:
        items: List of item names
        layout_pattern: List of integers representing buttons per row
        callback_prefix: Prefix for callback data
        add_back_button: Whether to add a back button
        back_target: Target for the back button (e.g., "language", "season")
    
    Returns:
        List of lists of InlineKeyboardButton objects
    """
    if not items:
        return []
    
    layout = []
    item_index = 0
    
    # Use saved layout pattern
    for row_count in layout_pattern:
        if item_index >= len(items):
            break
        
        row = []
        for _ in range(row_count):
            if item_index < len(items):
                item_button = InlineKeyboardButton(
                    items[item_index], 
                    callback_data=f"{callback_prefix}_{item_index}"
                )
                row.append(item_button)
                item_index += 1
        
        if row:
            layout.append(row)
    
    # Add remaining items if any (fallback)
    while item_index < len(items):
        row = []
        for _ in range(min(2, len(items) - item_index)):  # Max 2 per row for remaining
            item_button = InlineKeyboardButton(
                items[item_index], 
                callback_data=f"{callback_prefix}_{item_index}"
            )
            row.append(item_button)
            item_index += 1
        if row:
            layout.append(row)
    
    # Add back button if requested
    if add_back_button:
        back_button = InlineKeyboardButton("⬅️ Back", callback_data=f"back_{back_target}")
        layout.append([back_button])
    
    return layout

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    import difflib
    return difflib.get_close_matches(query, possibilities, n, cutoff)

async def get_links_for_quality(client: Client, file_link_key: str):
    """
    Retrieves file information based on a file_link_key.
    This function now handles the new format (get_channelid_firstmsgid_lastmsgid).
    
    Args:
        client: Pyrogram client instance
        file_link_key: The key linking to the files (reference string)
        
    Returns:
        tuple: A tuple containing:
            - list: A list of dictionaries, each containing 'file_id' and 'caption' for the media.
            - int: Channel ID
            - int: First message ID
            - int: Last message ID
    """
    logger.info(f"Fetching file links for key: {file_link_key}")
    
    # Check if it's the new format (get_channelid_firstmsgid_lastmsgid)
    if file_link_key.startswith("get_"):
        try:
            # Parse the reference string
            parts = file_link_key.split('_')
            if len(parts) != 4:
                logger.error(f"Invalid reference string format: {file_link_key}")
                return [], 0, 0, 0
            
            channel_id = int(parts[1])
            first_msg_id = int(parts[2])
            last_msg_id = int(parts[3])
            
            # Get the messages from the channel
            messages = await client.get_messages(
                chat_id=channel_id,
                message_ids=list(range(first_msg_id, last_msg_id + 1))
            )
            
            if not messages:
                logger.warning(f"No messages found for reference key: {file_link_key}")
                return [], 0, 0, 0
            
            # Extract file information
            files_to_send = []
            for msg in messages:
                file_info = get_file_id(msg)
                if file_info:
                    files_to_send.append({
                        "file_id": file_info.file_id,
                        "caption": msg.caption or ""
                    })
            
            logger.info(f"Found {len(files_to_send)} files for reference key {file_link_key}")
            return files_to_send, channel_id, first_msg_id, last_msg_id
        except Exception as e:
            logger.error(f"Error processing reference key {file_link_key}: {e}")
            return [], 0, 0, 0
    else:
        # Old format: get from episodes_collection
        episode_doc = episodes_collection.find_one({"file_link_key": file_link_key})
        if episode_doc and episode_doc.get("files"):
            logger.info(f"Found {len(episode_doc['files'])} files for link key {file_link_key} in episodes_collection")
            return (
                episode_doc["files"],
                episode_doc.get("channel_id", 0),
                episode_doc.get("first_msg_id", 0),
                episode_doc.get("last_msg_id", 0)
            )
        logger.warning(f"No files found in episodes_collection for link key: {file_link_key}")
        return [], 0, 0, 0
        
def get_movie_poster(series_key):
    poster_file_id = get_poster_manuel(series_key)
    return poster_file_id or NO_POSTER_FOUND_IMG[0]

# Global filter function
async def global_filters(client: Client, message: Message, text=False) -> bool:
    logger.info(f"Applying global filters to message {message.id} from user {message.from_user.id}")
    group_id = message.chat.id
    name = text or message.text 
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
    keywords = await get_gfilters("gfilters")

    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\W])" + re.escape(keyword) + r"( |$|[\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            logger.info(f"Global filter matched keyword: {keyword}")
            reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "").replace("\\t", "\t")
            
            try:
                if fileid == "None":
                    if btn == "[]":
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                elif btn == "[]":
                    piroxrk = await client.send_cached_media(
                        group_id,
                        fileid,
                        caption=reply_text or "",
                        reply_to_message_id=reply_id
                    )
                else:
                    button = eval(btn)
                    piroxrk = await message.reply_cached_media(
                        fileid,
                        caption=reply_text or "",
                        reply_markup=InlineKeyboardMarkup(button),
                        reply_to_message_id=reply_id
                    )
                logger.info(f"Successfully sent global filter response for keyword: {keyword}")
                return True
            except Exception as e:
                logger.exception(f"Error in global filter for keyword {keyword}: {e}")
    logger.info("No global filters matched")
    return False

# Series filter function
async def series_filter(client: Client, message: Message):
    logger.info(f"Applying series filter to message {message.id} from user {message.from_user.id}")
    text = message.text.strip()
    series_infos = get_series()
    
    # Filter only published series for users
    published_series = [s for s in series_infos if s.get('published', False)]
    
    series_keys = [series['_id'] for series in published_series]
    series_names = [series['title'] for series in published_series]

    series_key = None
    
    # Try exact match by key first
    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
        logger.info(f"Found exact key match: {series_key}")
    else:
        # Try exact match by title
        for s_info in published_series:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['_id']
                logger.info(f"Found exact title match: {series_key}")
                break
        
        if not series_key:
            # Try close matches for titles
            close_matches = find_close_matches(text, series_names)
            if not close_matches:
                # Fallback to starts-with if no close matches
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]
            
            if close_matches:
                logger.info(f"Found {len(close_matches)} close matches: {close_matches}")
                buttons = []
                for match in close_matches:
                    s_info = next((s for s in published_series if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series:{s_info['_id']}"))
                
                if buttons:
                    # Create simple layout for selection (1 button per row)
                    layout = [[button] for button in buttons]
                    reply_markup = InlineKeyboardMarkup(layout)
                    
                    etho = await message.reply_photo(
                        photo=random.choice(SPELL_CHECK_IMAGE), 
                        caption="<b>Choose Your Series:</b>", 
                        reply_markup=reply_markup
                    )
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = {
                        "data": reply_etho_user_id,
                        "timestamp": time.time()
                    }
                    request_timestamps[f"{etho.chat.id}•{etho.id}"] = time.time()
                    asyncio.create_task(DeleteMessage(etho))
                    logger.info(f"Sent series selection message with {len(buttons)} options")
                    return
    
    if series_key:
        logger.info(f"Processing series with key: {series_key}")
        series = get_series_name(series_key)
        if not series or not series.get('published', False):
            logger.warning(f"Series not found or not published for key: {series_key}")
            return

        languages = series.get("languages", [])
        language_layout = series.get("language_layout", [1] * len(languages))
        
        reply_text = (
            f"○ **Title:** `{series['title']}`"
            f"○ **Released On:** `{series['released_on']}`"
            f"○ **Genre:** `{series['genre']}`"
            f"○ **Rating:** `{series['rating']}`"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`"
            "Select the language you need...!"
        )
        poster_url = get_movie_poster(series_key)
        
        # Get language names
        language_names = [lang['name'] for lang in languages]
        
        # Create user layout using saved pattern
        layout = create_user_layout_from_pattern(language_names, language_layout, "lang")
        
        if not layout:
            # Fallback if no languages
            await message.reply("No languages available for this series.")
            return
        
        reply_markup = InlineKeyboardMarkup(layout)
        
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
            else:
                etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = {
                "data": {
                    "series_key": series_key,
                    "requested_user": reply_etho_user_id
                },
                "timestamp": time.time()
            }
            request_timestamps[f"{etho.chat.id}•{etho.id}"] = time.time()
            asyncio.create_task(DeleteMessage(etho))
            logger.info(f"Sent series filter response for {series['title']}")
        except Exception as e:
            logger.error(f"Error sending series filter message: {e}")

# Message handlers
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Client, message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"Received text message {message.id} from user {user_id} in chat {chat_id}")
    
    if message.chat.type != enums.ChatType.PRIVATE:
        logger.info(f"Message is in group {chat_id}, applying filters")
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)
        return
    
    if user_id not in ADMINS:
        logger.info(f"Applying filters for user {user_id}")
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)

# Start the cleanup scheduler when the bot starts
async def start_scheduler():
    asyncio.create_task(clean_expired_requests())

# Callback handlers
@Client.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Received callback query from user {user_id}: {data}")

    if data.startswith("b:"):
        start_parameter = data.split(":", 1)[1]
        try:
            test_string = f"https://t.me/{temp.U_NAME}?start={start_parameter}"
            print(test_string)
            await callback_query.answer(url=f"https://t.me/{temp.U_NAME}?start={start_parameter}")
        except Exception as e:
            logger.error(f"Error in b: callback: {e}")
            await callback_query.answer("Invalid URL provided.", show_alert=True)
        return

    if data.startswith("user_series:"):
        logger.info(f"User series callback from user {user_id}")
        await user_series_callback_handler(client, callback_query)
        return

    # Handle user interface callbacks
    elif data.startswith("lang_") or data.startswith("season_") or data.startswith("quality_") or data.startswith("back_"):
        logger.info(f"User interface callback from user {user_id}")
        await user_interface_callback_handler(client, callback_query)
        return

    logger.warning(f"Unknown callback type from user {user_id}: {data}")

async def user_series_callback_handler(client: Client, query: CallbackQuery):
    data = query.data
    parts = data.split(":")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id
    logger.info(f"Processing user series callback: {data}")

    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Failed to acknowledge callback: {e}")

    reply_msg = query.message.reply_to_message  
    if reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    else:
        stored_data = user_requestor.get(f"{chat_id}•{message_id}", {}).get("data")
        if isinstance(stored_data, dict):
            requested_user = stored_data.get("requested_user")
        else:
            requested_user = stored_data
    
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        logger.warning(f"User {clicked_user} tried to access another user's request")
        try:
            await query.answer("Not your request!", show_alert=True)
        except:
            pass
        return

    if data == "pages":
        return

    elif data.startswith("user_series:"):
        series_key = parts[1]
        logger.info(f"Processing series with key: {series_key}")
        series = get_series_name(series_key)
        if not series or not series.get('published', False):
            logger.warning(f"Series not found or not published for key: {series_key}")
            try:
                await query.message.edit_text("Series not found or not available.", parse_mode=enums.ParseMode.HTML)
            except Exception as e:
                logger.error(f"Failed to edit message: {e}")
            return

        # Store series key in user_requestor for future callbacks
        user_requestor[f"{chat_id}•{message_id}"] = {
            "data": {
                "series_key": series_key,
                "requested_user": clicked_user
            },
            "timestamp": time.time()
        }
        request_timestamps[f"{chat_id}•{message_id}"] = time.time()

        languages = series.get("languages", [])
        language_layout = series.get("language_layout", [1] * len(languages))
        
        base_text = (
            f"○ **Title:** `{series['title']}`"
            f"○ **Released On:** `{series['released_on']}`"
            f"○ **Genre:** `{series['genre']}`"
            f"○ **Rating:** `{series['rating']}`"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`"
        )
        
        # Get language names
        language_names = [lang['name'] for lang in languages]
        
        text = base_text + "
Select the language you need...!"
        
        # Create user layout using saved pattern
        layout = create_user_layout_from_pattern(language_names, language_layout, "lang")
        
        if not layout:
            try:
                await query.message.edit_text("No languages available for this series.")
            except Exception as e:
                logger.error(f"Failed to edit message: {e}")
            return
        
        reply_markup = InlineKeyboardMarkup(layout)

        try:
            await query.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Updated user series message for {series['title']}")
        except MessageNotModified:
            logger.debug("Message not modified, likely no changes")
        except Exception as e:
            logger.error(f"Error editing message in user_series callback: {e}")
            try:
                await query.answer("An error occurred. Please try again.", show_alert=True)
            except:
                pass

async def user_interface_callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id
    data = query.data
    logger.info(f"Processing user interface callback: {data}")
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Failed to acknowledge callback: {e}")
    
    # Get stored data
    stored_entry = user_requestor.get(f"{chat_id}•{message_id}", {})
    stored_data = stored_entry.get("data") if isinstance(stored_entry, dict) else None
    
    if not stored_data or not isinstance(stored_data, dict):
        try:
            await query.answer("Session expired. Please search again.", show_alert=True)
        except:
            pass
        return
    
    series_key = stored_data.get("series_key")
    requested_user = stored_data.get("requested_user")
    
    # Check if user is authorized
    if chat_id < 0 and requested_user and user_id != requested_user:
        logger.warning(f"User {user_id} tried to access another user's request")
        try:
            await query.answer("Not your request!", show_alert=True)
        except:
            pass
        return
    
    series = get_series_name(series_key)
    if not series or not series.get('published', False):
        try:
            await query.answer("Series not found or not available.", show_alert=True)
        except:
            pass
        return
    
    base_text = (
        f"○ **Title:** `{series['title']}`"
        f"○ **Released On:** `{series['released_on']}`"
        f"○ **Genre:** `{series['genre']}`"
        f"○ **Rating:** `{series['rating']}`"
        f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`"
    )
    
    # Handle back button
    if data.startswith("back_"):
        target = data.split("_")[1]
        
        if target == "language":
            # Go back to language selection
            languages = series.get("languages", [])
            language_layout = series.get("language_layout", [1] * len(languages))
            language_names = [lang['name'] for lang in languages]
            
            text = base_text + "
Select the language you need...!"
            
            # Create user layout using saved pattern
            layout = create_user_layout_from_pattern(language_names, language_layout, "lang")
            
            if not layout:
                try:
                    await query.answer("No languages available for this series.", show_alert=True)
                except:
                    pass
                return
            
            reply_markup = InlineKeyboardMarkup(layout)
            
            try:
                await query.message.edit_text(
                    text=text,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.MARKDOWN
                )
                logger.debug(f"Returned to language selection for {series['title']}")
            except Exception as e:
                logger.error(f"Error editing message: {e}")
                try:
                    await query.answer("An error occurred. Please try again.", show_alert=True)
                except:
                    pass
            return
        
        elif target == "season":
            # Go back to season selection
            language_index = stored_data.get("language_index")
            language_name = stored_data.get("language_name")
            
            if language_index is None:
                try:
                    await query.answer("Session error. Please start again.", show_alert=True)
                except:
                    pass
                return
            
            languages = series.get("languages", [])
            if language_index >= len(languages):
                try:
                    await query.answer("Language not found.", show_alert=True)
                except:
                    pass
                return
            
         
