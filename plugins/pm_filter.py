import pyrogram 
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from info import ADMINS
from database.crazy_db import (
    get_series, get_links, get_series_name, get_languages, get_seasons, get_poster_manuel
)
from utils import temp
from imdb import Cinemagoer
import asyncio
import difflib
import logging
import random

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

SPELL = (
    'https://envs.sh/kJj.jpg'
).split()

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

DEFAULT_POSTER = "https://envs.sh/kJK.jpg"

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
    await series_filter(client, message)


async def series_filter(client, message):
    text = message.text.strip()
    series_infos = get_series()
    user_id = str(message.from_user.id)
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
                InlineKeyboardButton(match, callback_data=f"spellcheck·{series_infos[series_names.index(match)]['key']}·{user_id}")
                for match in close_matches
            ]
            buttons_chunked = chunk_buttons(buttons, chunk_size=2)
            reply_markup = InlineKeyboardMarkup(buttons_chunked)
            etho = await message.reply_photo(photo=random.choice(SPELL), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
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
        buttons = [InlineKeyboardButton(lang, callback_data=f"{series_key}·{lang.lower().replace(' ', '')}·{user_id}") for lang in languages]
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        try:
            if poster_url:
                etho = await message.reply_photo(photo=poster_url, caption=reply_text, reply_markup=reply_markup)
            else:
                etho = await message.reply_photo(photo=DEFAULT_POSTER, caption=reply_text, reply_markup=reply_markup)
            asyncio.create_task(DeleteMessage(etho))
        except pyrogram.errors.MediaEmpty:
            await alert_admins(client, series_key)
            etho = await message.reply_photo(photo=DEFAULT_POSTER, caption=reply_text, reply_markup=reply_markup)
            asyncio.create_task(DeleteMessage(etho))


@Client.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    data = query.data
    user_id = str(query.from_user.id)
    parts = data.split("·")
    if data == "close_data":
        await query.message.delete()
    elif data == "pages":
        await query.answer()
    elif data.startswith("gt:"):
        start_parameter = data.split(":")[1]
        try:
            teststring = f"https://t.me/{temp.U_NAME}?start={start_parameter}"
            print(teststring)
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={start_parameter}")
        except pyrogram.errors.exceptions.bad_request_400.UrlInvalid:
            await query.answer("Invalid URL provided.", show_alert=True)
    elif data.startswith("get:"):
        start_parameter = data.split(":")[1]
        try:
            teststringt = f"https://t.me/{temp.U_NAME}?start={start_parameter}"
            print(teststringt)
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={start_parameter}")
        except pyrogram.errors.exceptions.bad_request_400.UrlInvalid:
            await query.answer("Invalid URL provided.", show_alert=True)
    elif data.startswith("spellcheck·"):
        series_key = parts[1]
        query_user_id = parts[2]
        if query_user_id != user_id:
            await query.answer("Request Yourself", show_alert=True)
            return

        series = get_series_name(series_key)
        if series:
            poster_url = get_movie_poster(series_key)
            languages = series.get("languages", [])
            reply_text = (
                f"○ <b>Title:</b> <code>{series['title']}</code>\n○ <b>Released On:</b> <code>{series['released_on']}</code>\n○ <b>Genre:</b> <code>{series['genre']}</code>\n○ <b>Rating:</b> <code>{series['rating']}</code>\n\n"
                "Available Languages:\n"
            )
            buttons = [InlineKeyboardButton(lang, callback_data=f"{series_key}·{lang.lower().replace(' ', '')}·{user_id}") for lang in languages]
            buttons_chunked = chunk_buttons(buttons, chunk_size=2)
            reply_markup = InlineKeyboardMarkup(buttons_chunked)
            try:
                if poster_url:
                    await query.message.edit_media(media=InputMediaPhoto(poster_url), reply_markup=reply_markup)
                else:
                    await query.message.edit_media(media=InputMediaPhoto(DEFAULT_POSTER), reply_markup=reply_markup)
                await query.message.edit_text(text=reply_text, reply_markup=reply_markup)
            except pyrogram.errors.MediaEmpty:
                await alert_admins(client, series_key)
                await query.message.edit_media(media=InputMediaPhoto(DEFAULT_POSTER), reply_markup=reply_markup)
                await query.message.edit_text(text=reply_text, reply_markup=reply_markup)
        else:
            await query.message.edit_text(text="Series not found.", disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
    else:
        if len(parts) == 3:
            series_key, language, query_user_id = parts
            if query_user_id != user_id:
                await query.answer("Request Yourself", show_alert=True)
                return

            series = get_series_name(series_key)
            if series:
                seasons = get_seasons(series['key'])
                reply_text = (
                    f"○ <b>Title:</b> <code>{series['title'].title()}</code>\n○ <b>Released On:</b> <code>{series['released_on']}</code>\n○ <b>Genre:</b> <code>{series['genre']}</code>\n○ <b>Rating:</b> <code>{series['rating']}</code>\n"
                    f"<blockquote>▪️<b>Language:</b> <code>{language.title()}</code></blockquote>\n"
                    "Available Seasons:\n"
                )
                
                buttons = [InlineKeyboardButton(season, callback_data=f"{series_key}·{language}·{season.lower().replace(' ', '')}·{user_id}") for season in seasons]
                buttons_chunked = chunk_buttons(buttons)
                buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"spellcheck-{series_key}-{user_id}")])
                reply_markup = InlineKeyboardMarkup(buttons_chunked)
                await query.message.edit_text(
                    text=reply_text,
                    reply_markup=reply_markup
                )
        elif len(parts) == 4:
            series_key, language, season, query_user_id = parts
            if query_user_id != user_id:
                await query.answer("Request Yourself", show_alert=True)
                return

            series = get_series_name(series_key)
            links = get_links(f"{series_key.lower().replace(' ', '')}·{language}·{season}")
            if links:
                buttons = [
                    InlineKeyboardButton(quality, callback_data=f"gt:{link}")
                    for quality, link in links.items()
                ]
                buttons_chunked = chunk_buttons(buttons, chunk_size=2)
                if buttons_chunked:
                    buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"{series_key}·{language}·{user_id}")])
                    reply_markup = InlineKeyboardMarkup(buttons_chunked)
                    await query.message.edit_text(
                        text=(
                            f"○ <b>Title:</b> <code>{series['title'].title()}</code>\n"
                            f"○ <b>Released On:</b> <code>{series['released_on']}</code>\n"
                            f"○ <b>Genre:</b> <code>{series['genre']}</code>\n"
                            f"○ <b>Rating:</b> <code>{series['rating']}</code>\n"
                            f"<blockquote><b>▪️Language:</b> <code>{language.title()}</code></blockquote>\n"
                            f"<blockquote><b>▪️Season:</b> <code>{season.replace('-', ' ').title()}</code></blockquote>\n"
                            "Select the quality you need...!"
                        ),
                        reply_markup=reply_markup,
                        disable_web_page_preview=True,
                        parse_mode=enums.ParseMode.HTML
                    )
                else:
                    await query.message.edit_text(
                        text="No qualities available for this language.",
                        disable_web_page_preview=True,
                        parse_mode=enums.ParseMode.HTML
                    )
            else:
                await query.message.edit_text(
                    text="No links found for the selected season and language.",
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML
)
    
