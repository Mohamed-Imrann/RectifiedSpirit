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
from info import ADMINS, TMP_DOWNLOAD_DIRECTORY, IMGBB_API_KEY
from database.users_chats_db import db
from database.crazy_db import (
    add_series, add_series_links, delete_series_and_links, delete_all_series_and_links,
    add_language, add_season, get_series_name, get_series, get_languages, get_seasons, get_links,
    delete_series_quality_and_links, delete_series_language, add_poster_to_db, delete_series_season
)
from plugins.get_file_id import get_file_id
import base64
import hashlib

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


import uuid

callback_data_store = {}

async def get_postr(query, bulk=False, id=False):
    try:
        if not id:
            search_results = imdb.search_movie(query)
            if not search_results:
                return None
            if bulk:
                top_movies = []
                for movie in search_results[:5]:
                    try:
                        movie_id = movie.movieID
                        full_movie = imdb.get_movie(movie_id)
                        top_movies.append({
                            'title': full_movie.get('title', 'N/A'),
                            'year': full_movie.get('year', 'N/A'),
                            'imdb_id': movie_id  # Updated key
                        })
                    except Exception as e:
                        print(f"Error fetching movie details: {e}")
                        continue
                return top_movies
            movie = search_results[0]
            movie_id = movie.movieID
        else:
            movie_id = query

        movie = imdb.get_movie(movie_id)
        if not movie:
            return None

        return {
            'title': movie.get('title', 'N/A'),
            'year': movie.get('year', 'N/A'),
            'genres': ', '.join(movie.get('genres', [])) or 'N/A',
            'languages': ', '.join(movie.get('languages', [])) or 'Original Audio',
            'rating': movie.get('rating', 'N/A'),
            'plot': movie.get('plot outline') or (movie.get('plot', ['N/A'])[0]),
            'poster': movie.get('full-size cover url', 'N/A'),
            'imdb_id': movie_id,  # Updated key
            'url': f'https://www.imdb.com/title/tt{movie_id}'
        }

    except Exception as e:
        print(f"IMDb Error: {e}")
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
        # Search on IMDb
        search_results = await get_postr(series_name, bulk=True)
        if not search_results:
            await k.edit_text("No results found on IMDb for the provided series name.")
            return

        # Create buttons for user to select the correct series
        buttons = []
        for movie in search_results:
            movie_title = movie.get('title', 'N/A')
            movie_year = movie.get('year', 'N/A')
            imdb_id = movie.get('imdb_id')  # Use consistent key

            # Store data in the callback store
            unique_id = str(uuid.uuid4())
            callback_data_store[unique_id] = {
                'imdb_id': imdb_id,
                'language': language,
                'season_name': season_name,
                'quality': quality,
                'link': link
            }

            button = InlineKeyboardButton(
                text=f"{movie_title} ({movie_year})",
                callback_data=f"idb#{unique_id}"
            )
            buttons.append([button])

        reply_markup = InlineKeyboardMarkup(buttons)
        await k.edit_text(
            "Multiple results found for {series_name}. Please select the correct series:",
            reply_markup=reply_markup
        )
        asyncio.create_task(DeleteMessage(k))
        return

    # If series found in DB, proceed directly
    await continue_add_quality_link(client, message, series_key, language, season_name, quality, link)
    
@Client.on_callback_query(filters.regex(r"^idb#"))
async def imdb_selection_callback(client: Client, callback_query):
    data = callback_query.data.split("#")
    unique_id = data[1]

    if unique_id not in callback_data_store:
        await callback_query.message.reply("Invalid or expired callback data.")
        return

    stored_data = callback_data_store.pop(unique_id)
    imdb_id = stored_data['imdb_id']
    language = stored_data['language']
    season_name = stored_data['season_name']
    quality = stored_data['quality']
    link = stored_data['link']

    movie = await get_postr(imdb_id, id=True)
    if not movie:
        await callback_query.message.reply("Failed to retrieve IMDb data.")
        return

    series_key = movie.get('title').lower().replace(" ", "").replace("-", "")

    series_data = {
        'title': movie.get('title', 'N/A'),
        'released_on': movie.get('year', 'N/A'),
        'genre': movie.get('genres', 'N/A'),
        'rating': movie.get('rating', 'N/A'),
        'key': series_key
    }

    add_series(series_data)

    msg = await callback_query.message.reply_text(
        f"Series added successfully!\n\n"
        f"**Title:** {movie.get('title', 'N/A')}\n"
        f"**Year:** {movie.get('year', 'N/A')}\n"
        f"**Genres:** {movie.get('genres', 'N/A')}\n"
        f"**Rating:** {movie.get('rating', 'N/A')}\n"
        f"**Poster URL:** {movie.get('poster', 'N/A')}"
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

import os
import shutil
import requests
from info import TMP_DOWNLOAD_DIRECTORY
from plugins.get_file_id import get_file_id

IMGBB_API_KEY = "5c789a0958af3fadc1db4fea0796576d"

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
