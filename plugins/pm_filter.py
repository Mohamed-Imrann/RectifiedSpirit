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
user_requestor: Dict[str, Optional[int]] = {}

# Helper functions
async def DeleteMessage(msg):
    await asyncio.sleep(temp.AUTO_DELETE_TIME)
    try:
        await msg.delete()
        logger.debug(f"Deleted message {msg.id} from chat {msg.chat.id}")
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")

def create_user_layout_from_pattern(items: List[str], layout_pattern: List[int], callback_prefix: str = "user_item") -> List[List[InlineKeyboardButton]]:
    """
    Create a user-facing layout without + buttons using saved layout pattern.
    
    Args:
        items: List of item names
        layout_pattern: List of integers representing buttons per row
        callback_prefix: Prefix for callback data
    
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
                    user_requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
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
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n\n"
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
                "series_key": series_key,
                "requested_user": reply_etho_user_id
            }
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

    # Handle user interface callbacks
    elif data.startswith("lang_") or data.startswith("season_") or data.startswith("quality_"):
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

    # Determine who requested the menu (reply-to-user or stored requester)
    reply_msg = query.message.reply_to_message
    if reply_msg and getattr(reply_msg, "from_user", None):
        requested_user = reply_msg.from_user.id
    else:
        requested_user = user_requestor.get(f"{chat_id}•{message_id}")

    # If in a group, block others from using the buttons
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        await query.answer("Not your request!", show_alert=True)
        return

    # quick passthrough
    if data == "pages":
        await query.answer()
        return

    # Final quality link -> send files to user
    if data.startswith("b:"):
        file_link_key = data.split(":", 1)[1]
        files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(file_link_key)
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
        return

    # Handle the hierarchical user_series menus (series -> language -> season -> quality)
    if data.startswith("user_series:"):
        # parts: ["user_series", series_key, maybe language, maybe season, maybe quality]
        series_key = parts[1]
        lang_name_from_callback = parts[2] if len(parts) > 2 else None
        season_name_from_callback = parts[3] if len(parts) > 3 else None
        quality_name_from_callback = parts[4] if len(parts) > 4 else None

        series = get_series_name(series_key)
        if not series or not series.get('published', False):
            await query.message.edit_text("Series not found or not available.", parse_mode=enums.ParseMode.HTML)
            return

        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
        )

        buttons = []
        back_callback = None

        # 1) Show languages
        if not lang_name_from_callback:
            languages = series.get("languages", [])
            for lang_data in languages:
                buttons.append(InlineKeyboardButton(lang_data['name'],
                                                    callback_data=f"user_series:{series_key}:{lang_data['name']}"))
            text = base_text + "\nSelect the language you need...!"

        # 2) Show seasons for selected language
        elif not season_name_from_callback:
            current_lang = next((lang for lang in series.get("languages", []) if lang["name"] == lang_name_from_callback), None)
            if current_lang:
                seasons = current_lang.get("seasons", [])
                for season_data in seasons:
                    buttons.append(InlineKeyboardButton(season_data['name'],
                                                        callback_data=f"user_series:{series_key}:{lang_name_from_callback}:{season_data['name']}"))
            text = base_text + f"○ **Language:** `{lang_name_from_callback}`\n\nSelect the season you need...!"
            back_callback = f"user_series:{series_key}"  # Back to languages

        # 3) Show qualities for selected season
        elif not quality_name_from_callback:
            current_lang = next((lang for lang in series.get("languages", []) if lang["name"] == lang_name_from_callback), None)
            current_season = next((s for s in current_lang.get("seasons", []) if s["name"] == season_name_from_callback), None) if current_lang else None
            if current_season:
                qualities = current_season.get("qualities", [])
                for quality_data in qualities:
                    file_link_key = quality_data.get('link_key')
                    if file_link_key:
                        buttons.append(InlineKeyboardButton(quality_data['name'], callback_data=f"b:{file_link_key}"))
            text = base_text + f"○ **Language:** `{lang_name_from_callback}`\n○ **Season:** `{season_name_from_callback}`\n\nSelect the quality you need.!"
            back_callback = f"user_series:{series_key}:{lang_name_from_callback}"  # Back to seasons

        # chunk rows (uses your chunk_buttons helper)
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)

        # Append a Back button when appropriate (labelled with arrow)
        if back_callback:
            buttons_chunked.append([InlineKeyboardButton("⬅️ Back", callback_data=back_callback)])

        reply_markup = InlineKeyboardMarkup(buttons_chunked)

        try:
            await query.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Updated user series message for {series['title']}")
        except MessageNotModified:
            logger.debug("Message not modified (no changes)")
        except Exception as e:
            logger.error(f"Error editing message in user_series callback: {e}")
            await query.answer("An error occurred. Please try again.", show_alert=True)
            
async def user_interface_callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id
    data = query.data
    logger.info(f"Processing user interface callback: {data}")
    
    # Get stored data
    stored_data = user_requestor.get(f"{chat_id}•{message_id}")
    if not stored_data or not isinstance(stored_data, dict):
        await query.answer("Session expired. Please search again.", show_alert=True)
        return
    
    series_key = stored_data.get("series_key")
    requested_user = stored_data.get("requested_user")
    
    # Check if user is authorized
    if chat_id < 0 and requested_user and user_id != requested_user:
        logger.warning(f"User {user_id} tried to access another user's request")
        await query.answer("Not your request!", show_alert=True)
        return
    
    series = get_series_name(series_key)
    if not series or not series.get('published', False):
        await query.answer("Series not found or not available.", show_alert=True)
        return
    
    base_text = (
        f"○ **Title:** `{series['title']}`\n"
        f"○ **Released On:** `{series['released_on']}`\n"
        f"○ **Genre:** `{series['genre']}`\n"
        f"○ **Rating:** `{series['rating']}`\n"
        f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
    )
    
    # Parse the callback data
    callback_parts = data.split("_")
    callback_type = callback_parts[0]  # lang, season, or quality
    callback_index = int(callback_parts[1])  # Index
    
    # Handle language selection
    if callback_type == "lang":
        languages = series.get("languages", [])
        
        if 0 <= callback_index < len(languages):
            language_name = languages[callback_index]["name"]
            await query.answer(f"Selected: {language_name}")
            
            # Update stored data
            user_requestor[f"{chat_id}•{message_id}"] = {
                "series_key": series_key,
                "language_name": language_name,
                "language_index": callback_index,
                "requested_user": requested_user
            }
            
            # Get seasons for this language
            seasons = languages[callback_index].get("seasons", [])
            season_layout = languages[callback_index].get("season_layout", [1] * len(seasons))
            season_names = [season['name'] for season in seasons]
            
            text = base_text + f"○ **Language:** `{language_name}`\n\nSelect the season you need...!"
            
            # Create user layout using saved pattern
            layout = create_user_layout_from_pattern(season_names, season_layout, "season")
            
            if not layout:
                await query.answer("No seasons available for this language.", show_alert=True)
                return
            
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
    
    # Handle season selection
    elif callback_type == "season":
        language_index = stored_data.get("language_index")
        
        if language_index is None:
            await query.answer("Session error. Please start again.", show_alert=True)
            return
        
        languages = series.get("languages", [])
        if language_index >= len(languages):
            await query.answer("Language not found.", show_alert=True)
            return
        
        seasons = languages[language_index].get("seasons", [])
        
        if 0 <= callback_index < len(seasons):
            season_name = seasons[callback_index]["name"]
            await query.answer(f"Selected: {season_name}")
            
            # Update stored data
            user_requestor[f"{chat_id}•{message_id}"] = {
                "series_key": series_key,
                "language_name": stored_data.get("language_name"),
                "language_index": language_index,
                "season_name": season_name,
                "season_index": callback_index,
                "requested_user": requested_user
            }
            
            # Get qualities for this season
            qualities = seasons[callback_index].get("qualities", [])
            quality_layout = seasons[callback_index].get("quality_layout", [1] * len(qualities))
            
            # Filter qualities that have files
            available_qualities = []
            available_quality_names = []
            for quality in qualities:
                if quality.get("link_key"):
                    available_qualities.append(quality)
                    available_quality_names.append(quality['name'])
            
            text = base_text + f"○ **Language:** `{stored_data.get('language_name')}`\n○ **Season:** `{season_name}`\n\nSelect the quality you need...!"
            
            # Create user layout using saved pattern
            layout = create_user_layout_from_pattern(available_quality_names, quality_layout, "quality")
            
            if not layout:
                await query.answer("No qualities available for this season.", show_alert=True)
                return
            
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
    
    # Handle quality selection
    elif callback_type == "quality":
        language_index = stored_data.get("language_index")
        season_index = stored_data.get("season_index")
        
        if language_index is None or season_index is None:
            await query.answer("Session error. Please start again.", show_alert=True)
            return
        
        languages = series.get("languages", [])
        if language_index >= len(languages):
            await query.answer("Language not found.", show_alert=True)
            return
        
        seasons = languages[language_index].get("seasons", [])
        if season_index >= len(seasons):
            await query.answer("Season not found.", show_alert=True)
            return
        
        qualities = seasons[season_index].get("qualities", [])
        
        # Filter available qualities (those with link_key)
        available_qualities = [q for q in qualities if q.get("link_key")]
        
        if 0 <= callback_index < len(available_qualities):
            quality_name = available_qualities[callback_index]["name"]
            link_key = available_qualities[callback_index].get("link_key")
            
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
