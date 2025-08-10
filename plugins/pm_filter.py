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
from info import SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG, ADMINS # Ensure ADMINS is imported
from database.crazy_db import (
    get_series, get_series_name, get_poster_manuel # get_series_name and get_poster_manuel are wrappers now
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import temp, get_links_for_quality # get_links_for_quality is now in utils.py
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
    """Delete a message after a delay."""
    await asyncio.sleep(temp.AUTO_DELETE_TIME) # Use AUTO_DELETE_TIME from temp
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
    """Get the poster file_id for a series."""
    poster_file_id = get_poster_manuel(series_key) # This now calls get_poster_file_id from crazy_db
    return poster_file_id or NO_POSTER_FOUND_IMG[0] # NO_POSTER_FOUND_IMG is a list

# Global filter function
async def global_filters(client: Client, message: Message, text=False) -> bool:
    """Apply global filters to a message."""
    logger.info(f"Applying global filters to message {message.id} from user {message.from_user.id}")
    group_id = message.chat.id
    name = text or message.text 
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
    keywords = await get_gfilters("gfilters") # "gfilters" is the collection name

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
    """Apply series filter to a message."""
    logger.info(f"Applying series filter to message {message.id} from user {message.from_user.id}")
    text = message.text.strip()
    series_infos = get_series() # This returns a list of series documents
    series_keys = [series['_id'] for series in series_infos] # Use '_id' as the key
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
                series_key = s_info['_id'] # Use '_id'
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
                        buttons.append(InlineKeyboardButton(match, callback_data=f"user_series:{s_info['_id']}")) # Use '_id'
                
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
        series = get_series_name(series_key) # This calls get_series_by_key
        if not series:
            logger.warning(f"Series not found for key: {series_key}")
            return

        languages = series.get("languages", []) # languages is a list of dicts
        
        reply_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n\n"
            "Select the language you need...!"
        )
        poster_url = get_movie_poster(series_key) # This gets the poster file_id
        
        buttons = []
        for lang_data in languages: # Iterate through the list of language dictionaries
            buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user_series:{series_key}:{lang_data['name']}"))
        
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

# Message handlers
@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client: Client, message: Message):
    """Handle text messages."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"Received text message {message.id} from user {user_id} in chat {chat_id}")
    
    # If the message is in a group, apply global and series filters
    if message.chat.type != enums.ChatType.PRIVATE:
        logger.info(f"Message is in group {chat_id}, applying filters")
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)
        return
    
    # For private chats from non-admins, apply global and series filters
    if user_id not in ADMINS: # Use ADMINS from info.py
        logger.info(f"Applying filters for user {user_id}")
        glob = await global_filters(client, message)
        if glob == False:
            await series_filter(client, message)

# Callback handlers
@Client.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    """Handle callback queries."""
    user_id = callback_query.from_user.id
    data = callback_query.data
    logger.info(f"Received callback query from user {user_id}: {data}")

    # Handle user series callbacks
    if data.startswith("user_series:") or data.startswith("b:"):
        logger.info(f"User series callback from user {user_id}")
        await user_series_callback_handler(client, callback_query)
        return

    logger.warning(f"Unknown callback type from user {user_id}: {data}")

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

    if data == "pages":
        await query.answer()
        return

    elif data.startswith("b:"):
        # This is the final link to fetch files
        file_link_key = data.split(":", 1)[1]
        logger.info(f"Fetching files for link key: {file_link_key}")
        
        # Fetch files from the episodes collection using get_links_for_quality from utils
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
        series = get_series_name(series_key) # This calls get_series_by_key
        if not series:
            logger.warning(f"Series not found for key: {series_key}")
            await query.message.edit_text("Series not found or deleted.", parse_mode=enums.ParseMode.HTML)
            return

        lang_name_from_callback = parts[2] if len(parts) > 2 else None
        season_name_from_callback = parts[3] if len(parts) > 3 else None
        quality_name_from_callback = parts[4] if len(parts) > 4 else None

        base_text = (
            f"○ **Title:** `{series['title']}`\n"
            f"○ **Released On:** `{series['released_on']}`\n"
            f"○ **Genre:** `{series['genre']}`\n"
            f"○ **Rating:** `{series['rating']}`\n"
            f"○ **Media Type:** `{series.get('media_type', 'N/A').upper()}`\n"
        )
        
        buttons = []
        back_callback = None

        if not lang_name_from_callback: # Show languages
            languages = series.get("languages", [])
            for lang_data in languages: # Iterate through the list
                buttons.append(InlineKeyboardButton(lang_data['name'], callback_data=f"user_series:{series_key}:{lang_data['name']}"))
            text = base_text + "\nSelect the language you need...!"
            
        elif not season_name_from_callback: # Show seasons for selected language
            current_lang = next((lang for lang in series.get("languages", []) if lang["name"] == lang_name_from_callback), None)
            if current_lang:
                seasons = current_lang.get("seasons", [])
                for season_data in seasons: # Iterate through the list
                    buttons.append(InlineKeyboardButton(season_data['name'], callback_data=f"user_series:{series_key}:{lang_name_from_callback}:{season_data['name']}"))
            text = base_text + f"○ **Language:** `{lang_name_from_callback}`\n\nSelect the season you need...!"
            back_callback = f"user_series:{series_key}"

        elif not quality_name_from_callback: # Show qualities for selected season
            current_lang = next((lang for lang in series.get("languages", []) if lang["name"] == lang_name_from_callback), None)
            current_season = next((s for s in current_lang.get("seasons", []) if s["name"] == season_name_from_callback), None) if current_lang else None
            if current_season:
                qualities = current_season.get("qualities", [])
                for quality_data in qualities: # Iterate through the list
                    file_link_key = quality_data.get('link_key')
                    if file_link_key:
                        buttons.append(InlineKeyboardButton(quality_data['name'], callback_data=f"b:{file_link_key}"))
            text = base_text + f"○ **Language:** `{lang_name_from_callback}`\n○ **Season:** `{season_name_from_callback}`\n\nSelect the quality you need...!"
            back_callback = f"user_series:{series_key}:{lang_name_from_callback}"
        
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
        except MessageNotModified:
            logger.debug("Message not modified, likely no changes")
        except Exception as e:
            logger.error(f"Error editing message in user_series callback: {e}")
            await query.answer("An error occurred. Please try again.", show_alert=True)

# Register handlers
Client.on_message(filters.text & (filters.private | filters.group))(handle_message)
Client.on_callback_query()(callback_handler)
