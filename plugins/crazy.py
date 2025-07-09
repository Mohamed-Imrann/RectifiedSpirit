# MultipleFiles/newuicrazy.py

import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, InputMediaPhoto
from imdb import Cinemagoer
import difflib
import re
import shutil
import os
from telegraph import upload_file
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, DB_CHANNEL # Assuming DB_CHANNEL is defined in info.py
from database.users_chats_db import db
from database.crazy_db import (
    add_series, add_series_links, delete_series_and_links,
    add_language, add_season, get_series_name, get_series, get_languages, get_seasons, get_links,
    delete_series_quality_and_links, delete_series_language, add_poster_to_db, delete_series_season,
    add_temp_series_data, get_temp_series_data, clear_temp_series_data, add_temp_quality_links,
    publish_temp_data
)
from plugins.get_file_id import get_file_id
import base64
import hashlib
import uuid

imdb = Cinemagoer()

# Dictionary to store temporary state for admin interactions
# {user_id: {'state': 'waiting_for_quality_name', 'series_key': '...', 'language': '...', 'season': '...'}}
ADMIN_STATES = {}

async def DeleteMessage(msg):
    await asyncio.sleep(40)
    try:
        await msg.delete()
    except Exception as e:
        print(f"Error deleting message: {e}")

def find_most_similar_title(query, search_results):
    titles = [movie.get('title', '').lower() for movie in search_results]
    matches = difflib.get_close_matches(query.lower(), titles, n=1, cutoff=0.6)
    if matches:
        for movie in search_results:
            if movie.get('title', '').lower() == matches[0]:
                return movie
    return None

def extract_parts(text):
    parts = []
    current_part = []
    inside_quotes = False

    # Skip the command itself
    text = text.split(None, 1)[1] if ' ' in text else ''

    for char in text:
        if char == '"':
            inside_quotes = not inside_quotes
            if not inside_quotes and current_part:
                parts.append(''.join(current_part).strip())
                current_part = []
            continue

        if char == ' ' and not inside_quotes:
            if current_part:
                parts.append(''.join(current_part).strip())
                current_part = []
        else:
            current_part.append(char)

    if current_part:
        parts.append(''.join(current_part).strip())

    return parts

async def get_postr(query, bulk=False, id=False):
    if not id:
        search_results = imdb.search_movie(query)
        if not search_results:
            return None
        if bulk:
            return search_results[:10]  # Return top 10 results
        movie = search_results[0]
        movie_id = movie.movieID
    else:
        movie_id = query

    movie = imdb.get_movie(movie_id)
    if not movie:
        return None

    genres = ', '.join(movie.get('genres', [])) if movie.get('genres') else 'N/A'
    poster = movie.get('full-size cover url', 'N/A')
    title = movie.get('title', 'N/A')
    year = movie.get('year', 'N/A')
    rating = movie.get('rating', 'N/A')

    return {
        'title': title,
        'year': year,
        'genres': genres,
        'rating': rating,
        'poster': poster,
        'imdb_id': movie_id
    }

@Client.on_message(filters.command("addseries") & filters.user(ADMINS))
async def add_series_command_new(client, message):
    user_id = message.from_user.id
    query_text = " ".join(message.command[1:])
    if not query_text:
        await message.reply("Please provide a series name. Usage: `/addseries <series_name>`")
        return

    search_results = imdb.search_movie(query_text)
    if not search_results:
        await message.reply("No results found on IMDb.")
        return

    buttons = []
    for result in search_results[:5]:
        movie_title = result.get('title', 'N/A')
        movie_year = result.get('year', 'N/A')
        imdb_id = result.movieID
        buttons.append([
            InlineKeyboardButton(
                f"{movie_title} - {movie_year}",
                callback_data=f"addseries_select#{imdb_id}#{user_id}"
            )
        ])
    buttons.append([InlineKeyboardButton("Cancel", callback_data=f"cancel_addseries#{user_id}")])

    etho = await message.reply(
        "Select a series from the results to add (this will be temporary until published):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    asyncio.create_task(DeleteMessage(etho))


@Client.on_message(filters.command('addquality') & filters.user(ADMINS))
async def add_quality_flow_start(client: Client, message: Message):
    user_id = message.from_user.id
    parts = extract_parts(message.text)

    if len(parts) != 3:
        await message.reply_text(
            "Please follow the command format:\n\n"
            "`/addquality \"Series Name\" \"Language\" \"Season Name\"`\n\n"
            "Example: `/addquality \"The Office\" \"English\" \"Season 1\"`"
        )
        return

    series_name, language, season_name = parts
    series_key = series_name.lower().replace(" ", "")

    # Check if series exists (either permanently or temporarily)
    series_info = get_series_name(series_key)
    if not series_info:
        temp_data = get_temp_series_data(user_id)
        temp_series_info = temp_data.get('series_info', {})
        if temp_series_info.get('key') != series_key:
            await message.reply_text(
                f"Series '{series_name}' not found. Please add it first using `/addseries` or ensure the name is correct."
            )
            return

    # Store state for the user
    ADMIN_STATES[user_id] = {
        'state': 'waiting_for_quality_name',
        'series_key': series_key,
        'language': language,
        'season': season_name,
        'message_id': message.id, # Store original message ID for context
        'chat_id': message.chat.id
    }

    etho = await message.reply_text(
        f"Okay, for **{series_name} - {language} - {season_name}**:\n"
        "Please enter the **quality name** (e.g., '720p HEVC', '1080p x264')."
    )
    asyncio.create_task(DeleteMessage(etho))


@Client.on_message(filters.command('seridel') & filters.user(ADMINS))
async def delete_series_command(client, message):
    if len(message.command) != 2:
        await message.reply_text("Usage: `/seridel <series_key>`")
        return

    series_key = message.command[1]
    delete_series_and_links(series_key)
    await message.reply_text(f"Deleted series and related links with key: `{series_key}`")

@Client.on_message(filters.command('seriview') & filters.user(ADMINS))
async def view_all_series_command(client, message):
    series_list = get_series()
    if not series_list:
        await message.reply_text("No series found.")
        return

    series_keys = [series['key'] for series in series_list]
    total_series = len(series_keys)
    reply_text = f"Total Series Count: {total_series}\nAvailable Series Keys:\n" + "\n".join(series_keys)

    text_limit = 4096
    if len(reply_text) > text_limit:
        file_name = "series_list.txt"
        with open(file_name, "w") as file:
            file.write(reply_text)
        await message.reply_document(file_name)
        os.remove(file_name) # Clean up
    else:
        await message.reply_text(reply_text)

@Client.on_message(filters.command('seridelquality') & filters.user(ADMINS))
async def delete_series_quality_command(client, message):
    parts = extract_parts(message.text)
    if len(parts) != 4:
        await message.reply_text("Usage: `/seridelquality \"Series Name\" \"Language\" \"Season Name\" \"Quality\"`")
        return

    series_name, language, season_name, quality = parts
    series_key = series_name.lower().replace(" ", "")
    delete_series_quality_and_links(series_key, language, season_name, quality)
    await message.reply_text(f"Deleted quality '{quality}' and related links for series: `{series_name}`, language: `{language}`, season: `{season_name}`")

@Client.on_message(filters.command('seridelsea') & filters.user(ADMINS))
async def delete_series_season_command(client, message):
    parts = extract_parts(message.text)
    if len(parts) != 3:
        await message.reply_text("Usage: `/seridelsea \"Series Name\" \"Language\" \"Season Name\"`")
        return

    series_name, language, season_name = parts
    series_key = series_name.lower().replace(" ", "")
    success = delete_series_season(series_key, language, season_name)

    if success:
        await message.reply_text(f"Deleted season '{season_name}' and related links for series '{series_name}' in language '{language}'.")
    else:
        await message.reply_text(f"Failed to delete season '{season_name}'. Ensure the series, language, and season exist.")

@Client.on_message(filters.command('seridelang') & filters.user(ADMINS))
async def delete_series_language_command(client, message):
    parts = extract_parts(message.text)
    if len(parts) != 2:
        await message.reply_text("Usage: `/seridelang \"Series Name\" \"Language\"`")
        return

    series_name, language = parts
    series_key = series_name.lower().replace(" ", "")
    delete_series_language(series_key, language)
    await message.reply_text(f"Deleted language '{language}' and related links for series: `{series_name}`")

IMGBB_API_KEY = "5c789a0958af3fadc1db4fea0796576d" # Replace with your actual ImgBB API key

@Client.on_message(filters.command("addposter") & filters.user(ADMINS))
async def add_poster(client, message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("Usage: `/addposter <series_key>`")
        return

    series_key = parts[1].strip().lower()

    replied = message.reply_to_message
    if not replied or not (replied.photo or replied.video):
        await message.reply_text("Reply to a photo or video to set it as the poster.")
        return

    file_info = get_file_id(replied)
    if not file_info:
        await message.reply_text("Unsupported media type for poster.")
        return

    _t = os.path.join(TMP_DOWNLOAD_DIRECTORY, series_key)
    if not os.path.isdir(_t):
        os.makedirs(_t)
    _t += "/"

    download_location = None
    try:
        download_location = await replied.download(_t)

        with open(download_location, "rb") as file:
            response = requests.post(
                "https://api.imgbb.com/1/upload",
                params={"key": IMGBB_API_KEY},
                files={"image": file}
            )
            response_data = response.json()

        if response.status_code == 200 and "data" in response_data:
            poster_url = response_data["data"]["url"]
            if add_poster_to_db(series_key, poster_url):
                await message.reply(
                    f"Poster added successfully for series key: `{series_key}`\nLink: {poster_url}"
                )
            else:
                await message.reply("Failed to add poster. Please check if the series key is correct.")
        else:
            error_message = response_data.get("error", {}).get("message", "Unknown error")
            await message.reply(f"Failed to upload poster: {error_message}")
    except Exception as e:
        await message.reply(f"Error: {e}")
    finally:
        if download_location and os.path.exists(download_location):
            os.remove(download_location)
        if os.path.exists(_t) and os.path.isdir(_t):
            shutil.rmtree(_t, ignore_errors=True)


@Client.on_message(filters.command('stats') & filters.user(ADMINS))
async def get_ststs(bot, message):
    rju = await message.reply('👀')
    users = await db.total_users_count()
    chats = await db.total_chat_count()
    series_list = get_series()
    series_keys = [series['key'] for series in series_list]
    total_series = len(series_keys)
    await rju.edit(
        text=f"Total Series: {total_series}\nUsers: {users}\n Chats: {chats}",
        parse_mode=enums.ParseMode.HTML
    )

