import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message 
from imdb import Cinemagoer
import difflib
import asyncio
import re
import shutil
import os
from telegraph import upload_file
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, IMGBB_API_KEY, TMDB_API_KEY
from database.users_chats_db import db
from database.crazy_db import (
    add_series, add_series_links, delete_series_and_links, delete_all_series_and_links,
    add_language, add_season, get_series_name, get_series, get_languages, get_seasons, get_links,
    delete_series_quality_and_links, delete_series_language, add_poster_to_db, delete_series_season
)
from plugins.get_file_id import get_file_id
import base64
import hashlib
import requests
import uuid

imdb = Cinemagoer()

async def DeleteMessage(msg):
    await asyncio.sleep(40)
    await msg.delete()
    
def find_most_similar_title(query, search_results):
    titles = [movie.get('title', '').lower() for movie in search_results]
    matches = difflib.get_close_matches(query.lower(), titles, n=1, cutoff=0.6)
    if matches:
        for movie in search_results:
            if movie.get('title', '').lower() == matches[0]:
                return movie
    return None

@Client.on_message(filters.command('seriadd') & filters.user(ADMINS))
async def add_series_command(client, message):
    chat_id = message.chat.id
    series_data = {}

    # Extract series title from command
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await client.send_message(chat_id, "Usage: /seriadd <series_title>")
        return

    series_title = parts[1]
    series_key = series_title.lower().replace(" ", "").replace("-", ":")

    series_data['title'] = series_title
    series_data['key'] = series_key

    # Function to ask for details and handle /imp command
    async def ask_for_detail(prompt, detail_key):
        detail_msg = await client.ask(chat_id, prompt, filters=filters.text, timeout=300)
        if detail_msg.text.lower() == "/imp":
            movieid = imdb.search_movie(series_title.lower(), results=2)
            if movieid:
                movie = find_most_similar_title(series_title, movieid)
                if movie:
                    movie = imdb.get_movie(movie.movieID)
                    series_data[detail_key] = movie.get(detail_key, 'N/A')
                else:
                    series_data[detail_key] = 'N/A'
            else:
                series_data[detail_key] = 'N/A'
        else:
            series_data[detail_key] = detail_msg.text if detail_msg.text else 'N/A'

    # Ask for details
    await ask_for_detail("Please enter the release date (or type /imp to get from IMDb):", 'released_on')
    await ask_for_detail("Please enter the genre (or type /imp to get from IMDb):", 'genre')
    await ask_for_detail("Please enter the rating (or type /imp to get from IMDb):", 'rating')

    add_series(series_data)

    # Ask for languages and other details
    languages_msg = await client.ask(chat_id, "Please enter the available languages (comma separated) (or type /skip to skip):", filters=filters.text, timeout=300)
    if languages_msg.text.lower() != "/skip":
        languages = [lang.strip().capitalize() for lang in languages_msg.text.split(",")]
        for language in languages:
            add_language(series_key, language)

        for language in languages:
            while True:
                season_name_msg = await client.ask(chat_id, f"Enter season number for {language} (e.g., '5' for 'Season 5') (or type /finish to finish):", filters=filters.text, timeout=300)
                if season_name_msg.text.lower() == "/finish":
                    break
                season_number = season_name_msg.text.strip()
                season_name = f"Season {season_number}"
                add_season(series_key, season_name)

                quality_msg = await client.ask(chat_id, "Enter quality (e.g., '720p H.265'):")
                if not quality_msg.text:
                    await message.reply_text("Quality is required.")
                    return
                quality = quality_msg.text

                link_msg = await client.ask(chat_id, f"Enter link for {quality}:")
                if not link_msg.text:
                    await message.reply_text("Link is required.")
                    return
                link = link_msg.text

                links = {quality: link}
                add_series_links(f"{series_key}-{language.lower().replace(' ', '')}-{season_name.lower().replace(' ', '')}", links)

    await client.send_message(chat_id, f"Series {series_data['title']} added successfully.")

def extract_parts(text):
    parts = []
    current_part = []
    inside_quotes = False

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

    return parts[1:]  # Skip the command itself

callback_data_store = {}

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

async def get_tmdb_info(query, bulk=False, id=False, media_type='tv'):
    """
    Enhanced TMDB function similar to get_postr from IMDb version
    - query: search term or TMDB ID
    - bulk: return multiple results (like IMDb search)
    - id: treat query as TMDB ID
    - media_type: 'tv' or 'movie'
    """
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_API_KEY}"
    }

    try:
        if not id:
            # Search mode - similar to IMDb search
            if bulk:
                # Return multiple results for selection
                search_results_tv = []
                search_results_movie = []
                
                # Search TV shows
                url_tv = f"{TMDB_BASE_URL}/search/tv"
                response_tv = requests.get(url_tv, headers=headers, params={"query": query})
                if response_tv.status_code == 200:
                    data_tv = response_tv.json()
                    for item in data_tv.get('results', [])[:3]:  # Limit to 3 results
                        if item.get('name'):
                            search_results_tv.append({
                                'title': item.get('name'),
                                'year': item.get('first_air_date', '').split('-')[0] if item.get('first_air_date') else 'N/A',
                                'tmdb_id': item.get('id'),
                                'media_type': 'tv'
                            })
                
                # Search Movies
                url_movie = f"{TMDB_BASE_URL}/search/movie"
                response_movie = requests.get(url_movie, headers=headers, params={"query": query})
                if response_movie.status_code == 200:
                    data_movie = response_movie.json()
                    for item in data_movie.get('results', [])[:3]:  # Limit to 3 results
                        if item.get('title'):
                            search_results_movie.append({
                                'title': item.get('title'),
                                'year': item.get('release_date', '').split('-')[0] if item.get('release_date') else 'N/A',
                                'tmdb_id': item.get('id'),
                                'media_type': 'movie'
                            })
                
                # Combine results (TV shows first, then movies)
                all_results = search_results_tv + search_results_movie
                return all_results[:5]  # Return max 5 results total
            
            else:
                # Single result mode
                url = f"{TMDB_BASE_URL}/search/{media_type}"
                response = requests.get(url, headers=headers, params={"query": query})
                if response.status_code == 200:
                    data = response.json()
                    if data.get('results'):
                        first_result = data['results'][0]
                        tmdb_id = first_result.get('id')
                        return await get_tmdb_info(tmdb_id, id=True, media_type=media_type)
                return None
        else:
            # ID mode - get full details using TMDB ID
            url = f"{TMDB_BASE_URL}/{media_type}/{query}"
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                
                # Get genres (limit to 3)
                genres = [g['name'] for g in data.get('genres', [])][:3]
                
                # Get poster URL
                poster_path = data.get('poster_path')
                poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else 'N/A'
                
                # Get title and year based on media type
                if media_type == 'tv':
                    title = data.get('name', 'N/A')
                    year = data.get('first_air_date', '').split('-')[0] if data.get('first_air_date') else 'N/A'
                else:  # movie
                    title = data.get('title', 'N/A')
                    year = data.get('release_date', '').split('-')[0] if data.get('release_date') else 'N/A'
                
                return {
                    'title': title,
                    'year': year,
                    'genres': ', '.join(genres) if genres else 'N/A',
                    'rating': data.get('vote_average', 'N/A'),
                    'poster': poster_url,
                    'tmdb_id': data.get('id'),
                    'media_type': media_type,
                    'url': f'https://www.themoviedb.org/{media_type}/{data.get("id")}'
                }
            return None

    except Exception as e:
        print(f"TMDB Error: {e}")
        return None

@Client.on_message(filters.command('quality') & filters.user(ADMINS))
async def add_quality_link(client: Client, message: Message):
    parts = extract_parts(message.text)

    if len(parts) < 5:
        k = await message.reply_text(
            "Please follow the command format:\n\n"
            "/quality \"Series Name\" \"Language\" \"Season Name\" \"Quality\" \"Download Link\""
        )
        asyncio.create_task(DeleteMessage(k))
        return

    k = await message.reply_text("Processing Request...")

    series_name, language, season_name, quality, link = parts
    series_key = series_name.lower().replace(" ", "").replace("-", "~")

    series = get_series_name(series_key)
    if not series:
        # Search on TMDB (bulk mode for multiple results)
        search_results = await get_tmdb_info(series_name, bulk=True)
        if not search_results:
            await k.edit_text("No results found on TMDB for the provided series name.")
            return

        # Create buttons for user to select the correct series
        buttons = []
        for item in search_results:
            item_title = item.get('title', 'N/A')
            item_year = item.get('year', 'N/A')
            tmdb_id = item.get('tmdb_id')
            media_type = item.get('media_type')

            # Store data in the callback store
            unique_id = str(uuid.uuid4())
            callback_data_store[unique_id] = {
                'tmdb_id': tmdb_id,
                'language': language,
                'season_name': season_name,
                'quality': quality,
                'link': link,
                'media_type': media_type
            }

            button = InlineKeyboardButton(
                text=f"{item_title} ({item_year}) - {media_type.upper()}",
                callback_data=f"tmdb#{unique_id}"
            )
            buttons.append([button])

        reply_markup = InlineKeyboardMarkup(buttons)
        await k.edit_text(
            f"Multiple results found for '{series_name}'. Please select the correct series:",
            reply_markup=reply_markup
        )
        asyncio.create_task(DeleteMessage(k))
        return

    # If series found in DB, proceed directly
    await continue_add_quality_link(client, message, series_key, language, season_name, quality, link)

@Client.on_callback_query(filters.regex(r"^tmdb#"))
async def tmdb_selection_callback(client: Client, callback_query):
    data = callback_query.data.split("#")
    unique_id = data[1]

    if unique_id not in callback_data_store:
        await callback_query.message.reply("Invalid or expired callback data.")
        return

    stored_data = callback_data_store.pop(unique_id)
    tmdb_id = stored_data['tmdb_id']
    language = stored_data['language']
    season_name = stored_data['season_name']
    quality = stored_data['quality']
    link = stored_data['link']
    media_type = stored_data['media_type']

    # Get full details using TMDB ID
    movie_details = await get_tmdb_info(tmdb_id, id=True, media_type=media_type)
    if not movie_details:
        await callback_query.message.reply("Failed to retrieve TMDB data.")
        return

    series_key = movie_details.get('title').lower().replace(" ", "").replace("-", "")

    series_data = {
        'title': movie_details.get('title', 'N/A'),
        'released_on': movie_details.get('year', 'N/A'),
        'genre': movie_details.get('genres', 'N/A'),
        'rating': movie_details.get('rating', 'N/A'),
        'key': series_key,
        'tmdb_id': tmdb_id,
        'media_type': media_type
    }

    add_series(series_data)
    
    # Add poster to database if available
    if movie_details.get('poster') != 'N/A':
        add_poster_to_db(series_key, movie_details.get('poster'))

    msg = await callback_query.message.reply_text(
        f"Series added successfully!\n\n"
        f"**Title:** {movie_details.get('title', 'N/A')}\n"
        f"**Year:** {movie_details.get('year', 'N/A')}\n"
        f"**Genres:** {movie_details.get('genres', 'N/A')}\n"
        f"**Rating:** {movie_details.get('rating', 'N/A')}\n"
        f"**Media Type:** {media_type.upper()}\n"
        f"**Poster URL:** {movie_details.get('poster', 'N/A')}"
    )
    asyncio.create_task(DeleteMessage(msg))
    await continue_add_quality_link(client, callback_query.message, series_key, language, season_name, quality, link)

async def continue_add_quality_link(client, message, series_key, language, season_name, quality, link):
    season_name = f"{season_name}"
    
    existing_languages = get_languages(series_key)
    if language not in existing_languages:
        add_language(series_key, language)

    existing_seasons = get_seasons(series_key)
    if season_name not in existing_seasons:
        add_season(series_key, season_name)

    link_key = f"{series_key}-{language.lower().replace(' ', '')}-{season_name.lower().replace(' ', '')}"
    
    links = get_links(link_key)
    if links is None:
        links = {}
    links[quality] = link

    add_series_links(link_key, links)

    msg = await message.reply_text(
        f"Link added successfully:\n\n"
        f"**Series:** {series_key.replace('-', ' ').title()}\n"
        f"**Language:** {language}\n"
        f"**Season:** {season_name}\n"
        f"**Quality:** {quality}\n"
        f"**Link:** {link}"
    )
    asyncio.create_task(DeleteMessage(msg))

@Client.on_message(filters.command('seridel') & filters.user(ADMINS))
async def delete_series_command(client, message):
    if len(message.command) != 2:
        await message.reply_text("Usage: /seridel series_key")
        return

    series_key = message.command[1]
    delete_series_and_links(series_key)
    await message.reply_text(f"Deleted series and related links with key: {series_key}")

@Client.on_message(filters.command('seriview') & filters.user(ADMINS))
async def view_all_series_command(client, message):
    series_list = get_series()
    if not series_list:
        await message.reply_text("No series found.")
        return
    
    series_keys = [series['key'] for series in series_list]
    total_series = len(series_keys)
    reply_text = f"Total Series Count: {total_series}\nAvailable Series Keys:\n" + "\n".join(series_keys)

    # Telegram's message text limit is 4096 characters
    text_limit = 4096
    if len(reply_text) > text_limit:
        # If the text is too long, write it to a file
        file_name = "series_list.txt"
        with open(file_name, "w") as file:
            file.write(reply_text)
        
        # Send the file
        await message.reply_document(file_name)
    else:
        # Send the reply text
        await message.reply_text(reply_text)

@Client.on_message(filters.command('seridelquality') & filters.user(ADMINS))
async def delete_series_quality_command(client, message):
    if len(message.command) != 5:
        await message.reply_text("Usage: /seridelquality series_key 'Language' 'Season Name' 'Quality'")
        return

    series_key, language, season_name, quality = message.command[1], message.command[2], message.command[3], message.command[4]
    delete_series_quality_and_links(series_key, language, season_name, quality)
    await message.reply_text(f"Deleted quality '{quality}' and related links for series with key: {series_key}, language: {language}, season: {season_name}")

@Client.on_message(filters.command('seridelsea') & filters.user(ADMINS))
async def delete_series_season_command(client, message):
    if len(message.command) != 4:
        await message.reply_text("Usage: /seridelsea series_key 'Language' 'Season Name'")
        return

    series_key, language, season_name = message.command[1], message.command[2], message.command[3]
    success = delete_series_season(series_key, language, season_name)
    
    if success:
        await message.reply_text(f"Deleted season '{season_name}' and related links for series '{series_key}' in language '{language}'.")
    else:
        await message.reply_text(f"Failed to delete season '{season_name}'. Ensure the series, language, and season exist.")

@Client.on_message(filters.command('seridelang') & filters.user(ADMINS))
async def delete_series_language_command(client, message):
    if len(message.command) != 3:
        await message.reply_text("Usage: /seridelang series_key 'Language'")
        return

    series_key, language = message.command[1], message.command[2]
    delete_series_language(series_key, language)
    await message.reply_text(f"Deleted language '{language}' and related links for series with key: {series_key}")

@Client.on_message(filters.command("addposter") & filters.user(ADMINS))
async def add_poster(client, message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("Usage: /addposter series_key")
        return
    
    series_key = parts[1].strip().lower()
    
    # Check if the message is a reply to a photo or video
    replied = message.reply_to_message
    if not replied or not (replied.photo or replied.video):
        await message.reply_text("Reply to a photo or video.")
        return
    
    # Get file info and download the file
    file_info = get_file_id(replied)
    if not file_info:
        await message.reply_text("Not supported!")
        return
    
    # Create directory for download
    _t = os.path.join(TMP_DOWNLOAD_DIRECTORY, series_key)
    if not os.path.isdir(_t):
        os.makedirs(_t)
    _t += "/"
    
    # Download file
    download_location = await replied.download(_t)
    
    try:
        # Upload file to ImgBB
        with open(download_location, "rb") as file:
            response = requests.post(
                "https://api.imgbb.com/1/upload",
                params={"key": IMGBB_API_KEY},
                files={"image": file}
            )
            response_data = response.json()
        
        if response.status_code == 200 and "data" in response_data:
            poster_url = response_data["data"]["url"]
            
            # Add poster URL to the database
            if add_poster_to_db(series_key, poster_url):
                await message.reply(
                    f"Poster added successfully for series key: {series_key}\nLink: {poster_url}"
                )
            else:
                await message.reply("Failed to add poster. Please check if the series key is correct.")
        else:
            error_message = response_data.get("error", {}).get("message", "Unknown error")
            await message.reply(f"Failed to upload poster: {error_message}")
    except Exception as e:
        await message.reply(f"Error: {e}")
    finally:
        # Clean up downloaded files
        shutil.rmtree(_t, ignore_errors=True)

@Client.on_message(filters.command('stats') & filters.incoming)
async def get_ststs(bot, message):
    rju = await message.reply('👀')
    users = await db.total_users_count()
    chats = await db.total_chat_count()
    series_list = get_series()
    series_keys = [series['key'] for series in series_list]
    total_series = len(series_keys)
    await rju.edit(
        text=f"Total Series: {total_series}\nUsers: {users}\n chats: {chats}",
        parse_mode=enums.ParseMode.HTML
    )
