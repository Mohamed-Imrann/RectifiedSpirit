#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import re
import uuid
import logging
import os
import shutil
import requests
import json
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from pyrogram.errors import FloodWait, BadRequest, MessageIdInvalid, UserNotParticipant, ChatAdminRequired
from fuzzywuzzy import fuzz

from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, TMDB_API_KEY, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    get_series_by_key, update_series_field, add_or_update_language,
    get_languages, delete_language, add_or_update_season, get_seasons, delete_season,
    add_or_update_quality, get_qualities, get_quality_link, delete_quality,
    get_poster_file_id, update_poster_file_id, publish_series, episodes_collection,
    get_series, get_poster_manuel, get_admin_channel, series_collection
)
from utils import (
    get_message_id, get_messages, delete_messages_from_user_chat, 
    forward_messages_without_tag
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

temp_admin_data: Dict[int, Dict[str, Any]] = {}

async def DeleteMessage(msg):
    await asyncio.sleep(600)
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")

def create_dynamic_layout_from_pattern(items: List[str], layout_pattern: List[int], add_buttons: List[str] = None):
    layout = []
    item_index = 0
    
    for row_index, row_count in enumerate(layout_pattern):
        if item_index >= len(items):
            break
        
        row = []
        items_in_this_row = 0
        for _ in range(row_count):
            if item_index < len(items):
                item_button = InlineKeyboardButton(items[item_index], callback_data=f"item_{item_index}")
                row.append(item_button)
                item_index += 1
                items_in_this_row += 1
        
        if items_in_this_row > 0:
            plus_button = InlineKeyboardButton("+", callback_data=f"add_to_row_{row_index}")
            row.append(plus_button)
            layout.append(row)
    
    while item_index < len(items):
        row = []
        item_button = InlineKeyboardButton(items[item_index], callback_data=f"item_{item_index}")
        row.append(item_button)
        plus_button = InlineKeyboardButton("+", callback_data=f"add_to_row_{len(layout)}")
        row.append(plus_button)
        layout.append(row)
        item_index += 1
    
    if items:
        next_row_index = len(layout)
        layout.append([InlineKeyboardButton("+", callback_data=f"add_to_row_{next_row_index}")])
    else:
        layout.append([InlineKeyboardButton("+", callback_data="add_to_row_0")])
    
    if add_buttons:
        for button_text, callback_data in add_buttons:
            layout.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    return layout

async def download_and_upload_poster(client: Client, poster_url: str = None, message: Message = None, send_to_log_channel: bool = True):
    logger.info("Downloading and uploading poster")
    temp_dir = os.path.join(TMP_DOWNLOAD_DIRECTORY, str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    download_path = None
    file_id = None

    try:
        if poster_url:
            logger.info(f"Downloading poster from URL: {poster_url}")
            response = requests.get(poster_url, stream=True)
            response.raise_for_status()
            download_path = os.path.join(temp_dir, "poster.jpg")
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        elif message and message.photo and message.photo.file_id:
            logger.info("Downloading user-provided photo")
            download_path = await client.download_media(message.photo.file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        elif message and message.video and message.video.thumbs and message.video.thumbs[0].file_id:
            logger.info("Downloading user-provided video thumbnail")
            download_path = await client.download_media(message.video.thumbs[0].file_id, file_name=os.path.join(temp_dir, "poster.jpg"))
        else:
            logger.warning("No valid poster source provided")
            return None

        if download_path:
            if send_to_log_channel:
                logger.info("Uploading poster to LOG_CHANNEL")
                sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="#MainPoster")
                file_id = sent_msg.photo.file_id
                try:
                    await sent_msg.delete()
                    logger.debug("Deleted temporary poster from LOG_CHANNEL")
                except Exception as e:
                    logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
            else:
                # For admin posters, don't send to LOG_CHANNEL
                logger.info("Uploading poster without sending to LOG_CHANNEL")
                sent_msg = await client.send_photo(LOG_CHANNEL, photo=download_path, caption="Series Poster")
                file_id = sent_msg.photo.file_id
                try:
                    await sent_msg.delete()
                    logger.debug("Deleted temporary poster from LOG_CHANNEL")
                except Exception as e:
                    logger.warning(f"Could not delete temporary poster message from LOG_CHANNEL: {e}")
    except Exception as e:
        logger.error(f"Error downloading/uploading poster: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.debug(f"Cleaned up temporary directory: {temp_dir}")
    return file_id

async def send_series_details_message(client: Client, user_id: int, series_data: dict, message_id: int = None):
    logger.info(f"Sending series details message to user {user_id}")
    series_key = series_data['_id']
    poster_file_id = get_poster_file_id(series_key) or NO_POSTER_FOUND_IMG[0]

    text = (
        f"○ **Title:** `{series_data.get('title', 'N/A')}`
"
        f"○ **Released On:** `{series_data.get('released_on', 'N/A')}`
"
        f"○ **Genre:** `{series_data.get('genre', 'N/A')}`
"
        f"○ **Rating:** `{series_data.get('rating', 'N/A')}`
"
        f"○ **Media Type:** `{series_data.get('media_type', 'N/A').upper()}`
"
        f"○ **Published:** `{'✅' if series_data.get('published', False) else '❌'}`
"
    )

    buttons = [
        InlineKeyboardButton("🌐 Languages", callback_data="edit_manage_languages"),
        InlineKeyboardButton("🖼️ Poster", callback_data="edit_change_poster"),
    ]
    
    # Add toggle publish button only if series is unpublished
    if not series_data.get('published', False):
        buttons.append(InlineKeyboardButton("📤 Publish", callback_data="edit_publish_series"))
    else:
        buttons.append(InlineKeyboardButton("📝 Update", callback_data="edit_update_series"))
    
    layout = [[buttons[0]], [buttons[1], buttons[2]]]
    reply_markup = InlineKeyboardMarkup(layout)

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_file_id, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
        else:
            await client.send_photo(
                chat_id=user_id,
                photo=poster_file_id,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
    except Exception as e:
        logger.error(f"Error sending series details message: {e}")

async def send_language_management_message(client: Client, user_id: int, series_key: str, message_id: int):
    logger.info(f"Sending language management message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    languages = series_data.get("languages", [])
    language_layout = series_data.get("language_layout", [])
    
    text = f"**Series:** `{series_data.get('title', 'N/A')}`"
    text += "Select any Language group to add new Season/Part group inside them. Or click '+' button to add new Language group."

    language_names = [lang['name'] for lang in languages]
    
    add_buttons = [
        ("⬅️ Back", "edit_back_to_series")
    ]
    
    layout = create_dynamic_layout_from_pattern(language_names, language_layout, add_buttons)
    reply_markup = InlineKeyboardMarkup(layout)
    
    poster_to_use = series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG[0]

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            logger.debug(f"Edited language management message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new language management message {msg.id}")
            return msg.id
    except Exception as e:
        logger.error(f"Error editing language management message: {e}")
        return None

async def send_season_management_message(client: Client, user_id: int, series_key: str, language_name: str, message_id: int):
    logger.info(f"Sending season management message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await client.send_message(user_id, "Language not found.")
        return

    seasons = current_lang.get("seasons", [])
    season_layout = current_lang.get("season_layout", [])
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`"
        f"**Language:** `{language_name}`"
        "Select any Seasons group to add new Quality group into them. Or click '+' button to add new Seasons group."
    )

    season_names = [season['name'] for season in seasons]
    
    add_buttons = [
        ("🖼️ Change Poster for this Language", "edit_change_lang_poster"),
        (f"🗑️ Delete '{language_name}' Group", "edit_delete_language"),
        ("⬅️ Back", "edit_back_to_languages")
    ]
    
    layout = create_dynamic_layout_from_pattern(season_names, season_layout, add_buttons)
    reply_markup = InlineKeyboardMarkup(layout)
    
    poster_to_use = current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG[0]

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            logger.debug(f"Edited season management message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new season management message {msg.id}")
            return msg.id
    except Exception as e:
        logger.error(f"Error editing season management message: {e}")
        return None

async def send_quality_management_message(client: Client, user_id: int, series_key: str, language_name: str, season_name: str, message_id: int):
    logger.info(f"Sending quality management message to user {user_id}")
    series_data = get_series_by_key(series_key)
    if not series_data:
        logger.warning(f"Series not found for key: {series_key}")
        await client.send_message(user_id, "Series not found.")
        return

    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None) if current_lang else None
    if not current_season:
        await client.send_message(user_id, "Season not found.")
        return

    qualities = current_season.get("qualities", [])
    quality_layout = current_season.get("quality_layout", [])
    
    text = (
        f"**Series:** `{series_data.get('title', 'N/A')}`"
        f"**Language:** `{language_name}`"
        f"**Season:** `{season_name}`"
        "Select any Quality group to add new files into them. Or click '+' button to add new Quality group."
    )

    quality_names = [quality['name'] for quality in qualities]
    
    add_buttons = [
        ("🖼️ Change Poster for this Season", "edit_change_season_poster"),
        (f"🗑️ Delete '{season_name}' Group", "edit_delete_season"),
        ("⬅️ Back", "edit_back_to_seasons")
    ]
    
    layout = create_dynamic_layout_from_pattern(quality_names, quality_layout, add_buttons)
    reply_markup = InlineKeyboardMarkup(layout)
    
    poster_to_use = current_season.get("poster_file_id") or current_lang.get("poster_file_id") or series_data.get("poster_file_id") or NO_POSTER_FOUND_IMG[0]

    try:
        if message_id:
            await client.edit_message_media(
                chat_id=user_id,
                message_id=message_id,
                media=InputMediaPhoto(media=poster_to_use, caption=text, parse_mode=enums.ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
            logger.debug(f"Edited quality management message {message_id}")
            return message_id
        else:
            msg = await client.send_photo(
                chat_id=user_id,
                photo=poster_to_use,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            logger.debug(f"Sent new quality management message {msg.id}")
            return msg.id
    except Exception as e:
        logger.error(f"Error editing quality management message: {e}")
        return None

async def forward_messages_without_tag_with_retry(
    client: Client, 
    source_channel_id: int, 
    target_channel_id: int, 
    first_msg_id: int, 
    last_msg_id: int,
    progress_msg: Message = None
):
    """
    Forward messages without forward tag with comprehensive error handling
    """
    new_message_ids = []
    total_messages = last_msg_id - first_msg_id + 1
    processed = 0
    failed = 0
    
    logger.info(f"Forwarding {total_messages} messages from {source_channel_id} to {target_channel_id}")
    
    for msg_id in range(first_msg_id, last_msg_id + 1):
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Get the message from source
                try:
                    msg = await client.get_messages(source_channel_id, msg_id)
                except MessageIdInvalid:
                    logger.warning(f"Message {msg_id} is invalid, skipping")
                    failed += 1
                    break
                except Exception as e:
                    logger.error(f"Error getting message {msg_id}: {e}")
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        await asyncio.sleep(2)
                        continue
                    else:
                        failed += 1
                        break
                
                if not msg or msg.empty:
                    logger.warning(f"Message {msg_id} is empty, skipping")
                    failed += 1
                    break
                
                # Copy the message to target channel
                try:
                    copied_msg = await msg.copy(
                        chat_id=target_channel_id,
                        caption=msg.caption if msg.caption else None,
                        parse_mode=enums.ParseMode.HTML if msg.caption else None
                    )
                    new_message_ids.append(copied_msg.id)
                    processed += 1
                    
                    # Update progress every 5 messages
                    if progress_msg and processed % 5 == 0:
                        try:
                            await progress_msg.edit_text(
                                f"⏳ Forwarding files..."
                                f"Progress: {processed}/{total_messages} ({failed} failed)"
                            )
                        except Exception:
                            pass
                    
                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.5)
                    break
                    
                except FloodWait as e:
                    logger.warning(f"FloodWait encountered: {e.value} seconds")
                    if progress_msg:
                        try:
                            await progress_msg.edit_text(
                                f"⏳ Rate limit hit. Waiting {e.value} seconds..."
                                f"Progress: {processed}/{total_messages}"
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(e.value)
                    retry_count += 1
                    
                except BadRequest as e:
                    logger.error(f"BadRequest copying message {msg_id}: {str(e)}")
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        await asyncio.sleep(2)
                        continue
                    else:
                        failed += 1
                        break
                        
                except Exception as e:
                    logger.error(f"Error copying message {msg_id}: {str(e)}")
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        await asyncio.sleep(2)
                        continue
                    else:
                        failed += 1
                        break
                        
            except Exception as e:
                logger.error(f"Unexpected error processing message {msg_id}: {str(e)}")
                if retry_count < max_retries - 1:
                    retry_count += 1
                    await asyncio.sleep(2)
                    continue
                else:
                    failed += 1
                    break
    
    if progress_msg:
        try:
            await progress_msg.edit_text(
                f"✅ Forwarding complete!"
                f"Successfully forwarded: {processed}/{total_messages}"
                f"Failed: {failed}"
            )
        except Exception:
            pass
    
    logger.info(f"Forwarding complete: {processed} successful, {failed} failed")
    return new_message_ids if new_message_ids else None

async def edit_series_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Processing edit series callback: {data}")
    
    if user_id not in temp_admin_data:
        logger.warning(f"Admin {user_id} not in temp_admin_data")
        try:
            await callback_query.answer("Session expired. Please start again with /editseries.", show_alert=True)
        except:
            pass
        return
    
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    
    if data.startswith("edit_sel_"):
        series_key = data.split("_", 2)[2]
        series_data = get_series_by_key(series_key)
        if not series_data:
            try:
                await callback_query.answer("Series not found.", show_alert=True)
            except:
                pass
            return
        
        temp_admin_data[user_id]["current_series_key"] = series_key
        temp_admin_data[user_id]["state"] = "EDIT_SERIES_DETAILS"
        
        await send_series_details_message(client, user_id, series_data, main_message_id)
    
    elif data == "edit_back_to_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        series_data = get_series_by_key(series_key)
        if not series_data:
            try:
                await callback_query.answer("Series not found.", show_alert=True)
            except:
                pass
            return
        
        try:
            await callback_query.answer("Going back to series details...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "EDIT_SERIES_DETAILS"
        await send_series_details_message(client, user_id, series_data, main_message_id)
    
    elif data == "edit_manage_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        try:
            await callback_query.answer("Managing languages...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "EDIT_MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id)
    
    elif data.startswith("edit_add_to_row_"):
        row_index = int(data.split("_")[-1])
        current_state = temp_admin_data[user_id].get("state")
        
        if current_state == "EDIT_MANAGE_LANGUAGES":
            try:
                await callback_query.answer(f"Adding language to row {row_index + 1}...")
            except:
                pass
            temp_admin_data[user_id]["target_row"] = row_index
            
            # Delete previous prompt if exists
            if "ask_message_id" in temp_admin_data[user_id]:
                try:
                    await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
                except Exception:
                    pass
            
            ask_msg = await client.send_message(
                user_id,
                f"Send language name to add to row {row_index + 1}:"
            )
            temp_admin_data[user_id]["state"] = "EDIT_AWAITING_LANGUAGE_INPUT"
            temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
            
        elif current_state == "EDIT_MANAGE_SEASONS":
            try:
                await callback_query.answer(f"Adding season to row {row_index + 1}...")
            except:
                pass
            temp_admin_data[user_id]["target_row"] = row_index
            
            # Delete previous prompt if exists
            if "ask_message_id" in temp_admin_data[user_id]:
                try:
                    await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
                except Exception:
                    pass
            
            ask_msg = await client.send_message(
                user_id,
                f"Send season name to add to row {row_index + 1}:"
            )
            temp_admin_data[user_id]["state"] = "EDIT_AWAITING_SEASON_INPUT"
            temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
            
        elif current_state == "EDIT_MANAGE_QUALITIES":
            try:
                await callback_query.answer(f"Adding quality to row {row_index + 1}...")
            except:
                pass
            temp_admin_data[user_id]["target_row"] = row_index
            
            # Delete previous prompt if exists
            if "ask_message_id" in temp_admin_data[user_id]:
                try:
                    await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
                except Exception:
                    pass
            
            ask_msg = await client.send_message(
                user_id,
                f"Send quality name to add to row {row_index + 1}:"
            )
            temp_admin_data[user_id]["state"] = "EDIT_AWAITING_QUALITY_INPUT"
            temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
    
    elif data.startswith("edit_item_"):
        item_index = int(data.split("_")[1])
        current_state = temp_admin_data[user_id].get("state")
        
        if current_state == "EDIT_MANAGE_LANGUAGES":
            series_key = temp_admin_data[user_id].get("current_series_key")
            languages = get_languages(series_key)
            
            if 0 <= item_index < len(languages):
                language_name = languages[item_index]["name"]
                try:
                    await callback_query.answer(f"Selected: {language_name}")
                except:
                    pass
                temp_admin_data[user_id]["current_language"] = language_name
                temp_admin_data[user_id]["current_language_index"] = item_index
                temp_admin_data[user_id]["state"] = "EDIT_MANAGE_SEASONS"
                await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
            else:
                try:
                    await callback_query.answer("Invalid selection.", show_alert=True)
                except:
                    pass
                
        elif current_state == "EDIT_MANAGE_SEASONS":
            series_key = temp_admin_data[user_id].get("current_series_key")
            language_name = temp_admin_data[user_id].get("current_language")
            seasons = get_seasons(series_key, language_name)
            
            if 0 <= item_index < len(seasons):
                season_name = seasons[item_index]["name"]
                try:
                    await callback_query.answer(f"Selected: {season_name}")
                except:
                    pass
                temp_admin_data[user_id]["current_season"] = season_name
                temp_admin_data[user_id]["current_season_index"] = item_index
                temp_admin_data[user_id]["state"] = "EDIT_MANAGE_QUALITIES"
                await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
            else:
                try:
                    await callback_query.answer("Invalid selection.", show_alert=True)
                except:
                    pass
                
        elif current_state == "EDIT_MANAGE_QUALITIES":
            series_key = temp_admin_data[user_id].get("current_series_key")
            language_name = temp_admin_data[user_id].get("current_language")
            season_name = temp_admin_data[user_id].get("current_season")
            qualities = get_qualities(series_key, language_name, season_name)
            
            if 0 <= item_index < len(qualities):
                quality_name = qualities[item_index]["name"]
                link_key = qualities[item_index].get("link_key")
                
                if link_key:
                    # This quality already has files, show options
                    try:
                        await callback_query.answer(f"Options for: {quality_name}")
                    except:
                        pass
                    temp_admin_data[user_id]["current_quality"] = quality_name
                    temp_admin_data[user_id]["current_quality_index"] = item_index
                    temp_admin_data[user_id]["state"] = "EDIT_QUALITY_OPTIONS"
                    
                    # Show options message
                    text = f"Quality '{quality_name}' already has files. What would you like to do?"
                    buttons = [
                        [InlineKeyboardButton("🔄 Re-Add Files", callback_data="edit_readd_quality")],
                        [InlineKeyboardButton("🗑️ Delete Quality", callback_data="edit_delete_quality")],
                        [InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel_quality")]
                    ]
                    reply_markup = InlineKeyboardMarkup(buttons)
                    
                    try:
                        await client.edit_message_caption(
                            chat_id=user_id,
                            message_id=main_message_id,
                            caption=text,
                            reply_markup=reply_markup
                        )
                    except Exception as e:
                        logger.error(f"Error showing quality options: {e}")
                else:
                    # No existing files, proceed to add files
                    try:
                        await callback_query.answer(f"Selected: {quality_name}")
                    except:
                        pass
                    temp_admin_data[user_id]["current_quality"] = quality_name
                    temp_admin_data[user_id]["current_quality_index"] = item_index
                    temp_admin_data[user_id]["state"] = "EDIT_AWAITING_FIRST_FILE"
                    
                    # Delete previous prompt if exists
                    if "ask_message_id" in temp_admin_data[user_id]:
                        try:
                            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
                        except Exception:
                            pass
                    
                    ask_msg = await client.send_message(
                        user_id,
                        f"Forward me the first file (with tag) for {language_name}-{season_name}-{quality_name}"
                    )
                    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
            else:
                try:
                    await callback_query.answer("Invalid selection.", show_alert=True)
                except:
                    pass
    
    elif data == "edit_back_to_languages":
        series_key = temp_admin_data[user_id].get("current_series_key")
        try:
            await callback_query.answer("Going back to languages...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "EDIT_MANAGE_LANGUAGES"
        await send_language_management_message(client, user_id, series_key, main_message_id)
    
    elif data == "edit_back_to_seasons":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        try:
            await callback_query.answer("Going back to seasons...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "EDIT_MANAGE_SEASONS"
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
    
    elif data == "edit_change_poster":
        try:
            await callback_query.answer("Send a new poster...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "EDIT_AWAITING_SERIES_POSTER"
        await client.send_message(user_id, "Please send a photo or video to use as the series poster:")
    
    elif data == "edit_change_lang_poster":
        try:
            await callback_query.answer("Send a new poster...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "EDIT_AWAITING_LANGUAGE_POSTER"
        language_name = temp_admin_data[user_id].get("current_language")
        await client.send_message(user_id, f"Please send a photo or video to use as the poster for {language_name}:")
    
    elif data == "edit_change_season_poster":
        try:
            await callback_query.answer("Send a new poster...")
        except:
            pass
        temp_admin_data[user_id]["state"] = "EDIT_AWAITING_SEASON_POSTER"
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        await client.send_message(user_id, f"Please send a photo or video to use as the poster for {language_name}-{season_name}:")
    
    elif data == "edit_delete_language":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        try:
            await callback_query.answer(f"Deleting {language_name}...")
        except:
            pass
        
        if delete_language(series_key, language_name):
            await client.send_message(user_id, f"Language '{language_name}' deleted successfully.")
            await send_language_management_message(client, user_id, series_key, main_message_id)
        else:
            await client.send_message(user_id, f"Failed to delete language '{language_name}'.")
    
    elif data == "edit_delete_season":
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        try:
            await callback_query.answer(f"Deleting {season_name}...")
        except:
            pass
        
        if delete_season(series_key, language_name, season_name):
            await client.send_message(user_id, f"Season '{season_name}' deleted successfully.")
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
        else:
            await client.send_message(user_id, f"Failed to delete season '{season_name}'.")
    
    elif data == "edit_publish_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        try:
            await callback_query.answer("Publishing...")
        except:
            pass
        
        text = (
            "Do you want to publish this series?"
            "NOTE: Once published, it will be visible to users."
        )
        
        buttons = [
            [InlineKeyboardButton("✅ Yes, Publish", callback_data="edit_confirm_publish")],
            [InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel_publish")]
        ]
        
        reply_markup = InlineKeyboardMarkup(buttons)
        
        try:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption=text,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error showing publish confirmation: {e}")
    
    elif data == "edit_update_series":
        series_key = temp_admin_data[user_id].get("current_series_key")
        try:
            await callback_query.answer("Updating metadata...")
        except:
            pass
        
        text = (
            "Do you want to update this series' metadata?"
            "NOTE: This will only update the metadata (title, poster, etc.) "
            "without affecting the published status or file links."
        )
        
        buttons = [
            [InlineKeyboardButton("✅ Yes, Update", callback_data="edit_confirm_update")],
            [InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel_update")]
        ]
        
        reply_markup = InlineKeyboardMarkup(buttons)
        
        try:
            await client.edit_message_caption(
                chat_id=user_id,
                message_id=main_message_id,
                caption=text,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error showing update confirmation: {e}")
    
    elif data == "edit_confirm_publish":
        series_key = temp_admin_data[user_id].get("current_series_key")
        try:
            await callback_query.answer("Publishing...")
        except:
            pass
        
        # Clean up empty groups but keep all file links
        series = series_collection.find_one({"_id": series_key})
        if not series:
            await callback_query.message.edit_caption("❌ Series not found.")
            return

        cleaned_languages = []
        for lang in series.get("languages", []):
            cleaned_seasons = []
            for season in lang.get("seasons", []):
                cleaned_qualities = []
                for quality in season.get("qualities", []):
                    if quality.get("link_key"):
                        cleaned_qualities.append(quality)
                if cleaned_qualities:
                    season["qualities"] = cleaned_qualities
                    cleaned_seasons.append(season)
            if cleaned_seasons:
                lang["seasons"] = cleaned_seasons
                cleaned_languages.append(lang)
        
        try:
            result = series_collection.update_one(
                {"_id": series_key},
                {"$set": {
                    "languages": cleaned_languages,
                    "published": True
                }}
            )
            if result.modified_count > 0:
                await callback_query.message.edit_caption("✅ Published Successfully")
                # Refresh the view
                series_data = get_series_by_key(series_key)
                await send_series_details_message(client, user_id, series_data, main_message_id)
            else:
                await callback_query.message.edit_caption("❌ Failed to publish series. Please try again.")
        except Exception as e:
            logger.error(f"Error publishing series: {e}")
            await callback_query.message.edit_caption(f"❌ Error: {str(e)}")
    
    elif data == "edit_confirm_update":
        series_key = temp_admin_data[user_id].get("current_series_key")
        try:
            await callback_query.answer("Updating...")
        except:
            pass
        
        # Just refresh the series data without changing published status
        series_data = get_series_by_key(series_key)
        if series_data:
            await callback_query.message.edit_caption("✅ Metadata Updated Successfully")
            await send_series_details_message(client, user_id, series_data, main_message_id)
        else:
            await callback_query.message.edit_caption("❌ Series not found.")

    elif data in ["edit_cancel_publish", "edit_cancel_update"]:
        series_key = temp_admin_data[user_id].get("current_series_key")
        try:
            await callback_query.answer("Cancelled")
        except:
            pass
        
        series_data = get_series_by_key(series_key)
        if series_data:
            await send_series_details_message(client, user_id, series_data, main_message_id)
        else:
            await callback_query.message.edit_caption("❌ Series not found.")
    
    # Quality options handlers
    elif data == "edit_readd_quality":
        # Re-add files for the quality
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_name = temp_admin_data[user_id].get("current_quality")
        
        try:
            await callback_query.answer("Re-adding files...")
        except:
            pass
        
        # Set state to await first file
        temp_admin_data[user_id]["state"] = "EDIT_AWAITING_FIRST_FILE"
        
        # Delete previous prompt if exists
        if "ask_message_id" in temp_admin_data[user_id]:
            try:
                await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
            except Exception:
                pass
        
        ask_msg = await client.send_message(
            user_id,
            f"Forward me the first file (with tag) for {language_name}-{season_name}-{quality_name}"
        )
        temp_admin_data[user_id]["ask_message_id"] = ask_msg.id
        
    elif data == "edit_delete_quality":
        # Delete the quality (remove the link_key)
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_name = temp_admin_data[user_id].get("current_quality")
        
        try:
            await callback_query.answer("Deleting quality...")
        except:
            pass
        
        # Remove the link_key from the quality
        if add_or_update_quality(series_key, language_name, season_name, quality_name, None):
            await client.send_message(user_id, f"Quality '{quality_name}' files removed.")
            # Go back to the quality management screen
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
        else:
            await client.send_message(user_id, "Failed to remove quality files. Please try again.")
        
    elif data == "edit_cancel_quality":
        # Cancel and go back to quality management
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        
        try:
            await callback_query.answer("Cancelled.")
        except:
            pass
        
        # Go back to the quality management screen
        main_message_id = temp_admin_data[user_id].get("main_message_id")
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)

    # Handle text input states
    elif data == "edit_search_again":
        try:
            await callback_query.answer("Search again...")
        except:
            pass
        query = temp_admin_data[user_id].get("query")
        if not query:
            try:
                await callback_query.answer("No previous search query found.", show_alert=True)
            except:
                pass
            return
        
        temp_admin_data[user_id]["state"] = "EDIT_SEARCH_RESULTS"
        await send_series_selection_message(client, user_id, query, get_series(), main_message_id)

@Client.on_message(filters.text & filters.private & filters.user(ADMINS))
async def handle_edit_text_message(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Received admin text message {message.id} from user {user_id}")
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        current_state = temp_admin_data[user_id].get("state")
        
        if current_state == "EDIT_AWAITING_LANGUAGE_INPUT":
            await process_language_input(client, message, message.text.strip())
        elif current_state == "EDIT_AWAITING_SEASON_INPUT":
            await process_season_input(client, message, message.text.strip())
        elif current_state == "EDIT_AWAITING_QUALITY_INPUT":
            await process_quality_input(client, message, message.text.strip())
        elif current_state == "EDIT_AWAITING_CODEC_INPUT":
            await process_codec_input(client, message, message.text.strip())

@Client.on_message((filters.photo | filters.video | filters.document) & filters.private & filters.user(ADMINS))
async def handle_edit_media_message(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Received admin media message {message.id} from user {user_id}")
    
    if user_id in temp_admin_data and temp_admin_data[user_id].get("state"):
        current_state = temp_admin_data[user_id].get("state")
        
        if current_state == "EDIT_AWAITING_SERIES_POSTER":
            await process_poster_input(client, message, "series")
        elif current_state == "EDIT_AWAITING_LANGUAGE_POSTER":
            await process_poster_input(client, message, "language")
        elif current_state == "EDIT_AWAITING_SEASON_POSTER":
            await process_poster_input(client, message, "season")
        elif current_state == "EDIT_AWAITING_FIRST_FILE":
            await process_first_file_input(client, message)
        elif current_state == "EDIT_AWAITING_LAST_FILE":
            await process_last_file_input(client, message)

async def process_language_input(client: Client, message: Message, language_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    target_row = temp_admin_data[user_id].get("target_row")
    
    # Delete the prompt message
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass
    
    # Send confirmation message
    confirm_msg = await message.reply("Language Added")
    
    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Series not found.")
        return
    
    languages = series_data.get("languages", [])
    current_layout = series_data.get("language_layout", [])
    
    existing_language = next((lang for lang in languages if lang["name"].lower() == language_name.lower()), None)
    if existing_language:
        await message.reply(f"Language '{language_name}' already exists.")
        return
    
    while len(current_layout) <= target_row:
        current_layout.append(0)
    
    insertion_index = sum(current_layout[:target_row]) + current_layout[target_row]
    
    new_language = {"name": language_name, "seasons": [], "season_layout": []}
    
    languages.insert(insertion_index, new_language)
    
    current_layout[target_row] += 1
    
    try:
        result = series_collection.update_one(
            {"_id": series_key},
            {"$set": {"languages": languages, "language_layout": current_layout}}
        )
        if result.modified_count > 0:
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_language_management_message(client, user_id, series_key, main_message_id)
            
            # Delete confirmation message after a delay
            asyncio.create_task(DeleteMessage(confirm_msg))
        else:
            await message.reply("Failed to add language. Please try again.")
    except Exception as e:
        logger.error(f"Error adding language: {e}")
        await message.reply(f"Error adding language: {e}")

async def process_season_input(client: Client, message: Message, season_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    target_row = temp_admin_data[user_id].get("target_row")
    
    # Delete the prompt message
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass
    
    # Send confirmation message
    confirm_msg = await message.reply("Season Added")
    
    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Series not found.")
        return
    
    languages = series_data.get("languages", [])
    current_lang = next((lang for lang in languages if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await message.reply("Language not found.")
        return
    
    seasons = current_lang.get("seasons", [])
    current_layout = current_lang.get("season_layout", [])
    
    existing_season = next((s for s in seasons if s["name"].lower() == season_name.lower()), None)
    if existing_season:
        await message.reply(f"Season '{season_name}' already exists.")
        return
    
    while len(current_layout) <= target_row:
        current_layout.append(0)
    
    insertion_index = sum(current_layout[:target_row]) + current_layout[target_row]
    
    new_season = {"name": season_name, "qualities": [], "quality_layout": []}
    
    seasons.insert(insertion_index, new_season)
    
    current_layout[target_row] += 1
    
    try:
        result = series_collection.update_one(
            {"_id": series_key},
            {"$set": {"languages": languages}}
        )
        if result.modified_count > 0:
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
            
            # Delete confirmation message after a delay
            asyncio.create_task(DeleteMessage(confirm_msg))
        else:
            await message.reply("Failed to add season. Please try again.")
    except Exception as e:
        logger.error(f"Error adding season: {e}")
        await message.reply(f"Error adding season: {e}")

async def process_quality_input(client: Client, message: Message, quality_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    target_row = temp_admin_data[user_id].get("target_row")
    
    # Delete the prompt message
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass
    
    # Send confirmation message
    confirm_msg = await message.reply("Quality Added")
    
    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Series not found.")
        return
    
    languages = series_data.get("languages", [])
    current_lang = next((lang for lang in languages if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await message.reply("Language not found.")
        return
    
    seasons = current_lang.get("seasons", [])
    current_season = next((s for s in seasons if s["name"].lower() == season_name.lower()), None)
    if not current_season:
        await message.reply("Season not found.")
        return
    
    qualities = current_season.get("qualities", [])
    current_layout = current_season.get("quality_layout", [])
    
    existing_quality = next((q for q in qualities if q["name"].lower() == quality_name.lower()), None)
    if existing_quality:
        await message.reply(f"Quality '{quality_name}' already exists.")
        return
    
    while len(current_layout) <= target_row:
        current_layout.append(0)
    
    insertion_index = sum(current_layout[:target_row]) + current_layout[target_row]
    
    new_quality = {"name": quality_name}
    
    qualities.insert(insertion_index, new_quality)
    
    current_layout[target_row] += 1
    
    try:
        result = series_collection.update_one(
            {"_id": series_key},
            {"$set": {"languages": languages}}
        )
        if result.modified_count > 0:
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
            
            # Delete confirmation message after a delay
            asyncio.create_task(DeleteMessage(confirm_msg))
        else:
            await message.reply("Failed to add quality. Please try again.")
    except Exception as e:
        logger.error(f"Error adding quality: {e}")
        await message.reply(f"Error adding quality: {e}")

async def process_codec_input(client: Client, message: Message, codec_name: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    quality_name = temp_admin_data[user_id].get("current_quality")
    
    # Delete the prompt message
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass
    
    # Send confirmation message
    confirm_msg = await message.reply("Codec Added")
    
    series_data = get_series_by_key(series_key)
    if not series_data:
        await message.reply("Series not found.")
        return
    
    languages = series_data.get("languages", [])
    current_lang = next((lang for lang in languages if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await message.reply("Language not found.")
        return
    
    seasons = current_lang.get("seasons", [])
    current_season = next((s for s in seasons if s["name"].lower() == season_name.lower()), None)
    if not current_season:
        await message.reply("Season not found.")
        return
    
    qualities = current_season.get("qualities", [])
    current_quality = next((q for q in qualities if q["name"].lower() == quality_name.lower()), None)
    if not current_quality:
        await message.reply("Quality not found.")
        return
    
    codecs = current_quality.get("codecs", [])
    
    if codec_name.lower() in [c.lower() for c in codecs]:
        await message.reply(f"Codec '{codec_name}' already exists.")
        return
    
    codecs.append(codec_name)
    
    try:
        result = series_collection.update_one(
            {"_id": series_key},
            {"$set": {"languages": languages}}
        )
        if result.modified_count > 0:
            main_message_id = temp_admin_data[user_id].get("main_message_id")
            await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
            
            # Delete confirmation message after a delay
            asyncio.create_task(DeleteMessage(confirm_msg))
        else:
            await message.reply("Failed to add codec. Please try again.")
    except Exception as e:
        logger.error(f"Error adding codec: {e}")
        await message.reply(f"Error adding codec: {e}")

async def process_poster_input(client: Client, message: Message, poster_type: str):
    user_id = message.from_user.id
    series_key = temp_admin_data[user_id].get("current_series_key")
    language_name = temp_admin_data[user_id].get("current_language")
    season_name = temp_admin_data[user_id].get("current_season")
    
    # Download and upload the poster
    poster_file_id = await download_and_upload_poster(client, message=message, send_to_log_channel=(poster_type == "series"))
    
    if not poster_file_id:
        await message.reply("Failed to process the poster. Please try again.")
        return
    
    # Update the appropriate poster
    if poster_type == "series":
        if update_poster_file_id(series_key, poster_file_id):
            await message.reply("Series poster updated successfully.")
        else:
            await message.reply("Failed to update series poster. Please try again.")
    elif poster_type == "language":
        if add_or_update_language(series_key, language_name, poster_file_id):
            await message.reply("Language poster updated successfully.")
        else:
            await message.reply("Failed to update language poster. Please try again.")
    elif poster_type == "season":
        if add_or_update_season(series_key, language_name, season_name, poster_file_id):
            await message.reply("Season poster updated successfully.")
        else:
            await message.reply("Failed to update season poster. Please try again.")
    
    # Return to the appropriate screen
    main_message_id = temp_admin_data[user_id].get("main_message_id")
    if poster_type == "series":
        await send_series_details_message(client, user_id, get_series_by_key(series_key), main_message_id)
    elif poster_type == "language":
        await send_season_management_message(client, user_id, series_key, language_name, main_message_id)
    elif poster_type == "season":
        await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)

async def process_first_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    # Get the channel_id and message_id from the forwarded message
    channel_id, msg_id = await get_message_id(client, message)
    if channel_id == 0 or msg_id == 0:
        await message.reply("Invalid message. Please forward a message from a channel.")
        return

    # Store the source channel and first message info
    temp_admin_data[user_id]["source_channel_id"] = channel_id
    temp_admin_data[user_id]["source_first_msg_id"] = msg_id

    # Delete the previous prompt if exists
    if "ask_message_id" in temp_admin_data[user_id]:
        try:
            await client.delete_messages(user_id, temp_admin_data[user_id]["ask_message_id"])
        except Exception:
            pass

    # Ask for the last file
    ask_msg = await client.send_message(
        user_id,
        "Forward me the last file (with tag) for this quality:"
    )
    temp_admin_data[user_id]["state"] = "EDIT_AWAITING_LAST_FILE"
    temp_admin_data[user_id]["ask_message_id"] = ask_msg.id

async def process_last_file_input(client: Client, message: Message):
    user_id = message.from_user.id
    # Get the channel_id and message_id from the forwarded message
    channel_id, msg_id = await get_message_id(client, message)
    if channel_id == 0 or msg_id == 0:
        await message.reply("Invalid message. Please forward a message from a channel.")
        return

    # Get the stored source channel and first message info
    source_channel_id = temp_admin_data[user_id].get("source_channel_id")
    source_first_msg_id = temp_admin_data[user_id].get("source_first_msg_id")

    if not source_channel_id or not source_first_msg_id:
        await message.reply("First file information not found. Please start over.")
        return

    # Check if the messages are from the same source channel
    if channel_id != source_channel_id:
        await message.reply("The first and last files must be from the same channel.")
        return

    # Get the assigned channel for this admin
    assigned_channel_id = get_admin_channel(user_id)
    if not assigned_channel_id:
        await message.reply("You don't have an assigned channel. Please contact the bot owner.")
        return

    # Forward the range of messages to the assigned channel without forward tag
    progress_msg = await message.reply("⏳ Forwarding files to assigned channel. Please wait...")
    
    try:
        new_message_ids = await forward_messages_without_tag_with_retry(
                        client, source_channel_id, assigned_channel_id, source_first_msg_id, msg_id, progress_msg
        )

        if not new_message_ids:
            await progress_msg.edit_text("❌ Failed to forward files. Please try again.")
            return

        # The new first and last message IDs in the assigned channel
        new_first_msg_id = new_message_ids[0]
        new_last_msg_id = new_message_ids[-1]

        # Form the link_key string
        channel_id_str = str(assigned_channel_id)
        if channel_id_str.startswith("-100"):
            clean_channel_id = channel_id_str[4:]  # Remove -100 prefix
        else:
            clean_channel_id = channel_id_str

        # Form the link_key string without -100 prefix
        link_key = f"get_{clean_channel_id}_{new_first_msg_id}_{new_last_msg_id}"

        # Update the quality with the new link_key
        series_key = temp_admin_data[user_id].get("current_series_key")
        language_name = temp_admin_data[user_id].get("current_language")
        season_name = temp_admin_data[user_id].get("current_season")
        quality_name = temp_admin_data[user_id].get("current_quality")

        if not all([series_key, language_name, season_name, quality_name]):
            await progress_msg.edit_text("❌ Session expired. Please start over.")
            return

        # Update the quality with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if add_or_update_quality(series_key, language_name, season_name, quality_name, link_key):
                    await progress_msg.edit_text(f"✅ Quality '{quality_name}' updated successfully with {len(new_message_ids)} files.")
                    # Go back to the quality management screen
                    main_message_id = temp_admin_data[user_id].get("main_message_id")
                    await send_quality_management_message(client, user_id, series_key, language_name, season_name, main_message_id)
                    break
                else:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
                        continue
                    else:
                        await progress_msg.edit_text("❌ Failed to update quality after multiple attempts. Please try again.")
            except Exception as e:
                logger.error(f"Error updating quality (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                else:
                    await progress_msg.edit_text(f"❌ Error updating quality: {str(e)}")
                    
    except FloodWait as e:
        logger.warning(f"FloodWait encountered in process_last_file_input: {e.value} seconds")
        await progress_msg.edit_text(f"⏳ Telegram rate limit hit. Waiting {e.value} seconds...")
        await asyncio.sleep(e.value)
        await progress_msg.edit_text("🔄 Retrying operation...")
        # Retry the operation
        await process_last_file_input(client, message)
    except Exception as e:
        logger.error(f"Unexpected error in process_last_file_input: {e}")
        await progress_msg.edit_text(f"❌ An unexpected error occurred: {str(e)}")

@Client.on_callback_query(filters.user(ADMINS))
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    if data.startswith("edit_"):
        await edit_series_callback_handler(client, callback_query)

@Client.on_message(filters.command('editseries') & filters.user(ADMINS))
async def edit_series_command(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} started edit series UI")
    
    # Check if user has an assigned channel
    assigned_channel = get_admin_channel(user_id)
    if not assigned_channel:
        await message.reply("You don't have an assigned channel. Please contact the bot owner.")
        return
    
    query = message.text.split(None, 1)[1] if len(message.text.split(None, 1)) > 1 else None

    if not query:
        await message.reply("Usage: `/editseries <series_title>`")
        return

    # Search for series in database
    all_series = get_series()
    if not all_series:
        await message.reply("No series found in database.")
        return

    # Find matching series
    matches = []
    for series in all_series:
        title = series.get('title', '')
        similarity = fuzz.partial_ratio(query.lower(), title.lower())
        if similarity > 70:  # Only show reasonably close matches
            matches.append((series, similarity))

    # Sort by similarity
    matches.sort(key=lambda x: x[1], reverse=True)
    matched_series = [match[0] for match in matches[:10]]  # Limit to top 10 matches

    if not matched_series:
        await message.reply("No matching series found in database.")
        return

    # Show selection menu
    text = f"**Select a series to edit:**\nSearch query: `{query}`"
    
    buttons = []
    for series in matched_series:
        button_text = f"{series.get('title', 'N/A')} ({series.get('released_on', 'N/A')})"
        callback_data = f"edit_sel_{series['_id']}"
        buttons.append(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    buttons.append(InlineKeyboardButton("🔍 Search Again", callback_data="edit_search_again"))
    
    layout = [[button] for button in buttons]
    reply_markup = InlineKeyboardMarkup(layout)

    try:
        temp_msg = await message.reply_photo(
            photo=NO_POSTER_FOUND_IMG[0],
            caption=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        temp_admin_data[user_id] = {
            "state": "EDIT_SERIES_SELECTION",
            "main_message_id": temp_msg.id,
            "query": query
        }
    except Exception as e:
        logger.error(f"Error sending series selection message: {e}")
        await message.reply("Failed to show series selection. Please try again.")
