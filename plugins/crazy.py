# MultipleFiles/newuicrazy.py

import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, InputMediaPhoto
import re
import shutil
import os
from telegraph import upload_file
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, DB_CHANNEL, TMDB_API_KEY, TMDB_IMAGE_BASE_URL # NEW IMPORTS
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
import requests
import tmdbsimple as tmdb # NEW IMPORT

tmdb.API_KEY = TMDB_API_KEY # Initialize TMDB API key

# Dictionary to store temporary state for admin interactions
# {user_id: {'state': 'waiting_for_quality_name', 'series_key': '...', 'language': '...', 'season': '...'}}
ADMIN_STATES = {} # This will be imported by newuipm_filter.py

async def DeleteMessage(msg):
    await asyncio.sleep(40)
    try:
        await msg.delete()
    except Exception as e:
        print(f"Error deleting message: {e}")

def find_most_similar_title(query, search_results):
    """
    Finds the most similar title from TMDB search results.
    TMDB search results have 'title' for movies and 'name' for TV shows.
    """
    titles = []
    for item in search_results:
        if item.get('media_type') == 'movie':
            titles.append(item.get('title', '').lower())
        elif item.get('media_type') == 'tv':
            titles.append(item.get('name', '').lower())
    
    matches = difflib.get_close_matches(query.lower(), titles, n=1, cutoff=0.6)
    if matches:
        for item in search_results:
            if item.get('media_type') == 'movie' and item.get('title', '').lower() == matches[0]:
                return item
            elif item.get('media_type') == 'tv' and item.get('name', '').lower() == matches[0]:
                return item
    return None

async def get_movie_details_from_tmdb(query=None, tmdb_id=None, media_type='multi', bulk=False):
    """
    Fetches movie/series details from TMDB.
    :param query: Search query (title/name) if tmdb_id is None.
    :param tmdb_id: If provided, fetches details for a specific TMDB ID.
    :param media_type: 'movie', 'tv', or 'multi' (for search).
    :param bulk: If True, returns a list of search results.
    :return: Dictionary of movie/series details or list of search results.
    """
    try:
        if tmdb_id:
            if media_type == 'movie':
                details = tmdb.Movies(tmdb_id).info()
            elif media_type == 'tv':
                details = tmdb.TV(tmdb_id).info()
            else:
                # This case should ideally not happen if media_type is correctly passed
                # from a multi-search result.
                print(f"Warning: Attempted to get details for unknown media_type: {media_type}")
                return None

            poster_path = details.get('poster_path')
            poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else None

            return {
                'title': details.get('title') or details.get('name', 'N/A'), # 'title' for movies, 'name' for TV
                'released_on': details.get('release_date') or details.get('first_air_date', 'N/A'),
                'genre': ', '.join([g['name'] for g in details.get('genres', [])]) if details.get('genres') else 'N/A',
                'rating': details.get('vote_average', 'N/A'),
                'poster': poster_url,
                'tmdb_id': tmdb_id,
                'media_type': media_type # Store media type for later use
            }
        else:
            search = tmdb.Search()
            response = search.multi(query=query) # Searches movies, TV shows, and people

            if not response['results']:
                return None

            if bulk:
                # Filter out people and return top results
                return [
                    item for item in response['results']
                    if item.get('media_type') in ['movie', 'tv']
                ][:10] # Limit to top 10 relevant results

            # Find the most similar title from multi-search results
            best_match = find_most_similar_title(query, response['results'])
            if best_match:
                # Recursively call to get full details for the best match
                return await get_movie_details_from_tmdb(
                    tmdb_id=best_match['id'],
                    media_type=best_match['media_type']
                )
            return None

    except Exception as e:
        print(f"Error fetching TMDB details: {e}")
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

@Client.on_message(filters.command("addseries") & filters.user(ADMINS))
async def add_series_command_new(client, message):
    user_id = message.from_user.id
    query_text = " ".join(message.command[1:])
    if not query_text:
        await message.reply("Please provide a series name. Usage: `/addseries <series_name>`")
        return

    # Use the TMDB utility function to search
    search_results = await get_movie_details_from_tmdb(query=query_text, bulk=True)
    if not search_results:
        await message.reply("No results found on TMDB.")
        return

    buttons = []
    for result in search_results[:5]: # Limit to top 5 for display
        title = result.get('title') or result.get('name', 'N/A')
        year = result.get('release_date', '')[:4] or result.get('first_air_date', '')[:4] or 'N/A'
        tmdb_id = result.get('id')
        media_type = result.get('media_type') # 'movie' or 'tv'

        buttons.append([
            InlineKeyboardButton(
                f"{title} - {year} ({media_type.upper()})",
                callback_data=f"addseries_select#{tmdb_id}#{media_type}#{user_id}"
            )
        ])
    buttons.append([InlineKeyboardButton("Cancel", callback_data=f"cancel_addseries#{user_id}")])

    etho = await message.reply(
        "Select a series/movie from the results to add (this will be temporary until published):",
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

