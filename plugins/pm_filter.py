#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import re
import logging
import random
from typing import Dict, Optional

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from info import SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG
from database.crazy_db import get_series_name, get_links_for_quality
from database.gfilters_mdb import find_gfilter, get_gfilters
from utils import temp

logger = logging.getLogger(__name__)

user_requestor: Dict[str, Optional[int]] = {}

async def DeleteMessage(msg):
    """Delete a message after a delay."""
    await asyncio.sleep(600)
    try:
        await msg.delete()
        logger.debug(f"Deleted message {msg.id} from chat {msg.chat.id}")
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")

def chunk_buttons(buttons, chunk_size=2):
    """Chunk buttons into rows."""
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    """Find close matches using difflib."""
    import difflib
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def get_movie_poster(series_key):
    """Get the poster URL for a series."""
    from database.crazy_db import get_poster_manuel
    poster_url = get_poster_manuel(series_key)
    if not poster_url:
        series = get_series_name(series_key)
        if series:
            poster_url = series.get('poster_url')
    return poster_url or NO_POSTER_FOUND_IMG[0]

async def global_filters(client: Client, message: Message, text=False) -> bool:
    """Apply global filters to a message."""
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

async def series_filter(client: Client, message: Message):
    """Apply series filter to a message."""
    logger.info(f"Applying series filter to message {message.id} from user {message.from_user.id}")
    text = message.text.strip()
    from database.crazy_db import get_series
    series_infos = get_series()
    series_keys = [series['key'] for series in series_infos]
    series_names = [series['title'] for series in series_infos]

    series_key = None
    
    if text.lower().replace(" ", "").replace("-", "") in series_keys:
        series_key = text.lower().replace(" ", "").replace("-", "")
        logger.info(f"Found exact key match: {series_key}")
    else:
        for s_info in series_infos:
            if s_info['title'].lower() == text.lower():
                series_key = s_info['key']
                logger.info(f"Found exact title match: {series_key}")
                break
        
        if not series_key:
            close_matches = find_close_matches(text, series_names)
            if not close_matches:
                first_word = text.split()[0]
                close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]
            
            if close_matches:
                logger.info(f"Found {len(close_matches)} close matches: {close_matches}")
                buttons = []
                for match in close_matches:
                    s_info = next((s for s in series_infos if s['title'] == match), None)
                    if s_info:
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user:{s_info['key']}:l1"))
                
                if buttons:
                    buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                    reply_markup = InlineKeyboardMarkup(buttons_chunked)
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

        languages = series.get("languages", {})
        
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
        for i, (lang_key, lang_data) in enumerate(languages.items()):
            buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user:{series_key}:l1:{i}"))
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
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

async def user_series_callback_handler(client: Client, query: CallbackQuery):
    """Handle user series callbacks."""
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

    if data.startswith("b:"):
        file_link_key = data.split(":", 1)[1]
        logger.info(f"Fetching files for link key: {file_link_key}")
        
        files_to_send, channel_id, first_msg_id, last_msg_id = await get_links_for_quality(file_link_key)

        if not files_to_send:
            logger.warning(f"No files found for link key: {file_link_key}")
            await query.answer("No files found for this quality.", show_alert=True)
            return

        await query.answer("Sending files...")
        
        for entry in files_to_send:
            try:
                await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=entry["file_id"],
                    caption=entry.get("caption", "")
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error sending cached media to user {query.from_user.id}: {e}")
                await client.send_message(query.from_user.id, f"Error sending file: {e}")
                
        if temp.AUTO_DELETE_TIME and temp.AUTO_DELETE_TIME > 0:
            delete_data = await client.send_message(
                chat_id=query.from_user.id,
                text=temp.AUTO_DELETE_MSG.format(time=temp.AUTO_DELETE_TIME)
            )
            asyncio.create_task(DeleteMessage(delete_data))
        return

    elif data.startswith("user:"):
        series_key = parts[1]
        logger.info(f"Processing series with key: {series_key}")
        series = get_series_name(series_key)
        if not series:
            logger.warning(f"Series not found for key: {series_key}")
            await query.message.edit_text("Series not found or deleted.", parse_mode=enums.ParseMode.HTML)
            return

        layer = parts[2] if len(parts) > 2 else None
        index = int(parts[3]) if len(parts) > 3 else None

        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
        )
        
        buttons = []
        back_callback = None

        if layer == "l1":  # Languages
            languages = list(series.get("languages", {}).items())
            if index >= len(languages):
                await query.answer("Language not found!", show_alert=True)
                return
            
            lang_key, lang_data = languages[index]
            lang_name = lang_data['name']
            
            seasons = list(lang_data.get("seasons", {}).items())
            for i, (season_key, season_data) in enumerate(seasons):
                buttons.append(InlineKeyboardButton(season_data['name'], callback_data=f"user:{series_key}:l2:{i}"))
            
            text = base_text + f"○ **Language:** `{lang_name}`\n\nSelect the season you need...!"
            back_callback = f"user:{series_key}:back"
        
        elif layer == "l2":  # Seasons
            languages = list(series.get("languages", {}).items())
            if index >= len(languages):
                await query.answer("Season not found!", show_alert=True)
                return
            
            lang_key, lang_data = languages[index]
            lang_name = lang_data['name']
            
            seasons = list(lang_data.get("seasons", {}).items())
            if index >= len(seasons):
                await query.answer("Season not found!", show_alert=True)
                return
            
            season_key, season_data = seasons[index]
            season_name = season_data['name']
            
            qualities = list(season_data.get("qualities", {}).items())
            for i, (quality_key, quality_data) in enumerate(qualities):
                file_link_key = quality_data.get('file_link_key')
                if file_link_key:
                    buttons.append(InlineKeyboardButton(quality_data['name'], callback_data=f"b:{file_link_key}"))
            
            text = base_text + f"○ **Language:** `{lang_name}`\n○ **Season:** `{season_name}`\n\nSelect the quality you need...!"
            back_callback = f"user:{series_key}:l1:{languages.index((lang_key, lang_data))}"
        
        elif layer == "back":
            series = get_series_name(series_key)
            if not series:
                await query.answer("Series not found!", show_alert=True)
                return
            
            languages = list(series.get("languages", {}).items())
            buttons = []
            for i, (lang_key, lang_data) in enumerate(languages):
                buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user:{series_key}:l1:{i}"))
            
            text = base_text + "\nSelect the language you need...!"
            back_callback = None
        
        else:
            await query.answer("Invalid action!", show_alert=True)
            return
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        if back_callback:
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=back_callback)])
        
        reply_markup = InlineKeyboardMarkup(buttons_chunked)

        try:
            await query.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Updated user series message for {series['title']}")
        except Exception as e:
            logger.error(f"Error editing message in user_series callback: {e}")
            await query.answer("An error occurred. Please try again.", show_alert=True)

async def handle_pm_filter_message(client: Client, message: Message):
    """Handle messages for pm_filter."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"Received message {message.id} from user {user_id} in chat {chat_id}")
    
    if message.chat.type != enums.ChatType.PRIVATE:
        logger.info(f"Message is in group {chat_id}, applying filters")
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)
        return
    
    logger.info(f"Applying filters for user {user_id}")
    glob = await global_filters(client, message)
    if glob == False:
        await series_filter(client, message)

async def handle_pm_filter_callback(client: Client, callback_query: CallbackQuery):
    """Handle callback queries for pm_filter."""
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Received callback query from user {user_id}: {data}")

    if data.startswith("user:") or data.startswith("b:"):
        logger.info(f"User series callback from user {user_id}")
        await user_series_callback_handler(client, callback_query)
        return

    logger.warning(f"Unknown callback type from user {user_id}: {data}")
