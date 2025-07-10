#Credits Only To Abhishek
#None Of The People In The Repository Are Coding But Suggestions
#t.me/Abhishekissac
import re
import pyrogram 
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, Message
from info import ADMINS, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG, CUSTOM_FILE_CAPTION, BATCH_FILE_CAPTION, PROTECT_CONTENT, PUBLIC_FILE_STORE, PICS
from database.crazy_db import (
    get_series, get_links, get_series_name, get_languages, get_seasons, get_poster_manuel
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters
)
from database.ia_filterdb import get_search_results
from utils import temp, get_readable_file_size, is_subscribed, get_poster, get_settings, save_group_settings
from imdb import Cinemagoer
import asyncio
import difflib
import logging
import random

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

requestor = {}
imdb = Cinemagoer()

async def DeleteMessage(msg):
    await asyncio.sleep(600)
    await msg.delete()

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def chunk_buttons(buttons, chunk_size=3):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

def find_most_similar_title(query, search_results):
    titles = [movie.get('title', '').lower() for movie in search_results]
    matches = difflib.get_close_matches(query.lower(), titles, n=1, cutoff=0.6)
    if matches:
        for movie in search_results:
            if movie.get('title', '').lower() == matches[0]:
                return movie
    return None


async def alert_admins(client, series_key):
    alert_message = f"⚠️ Failed to fetch poster for series: <code>{series_key}</code>"
    async for admin_id in ADMINS:
        await client.send_message(chat_id=admin_id, text=alert_message, parse_mode=enums.ParseMode.HTML)

def get_movie_poster(series_key):
    poster_url = get_poster_manuel(series_key)
    if not poster_url:
        series = get_series_name(series_key)
        if series:
            series_title = series.get('title', '')
            search_results = imdb.search_movie(series_title.lower(), results=10)
            if search_results:
                movie = find_most_similar_title(series_title, search_results)
                poster_url = movie.get('full-size cover url') if movie else None
    return poster_url

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
    series_infos = get_series()
    series_keys = [series['key'] for series in series_infos]
    series_names = [series['title'] for series in series_infos]

    series_key = None
    series_name = None

    if text in series_keys:
        series_key = text
    elif text in series_names:
        series_name = text
    else:
        close_matches = find_close_matches(text, series_names)
        if not close_matches:
            first_word = text.split()[0]
            close_matches = [name for name in series_names if name.lower().startswith(first_word.lower())]
        
        if close_matches:
            buttons = [
                InlineKeyboardButton(match, callback_data=f"spellcheck-{series_infos[series_names.index(match)]['key']}")
                for match in close_matches
            ]
            buttons_chunked = chunk_buttons(buttons, chunk_size=1)
            reply_markup = InlineKeyboardMarkup(buttons_chunked)
            etho = await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else None
            requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))
            return

    if series_name:
        series = get_series_name(series_name)
        if not series:
            return
        series_key = series.get('key')
    
    if series_key:
        series = get_series_name(series_key)
        if not series:
            return

        languages = series.get("languages", [])
        reply_text = (
            f"○ <b>Title:</b> <code>{series['title']}</code>\n○ <b>Released On:</b> <code>{series['released_on']}</code>\n○ <b>Genre:</b> <code>{series['genre']}</code>\n○ <b>Rating:</b> <code>{series['rating']}</code>\n\n"
            "Available Languages:\n"
        )
        poster_url = get_movie_poster(series_key)
        buttons = [InlineKeyboardButton(lang, callback_data=f"{series_key}-{lang.lower().replace(' ', '')}") for lang in languages]
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
                reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
                requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                asyncio.create_task(DeleteMessage(etho))
            else:
                etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG, caption=reply_text, reply_markup=reply_markup)
                reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
                requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                asyncio.create_task(DeleteMessage(etho))
            logger.info("postertrying")
        except pyrogram.errors.MediaEmpty:
            await alert_admins(client, series_key)
            etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG, caption=reply_text, reply_markup=reply_markup)
            reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.chat.id
            requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
            asyncio.create_task(DeleteMessage(etho))


@Client.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    data = query.data
    parts = data.split("-")
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
        series = get_series_name(series_key)
        if series:
            poster_url = get_movie_poster(series_key)
            languages = series.get("languages", [])
            reply_text = (
                f"○ <b>Title:</b> <code>{series['title']}</code>\n"
                f"○ <b>Released On:</b> <code>{series['released_on']}</code>\n"
                f"○ <b>Genre:</b> <code>{series['genre']}</code>\n"
                f"○ <b>Rating:</b> <code>{series['rating']}</code>\n\n"
                "Available Languages:\n"
            )
            buttons = [
                InlineKeyboardButton(lang, callback_data=f"{series_key}-{lang.lower().replace(' ', '')}") 
                for lang in languages
            ]
            buttons_chunked = chunk_buttons(buttons, chunk_size=2)
            reply_markup = InlineKeyboardMarkup(buttons_chunked)

            try:
                if poster_url:
                    media = InputMediaPhoto(media=poster_url, caption=reply_text, parse_mode=enums.ParseMode.HTML)
                else:
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
            except pyrogram.errors.MediaEmpty:
                await alert_admins(client, series_key)
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
        else:
            await query.message.edit_text(
                "Series not found.",
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )

    elif len(parts) == 2:
        series_key, language = parts
        series = get_series_name(series_key)

        if series:
            seasons = get_seasons(series['key'])
            reply_text = (
                f"○ <b>Title:</b> <code>{series['title'].title()}</code>\n"
                f"○ <b>Released On:</b> <code>{series['released_on']}</code>\n"
                f"○ <b>Genre:</b> <code>{series['genre']}</code>\n"
                f"○ <b>Rating:</b> <code>{series['rating']}</code>\n"
                f"○ <b>Language:</b> <code>{language.title()}</code>\n"
                "Available Seasons:\n"
            )
            buttons = [
                InlineKeyboardButton(season, callback_data=f"{series_key}-{language}-{season.lower().replace(' ', '')}") 
                for season in seasons
            ]
            buttons_chunked = chunk_buttons(buttons)
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"spellcheck-{series_key}")])
            reply_markup = InlineKeyboardMarkup(buttons_chunked)
            await query.message.edit_text(text=reply_text, reply_markup=reply_markup)

    elif len(parts) == 3:
        series_key, language, season = parts
        series = get_series_name(series_key)
        links = get_links(f"{series_key.lower().replace(' ', '')}-{language}-{season}")

        if links:
            buttons = [InlineKeyboardButton(quality, callback_data=f"b:{link}") for quality, link in links.items()]
            buttons_chunked = chunk_buttons(buttons, chunk_size=2)
            if buttons_chunked:
                buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"{series_key}-{language}")])
                reply_markup = InlineKeyboardMarkup(buttons_chunked)
                await query.message.edit_text(
                    text=(
                        f"○ <b>Title:</b> <code>{series['title'].title()}</code>\n"
                        f"○ <b>Released On:</b> <code>{series['released_on']}</code>\n"
                        f"○ <b>Genre:</b> <code>{series['genre']}</code>\n"
                        f"○ <b>Rating:</b> <code>{series['rating']}</code>\n"
                        f"○ <b>Language:</b> <code>{language.title()}</code>\n"
                        f"○ <b>Season:</b> <code>{season.replace('-', ' ').title()}</code>\n"
                        "Select the quality you need...!"
                    ),
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML
                )
            else:
                await query.message.edit_text(
                    text="No qualities found for this season and language.",
                    disable_web_page_preview=True,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("Back", callback_data=f"{series_key}-{language}")]]
                    ),
                    parse_mode=enums.ParseMode.HTML
                )
        else:
            await query.message.edit_text(
                text="No links found for the selected season and language.",
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Back", callback_data=f"{series_key}-{language}")]]
                ),
                parse_mode=enums.ParseMode.HTML
            )

from Script import script

@Client.on_message(filters.text & filters.private & ~filters.edited & ~filters.command(["start", "help", "about", "stats", "restart", "totalusers", "viewall", "deleteseries", "deleteallseries", "gfilters", "gdel", "gdelall", "genlink", "get_file_id", "admin_ui"]))
async def pm_filter(client, message: Message):
    if not await is_subscribed(client, message):
        # This check is already handled in bot.py for force subscribe channels
        # If you have a general AUTH_CHANNEL for PM, you can add it here.
        # For now, assuming force subscribe is handled at bot start.
        pass

    query = message.text.strip()
    files, offset, total_results = await get_search_results(query, file_type="document", max_results=10)
    
    if files:
        reply_markup = []
        for file in files:
            reply_markup.append([InlineKeyboardButton(file.file_name, callback_data=f"files#{file.file_id}")])
        
        if offset != "":
            reply_markup.append([InlineKeyboardButton("Next ➡️", callback_data=f"next_{offset}_{query}")])
        
        reply_markup.append([InlineKeyboardButton("Close", callback_data="close_data")])
        
        await message.reply_text(
            f"Found {total_results} results for '{query}':",
            reply_markup=InlineKeyboardMarkup(reply_markup)
        )
    else:
        # Spell check logic
        await message.reply_photo(
            photo=random.choice(PICS),
            caption=script.SPELL_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Close", callback_data="close_data")]
            ])
        )
