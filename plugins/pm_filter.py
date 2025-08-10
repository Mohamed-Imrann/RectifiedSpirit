#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import re
import logging
import random
from typing import Dict, Optional, List

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto
)
from info import SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG, ADMINS
from database.crazy_db import (
    get_series, get_series_by_key as get_series_name, get_poster_manuel
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
user_requestor: Dict[str, Optional[int]] = {}

# Helper functions
async def DeleteMessage(msg):
    await asyncio.sleep(temp.AUTO_DELETE_TIME)
    try:
        await msg.delete()
        logger.debug(f"Deleted message {msg.id} from chat {msg.chat.id}")
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")

def create_dynamic_layout(items, layout_pattern):
    """
    Create a dynamic button layout based on a pattern.
    
    Args:
        items: List of items to display
        layout_pattern: List of strings representing the layout pattern
                       Each string contains the type and position (e.g., "la1", "lb2", "sa3")
    
    Returns:
        List of lists of InlineKeyboardButton objects
    """
    # Create a dictionary to map layout codes to items
    item_dict = {}
    for i, item in enumerate(items, 1):
        item_dict[f"l{i}"] = item
    
    # Create the layout
    layout = []
    current_row = []
    
    for code in layout_pattern:
        if code in item_dict:
            current_row.append(InlineKeyboardButton(
                text=item_dict[code],
                callback_data=code
            ))
        
        # Add row to layout if it has 3 buttons or is the last item
        if len(current_row) == 3 or code == layout_pattern[-1]:
            if current_row:
                layout.append(current_row)
                current_row = []
    
    return layout

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    import difflib
    return difflib.get_close_matches(query, possibilities, n, cutoff)

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
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
            
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
    series_keys = [series['_id'] for series in series_infos]
    series_names = [series['title'] for series in series_infos]

    series_key = None
    
    # Try exact match by key first
    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
        logger.info(f"Found exact key match: {series_key}")
    else:
        # Try exact match by title
        for s_info in series_infos:
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
                    s_info = next((s for s in series_infos if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series:{s_info['_id']}"))
                
                if buttons:
                    # Define the layout pattern
                    layout_pattern = [f"la{i}" for i in range(1, len(buttons) + 1)]
                    layout = create_dynamic_layout(buttons, layout_pattern)
                    reply_markup = InlineKeyboardMarkup(layout)
                    
                    etho = await message.reply_photo(
                        photo=random.choice(SPELL_CHECK_IMAGE), 
                        caption="<b>Choose Your Series:</b>", 
                        reply_markup=reply_markup
                    )
                    reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                    asyncio.create_task(DeleteMessage(etho))
                    logger.info(f"Sent series selection message with {len(buttons)} options")
                    return
    
    if series_key:
        logger.info(f"Processing series with key: {series_key}")
        series = get_series_name(series_key)
        if not series:
            logger.warning(f"Series not found for key: {series_key}")
            return

        languages = series.get("languages", [])
        
        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n\n"
            "Select the language you need...!"
        )
        poster_url = get_movie_poster(series_key)
        
        buttons = []
        for lang_data in languages:
            buttons.append(lang_data['name'])
        
        # Define the layout pattern
        layout_pattern = [f"la{i}" for i in range(1, len(buttons) + 1)]
        layout = create_dynamic_layout(buttons, layout_pattern)
        reply_markup = InlineKeyboardMarkup(layout)
        
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
            else:
                etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=reply_text, reply_markup=reply_markup)
            
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
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

# Callback handlers
@Client.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Received callback query from user {user_id}: {data}")

    if data.startswith("user_series:") or data.startswith("b:"):
        logger.info(f"User series callback from user {user_id}")
        await user_series_callback_handler(client, callback_query)
        return

    # Handle dynamic layout callbacks
    elif data.startswith("la") or data.startswith("sa") or data.startswith("qa"):
        logger.info(f"Dynamic layout callback from user {user_id}")
        await dynamic_layout_callback_handler(client, callback_query)
        return

    logger.warning(f"Unknown callback type from user {user_id}: {data}")

async def user_series_callback_handler(client: Client, query: CallbackQuery):
    data = query.data
    parts = data.split(":")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id
    logger.info(f"Processing user series callback: {data}")

    reply_msg = query.message.reply_to_message  
    if reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    else:
        requested_user = user_requestor.get(f"{chat_id}•{message_id}")
    
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        logger.warning(f"User {clicked_user} tried to access another user's request")
        await query.answer("Not your request!", show_alert=True)
        return

    if data == "pages":
        await query.answer()
        return

    elif data.startswith("b:"):
        file_link_key = data.split(":", 1)[1]
        logger.info(f"Fetching files for link key: {file_link_key}")
        
        files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(file_link_key)

        if not files_to_send:
            logger.warning(f"No files found for link key: {file_link_key}")
            await query.answer("No files found for this quality.", show_alert=True)
            return

        await query.answer("Sending files...")
        
        track_msgs = []
        for entry in files_to_send:
            try:
                copied_msg = await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                    track_msgs.append(copied_msg)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error sending cached media to user {query.from_user.id}: {e}")
                await client.send_message(query.from_user.id, f"Error sending file: {e}")
                
        if track_msgs:
            delete_data = await client.send_message(
                chat_id=query.from_user.id,
                text=temp.AUTO_DELETE_MSG.format(time=temp.AUTO_DELETE_TIME)
            )
            asyncio.create_task(DeleteMessage(delete_data))
        return

    elif data.startswith("user_series:"):
        series_key = parts[1]
        logger.info(f"Processing series with key: {series_key}")
        series = get_series_name(series_key)
        if not series:
            logger.warning(f"Series not found for key: {series_key}")
            await query.message.edit_text("Series not found or deleted.", parse_mode=enums.ParseMode.HTML)
            return

        # Store series key in user_requestor for dynamic layout callbacks
        user_requestor[f"{chat_id}•{message_id}"] = {
            "series_key": series_key,
            "requested_user": requested_user
        }

        languages = series.get("languages", [])
        
        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
        )
        
        buttons = []
        for lang_data in languages:
            buttons.append(lang_data['name'])
        
        text = base_text + "\nSelect the language you need...!"
        
        # Define the layout pattern
        layout_pattern = [f"la{i}" for i in range(1, len(buttons) + 1)]
        layout = create_dynamic_layout(buttons, layout_pattern)
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
            await query.answer("An error occurred. Please try again.", show_alert=True)

async def dynamic_layout_callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id
    data = query.data
    logger.info(f"Processing dynamic layout callback: {data}")
    
    # Get stored data
    stored_data = user_requestor.get(f"{chat_id}•{message_id}")
    if not stored_data:
        await query.answer("Session expired. Please search again.", show_alert=True)
        return
    
    if isinstance(stored_data, dict):
        series_key = stored_data.get("series_key")
        requested_user = stored_data.get("requested_user")
    else:
        requested_user = stored_data
        # Find series_key from previous callbacks
        await query.answer("Session expired. Please search again.", show_alert=True)
        return
    
    # Check if user is authorized
    if chat_id < 0 and requested_user and user_id != requested_user:
        logger.warning(f"User {user_id} tried to access another user's request")
        await query.answer("Not your request!", show_alert=True)
        return
    
    series = get_series_name(series_key)
    if not series:
        await query.answer("Series not found.", show_alert=True)
        return
    
    base_text = (
        f"○ **Title:** `{series['title']}`\n"
        f"○ **Released On:** `{series['released_on']}`\n"
        f"○ **Genre:** `{series['genre']}`\n"
        f"○ **Rating:** `{series['rating']}`\n"
        f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
    )
    
    # Parse the callback data
    callback_type = data[0]  # l, s, or q
    callback_index = int(data[2:]) - 1  # Convert to 0-based index
    
    # Handle language selection (la)
    if callback_type == "l":
        languages = series.get("languages", [])
        
        if 0 <= callback_index < len(languages):
            language_name = languages[callback_index]["name"]
            await query.answer(f"Selected: {language_name}")
            
            # Update stored data
            user_requestor[f"{chat_id}•{message_id}"] = {
                "series_key": series_key,
                "language_name": language_name,
                "requested_user": requested_user
            }
            
            # Get seasons for this language
            seasons = languages[callback_index].get("seasons", [])
            buttons = []
            for season_data in seasons:
                buttons.append(season_data['name'])
            
            text = base_text + f"○ **Language:** `{language_name}`\n\nSelect the season you need...!"
            
            # Define the layout pattern
            layout_pattern = [f"sa{i}" for i in range(1, len(buttons) + 1)]
            layout = create_dynamic_layout(buttons, layout_pattern)
            reply_markup = InlineKeyboardMarkup(layout)
            
            try:
                await query.message.edit_text(
                    text=text,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Error editing message: {e}")
                await query.answer("An error occurred. Please try again.", show_alert=True)
        else:
            await query.answer("Invalid selection.", show_alert=True)
    
    # Handle season selection (sa)
    elif callback_type == "s":
        language_name = stored_data.get("language_name")
        lang_index = next((i for i, lang in enumerate(series.get("languages", [])) if lang["name"] == language_name), -1)
        
        if lang_index == -1:
            await query.answer("Language not found.", show_alert=True)
            return
        
        seasons = series.get("languages", [])[lang_index].get("seasons", [])
        
        if 0 <= callback_index < len(seasons):
            season_name = seasons[callback_index]["name"]
            await query.answer(f"Selected: {season_name}")
            
            # Update stored data
            user_requestor[f"{chat_id}•{message_id}"] = {
                "series_key": series_key,
                "language_name": language_name,
                "season_name": season_name,
                "requested_user": requested_user
            }
            
            # Get qualities for this season
            qualities = seasons[callback_index].get("qualities", [])
            buttons = []
            for quality_data in qualities:
                if quality_data.get("link_key"):
                    buttons.append(quality_data['name'])
            
            text = base_text + f"○ **Language:** `{language_name}`\n○ **Season:** `{season_name}`\n\nSelect the quality you need...!"
            
            # Define the layout pattern
            layout_pattern = [f"qa{i}" for i in range(1, len(buttons) + 1)]
            layout = create_dynamic_layout(buttons, layout_pattern)
            reply_markup = InlineKeyboardMarkup(layout)
            
            try:
                await query.message.edit_text(
                    text=text,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Error editing message: {e}")
                await query.answer("An error occurred. Please try again.", show_alert=True)
        else:
            await query.answer("Invalid selection.", show_alert=True)
    
    # Handle quality selection (qa)
    elif callback_type == "q":
        language_name = stored_data.get("language_name")
        season_name = stored_data.get("season_name")
        
        lang_index = next((i for i, lang in enumerate(series.get("languages", [])) if lang["name"] == language_name), -1)
        if lang_index == -1:
            await query.answer("Language not found.", show_alert=True)
            return
        
        season_index = next((i for i, season in enumerate(series.get("languages", [])[lang_index].get("seasons", [])) if season["name"] == season_name), -1)
        if season_index == -1:
            await query.answer("Season not found.", show_alert=True)
            return
        
        qualities = series.get("languages", [])[lang_index].get("seasons", [])[season_index].get("qualities", [])
        
        if 0 <= callback_index < len(qualities):
            quality_name = qualities[callback_index]["name"]
            link_key = qualities[callback_index].get("link_key")
            
            if not link_key:
                await query.answer("No files available for this quality.", show_alert=True)
                return
            
            await query.answer(f"Selected: {quality_name}")
            
            # Fetch and send files
            files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(link_key)

            if not files_to_send:
                await query.answer("No files found for this quality.", show_alert=True)
                return

            await query.answer("Sending files...")
            
            track_msgs = []
            for entry in files_to_send:
                try:
                    copied_msg = await client.send_cached_media(
                        chat_id=query.from_user.id, 
                        file_id=entry["file_id"],
                        caption=entry.get("caption", "")
                    )
                    if copied_msg and temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
                        track_msgs.append(copied_msg)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error sending cached media to user {query.from_user.id}: {e}")
                    await client.send_message(query.from_user.id, f"Error sending file: {e}")
                    
            if track_msgs:
                delete_data = await client.send_message(
                    chat_id=query.from_user.id,
                    text=temp.AUTO_DELETE_MSG.format(time=temp.AUTO_DELETE_TIME)
                )
                asyncio.create_task(DeleteMessage(delete_data))
        else:
            await query.answer("Invalid selection.", show_alert=True)
