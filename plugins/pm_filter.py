import re
import pyrogram 
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from info import ADMINS, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    get_series, get_series_by_key, get_languages, get_seasons, get_qualities, get_quality_link, get_poster_file_id
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from utils import temp
from imdb import Cinemagoer # Keep for find_most_similar_title if needed for fallback
import asyncio
import difflib
import logging
import random

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # Changed to INFO for more detailed logging during development

requestor = {}
imdb = Cinemagoer()

async def DeleteMessage(msg):
    await asyncio.sleep(600)
    await msg.delete()

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def chunk_buttons(buttons, chunk_size=3):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

# This function is now updated to handle both file IDs and URLs
def get_series_poster_for_user(series_key):
    poster_source = get_poster_file_id(series_key) # This can be a file ID or a URL
    if poster_source:
        if poster_source.startswith(('http://', 'https://')):
            logger.info(f"Poster for series {series_key} is a URL: {poster_source}")
            return poster_source
        elif len(poster_source) > 20 and poster_source.replace('_', '').replace('-', '').isalnum():
            # This is a heuristic for a Telegram file ID.
            logger.info(f"Poster for series {series_key} is a File ID: {poster_source}")
            return poster_source
        else:
            logger.warning(f"Poster for series {series_key} is an unrecognized format: {poster_source}. Falling back to default.")
            return NO_POSTER_FOUND_IMG
    else:
        logger.info(f"No poster found for series {series_key}. Using default.")
        return NO_POSTER_FOUND_IMG

@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client, message):
    glob = await global_filters(client, message)
    if glob == False:
        await series_filter(client, message)


async def global_filters(client, message, text=False):
    group_id = message.chat.id
    name = text or message.text 
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
    keywords = await get_gfilters("gfilters")
    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\\W])" + re.escape(keyword) + r"( |$|[\\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
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
            except Exception as e:
                logger.exception(e)
            break
    else:
        return False

async def series_filter(client, message):
    text = message.text.strip()
    series_list_data = get_series() # Get all series documents
    
    # Filter for published series only
    published_series = [s for s in series_list_data if s.get('published', False)]

    series_keys = [s['_id'] for s in published_series]
    series_titles = [s['title'] for s in published_series]

    series_data = None

    # Try exact match by key or title
    for s in published_series:
        if text.lower() == s['_id'].lower() or text.lower() == s['title'].lower():
            series_data = s
            break
    
    # If no exact match, try close matches
    if not series_data:
        close_matches_titles = find_close_matches(text, series_titles)
        if not close_matches_titles:
            first_word = text.split()[0]
            close_matches_titles = [name for name in series_titles if name.lower().startswith(first_word.lower())]
        
        if close_matches_titles:
            buttons = []
            for match_title in close_matches_titles:
                # Find the series data for the matched title
                matched_series = next((s for s in published_series if s['title'] == match_title), None)
                if matched_series:
                    buttons.append(
                        InlineKeyboardButton(match_title, callback_data=f"spellcheck-{matched_series['_id']}")
                    )
            
            if buttons:
                buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                reply_markup = InlineKeyboardMarkup(buttons_chunked)
                etho = await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
                reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
                requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                asyncio.create_task(DeleteMessage(etho))
                return

    if series_data:
        languages = series_data.get("languages", [])
        
        # Filter out languages with no seasons
        languages = [lang for lang in languages if lang.get('seasons')]

        if not languages:
            await message.reply_text("No languages available for this series yet.")
            return

        reply_text = (
            f"○ <b>Title:</b> <code>{series_data['title']}</code>\n"
            f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>\n"
            f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>\n"
            f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>\n\n"
            "Select the language you need...!"
        )
        
        poster_to_use = get_series_poster_for_user(series_data['_id']) # Use the updated function
        
        buttons = []
        for lang in languages:
            buttons.append(InlineKeyboardButton(lang['name'], callback_data=f"user_lang:{series_data['_id']}:{lang['name']}"))
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
        try:
            etho = await message.reply_photo(photo=poster_to_use, caption=reply_text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
        except pyrogram.errors.MediaEmpty:
            # Fallback if poster_to_use is invalid (e.g., a broken URL or invalid file ID)
            logger.error(f"MediaEmpty error for poster: {poster_to_use}. Falling back to NO_POSTER_FOUND_IMG.")
            etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG, caption=reply_text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
        except Exception as e:
            logger.error(f"Error sending series details to user: {e}")
            await message.reply_text("An error occurred while fetching series details.")


@Client.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    data = query.data
    parts = data.split(":")
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id

    reply_msg = query.message.reply_to_message  
    if reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    else:
        requested_user = requestor.get(f"{chat_id}•{message_id}")
    
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        await query.answer("Not your request!", show_alert=True)
        return

    if data == "pages":
        await query.answer()
        return

    elif data.startswith("b:"):
        try:
            k = data.split(":")
            parameter = k[1]
            url = f"https://t.me/{temp.U_NAME}?start={parameter}"
            await query.answer(url=url)
        except pyrogram.errors.exceptions.bad_request_400.UrlInvalid:
            await query.answer("Invalid URL provided.", show_alert=True)

    elif data.startswith("spellcheck-"):
        series_key = parts[1]
        series_data = get_series_by_key(series_key)
        if series_data and series_data.get('published', False):
            languages = series_data.get("languages", [])
            languages = [lang for lang in languages if lang.get('seasons')] # Filter out languages with no seasons

            if not languages:
                await query.message.edit_text("No languages available for this series yet.")
                return

            reply_text = (
                f"○ <b>Title:</b> <code>{series_data['title']}</code>\n"
                f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>\n"
                f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>\n"
                f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>\n\n"
                "Select the language you need...!"
            )
            
            poster_to_use = get_series_poster_for_user(series_data['_id']) # Use the updated function
            
            buttons = []
            for lang in languages:
                buttons.append(InlineKeyboardButton(lang['name'], callback_data=f"user_lang:{series_data['_id']}:{lang['name']}"))
            
            buttons_chunked = chunk_buttons(buttons, chunk_size=2)
            reply_markup = InlineKeyboardMarkup(buttons_chunked)

            try:
                media = InputMediaPhoto(media=poster_to_use, caption=reply_text, parse_mode=enums.ParseMode.HTML)
                await client.edit_message_media(
                    chat_id=query.message.chat.id,
                    message_id=query.message.id,
                    media=media,
                    reply_markup=reply_markup
                )
            except pyrogram.errors.MediaEmpty:
                logger.error(f"MediaEmpty error for poster: {poster_to_use} during edit. Falling back to NO_POSTER_FOUND_IMG.")
                media = InputMediaPhoto(
                    media=NO_POSTER_FOUND_IMG,
                    caption=reply_text,
                    parse_mode=enums.ParseMode.HTML
                )
                await client.edit_message_media(
                    chat_id=query.message.chat.id,
                    message_id=query.message.id,
                    media=media,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Error editing message media for series details: {e}")
                await query.message.edit_text("An error occurred while fetching series details.")
        else:
            await query.message.edit_text(
                "Series not found or not published.",
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )

    elif data.startswith("user_lang:"):
        _, series_key, language_name = parts
        series_data = get_series_by_key(series_key)

        if series_data and series_data.get('published', False):
            current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
            seasons = current_lang.get("seasons", []) if current_lang else []
            seasons = [s for s in seasons if s.get('qualities')] # Filter out seasons with no qualities

            if not seasons:
                await query.answer("No seasons available for this language yet.", show_alert=True)
                return

            reply_text = (
                f"○ <b>Title:</b> <code>{series_data['title']}</code>\n"
                f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>\n"
                f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>\n"
                f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>\n"
                f"○ <b>Language:</b> <code>{language_name.title()}</code>\n\n"
                "Select the season you need...!"
            )
            
            buttons = []
            for season in seasons:
                buttons.append(InlineKeyboardButton(season['name'], callback_data=f"user_season:{series_key}:{language_name}:{season['name']}"))
            
            buttons_chunked = chunk_buttons(buttons)
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"spellcheck-{series_key}")]) # Back to language selection
            reply_markup = InlineKeyboardMarkup(buttons_chunked)
            
            await query.message.edit_text(text=reply_text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)

    elif data.startswith("user_season:"):
        _, series_key, language_name, season_name = parts
        series_data = get_series_by_key(series_key)

        if series_data and series_data.get('published', False):
            current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
            current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None) if current_lang else None
            qualities = current_season.get("qualities", []) if current_season else []
            qualities = [q for q in qualities if q.get('link_key')] # Filter out qualities with no links

            if not qualities:
                await query.answer("No qualities available for this season yet.", show_alert=True)
                return

            reply_text = (
                f"○ <b>Title:</b> <code>{series_data['title']}</code>\n"
                f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>\n"
                f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>\n"
                f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>\n"
                f"○ <b>Language:</b> <code>{language_name.title()}</code>\n"
                f"○ <b>Season:</b> <code>{season_name.title()}</code>\n\n"
                "Select the quality you need...!"
            )
            
            buttons = []
            for quality in qualities:
                buttons.append(InlineKeyboardButton(quality['name'], callback_data=f"b:{quality['link_key']}"))
            
            buttons_chunked = chunk_buttons(buttons, chunk_size=2)
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"user_lang:{series_key}:{language_name}")]) # Back to season selection
            reply_markup = InlineKeyboardMarkup(buttons_chunked)
            
            await query.message.edit_text(
                text=reply_text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
