# MultipleFiles/newuipm_filter.py

import pyrogram
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from info import ADMINS, DB_CHANNEL # NEW IMPORT for TMDB_IMAGE_BASE_URL
from database.crazy_db import (
    get_series, get_links, get_series_name, get_languages, get_seasons, get_poster_manuel,
    tadd_series, tadd_poster_to_db, tadd_language, tdelete_group,
    add_temp_series_data, get_temp_series_data, clear_temp_series_data, add_temp_quality_links,
    get_temp_quality_links, get_all_temp_qualities_for_series, publish_temp_data
)
from utils import temp # Assuming 'temp' is still needed from your original utils.py
# Import TMDB related functions and ADMIN_STATES from newuicrazy.py
from crazy import ADMIN_STATES, get_movie_details_from_tmdb, find_most_similar_title

import asyncio
import difflib
import logging
import random

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

SPELL = (
    'https://envs.sh/kJj.jpg'
).split()

DEFAULT_POSTER = "https://envs.sh/kJK.jpg"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

async def alert_admins(client, series_key):
    alert_message = f"⚠️ Failed to fetch poster for series: <code>{series_key}</code>"
    for admin_id in ADMINS:
        try:
            await client.send_message(chat_id=admin_id, text=alert_message, parse_mode=enums.ParseMode.HTML)
        except Exception as e:
            logger.error(f"Failed to alert admin {admin_id}: {e}")

def get_movie_poster(series_key):
    poster_url = get_poster_manuel(series_key)
    if not poster_url:
        series = get_series_name(series_key)
        if series:
            series_title = series.get('title', '')
            # Use the TMDB utility function for search
            # Note: This is a synchronous call in an async function, which is generally bad.
            # For a quick fix, we'll use asyncio.run, but ideally, get_movie_details_from_tmdb
            # should be awaited directly if possible, or the poster fetching logic refactored.
            # However, get_poster_manuel is sync, so this might be unavoidable without deeper changes.
            search_results = asyncio.run(get_movie_details_from_tmdb(query=series_title.lower(), bulk=True))
            if search_results:
                movie = find_most_similar_title(series_title, search_results)
                if movie and movie.get('poster_path'):
                    poster_url = f"{TMDB_IMAGE_BASE_URL}{movie['poster_path']}"
    return poster_url

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def chunk_buttons(buttons, chunk_size=3):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

# find_most_similar_title is now imported from newuicrazy.py

@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client, message):
    user_id = message.from_user.id

    # --- Admin State Handling (for quality addition flow) ---
    if user_id in ADMINS and user_id in ADMIN_STATES:
        state_data = ADMIN_STATES[user_id]
        current_state = state_data.get('state')

        if current_state == 'waiting_for_quality_name':
            quality_name = message.text.strip()
            if not quality_name:
                await message.reply_text("Quality name cannot be empty. Please try again.")
                return

            state_data['quality_name'] = quality_name
            state_data['state'] = 'waiting_for_first_message'
            ADMIN_STATES[user_id] = state_data # Update state

            etho = await message.reply_text(
                f"Quality '{quality_name}' set. Now, **forward the first message** of the files you want to add for this quality."
            )
            asyncio.create_task(DeleteMessage(etho))
            return

        elif current_state == 'waiting_for_first_message':
            if not message.forward_from_chat or not message.forward_from_message_id:
                await message.reply_text("Please forward a message, not just send text.")
                return

            state_data['first_message_chat_id'] = message.forward_from_chat.id
            state_data['first_message_id'] = message.forward_from_message_id
            state_data['state'] = 'waiting_for_last_message'
            ADMIN_STATES[user_id] = state_data # Update state

            etho = await message.reply_text(
                "First message received. Now, **forward the last message** of the files. "
                "If it's a single file, forward the same message again."
            )
            asyncio.create_task(DeleteMessage(etho))
            return

        elif current_state == 'waiting_for_last_message':
            if not message.forward_from_chat or not message.forward_from_message_id:
                await message.reply_text("Please forward a message, not just send text.")
                return

            if message.forward_from_chat.id != state_data['first_message_chat_id']:
                await message.reply_text("The last message must be from the same chat as the first message.")
                return

            state_data['last_message_id'] = message.forward_from_message_id
            state_data['state'] = 'processing_files' # Indicate processing

            await message.reply_text("Processing files... This might take a moment.")

            # Trigger the file processing and link extraction
            await process_and_add_quality_links(client, message, user_id, state_data)

            # Clear state after processing
            del ADMIN_STATES[user_id]
            return

    # --- Regular User/Series Filter Handling ---
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
                InlineKeyboardButton(match, callback_data=f"spellcheck-{series_infos[series_names.index(match)]['key']}-{user_id}")
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
            f"<b>○ Title:</b> <code>{series['title']}</code>\n<b>○ Released On:</b> <code>{series['released_on']}</code>\n<b>○ Genre:</b> <code>{series['genre']}</code>\n<b>○ Rating:</b> <code>{series['rating']}</code>\n\n"
            "Available Languages:\n"
        )
        poster_url = get_movie_poster(series_key)
        buttons = [InlineKeyboardButton(lang, callback_data=f"{series_key}-{lang.lower().replace(' ', '')}-{user_id}") for lang in languages]
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


async def process_and_add_quality_links(client, message, user_id, state_data):
    series_key = state_data['series_key']
    language = state_data['language']
    season = state_data['season']
    quality_name = state_data['quality_name']
    first_msg_chat_id = state_data['first_message_chat_id']
    first_msg_id = state_data['first_message_id']
    last_msg_id = state_data['last_message_id']

    extracted_links = {}
    try:
        # Iterate through messages and forward them to DB_CHANNEL
        current_msg_id = first_msg_id
        while current_msg_id <= last_msg_id:
            try:
                msg_to_forward = await client.get_messages(first_msg_chat_id, current_msg_id)
                if msg_to_forward.empty:
                    current_msg_id += 1
                    continue

                # Forward to DB_CHANNEL
                forwarded_msg = await msg_to_forward.copy(DB_CHANNEL)

                # Extract file_id and simulate download link
                file_id = None
                if forwarded_msg.document:
                    file_id = forwarded_msg.document.file_id
                elif forwarded_msg.video:
                    file_id = forwarded_msg.video.file_id
                elif forwarded_msg.audio:
                    file_id = forwarded_msg.audio.file_id
                elif forwarded_msg.photo:
                    # For photos, get the largest size's file_id
                    if forwarded_msg.photo.sizes:
                        file_id = forwarded_msg.photo.sizes[-1].file_id
                elif forwarded_msg.sticker:
                    file_id = forwarded_msg.sticker.file_id
                elif forwarded_msg.animation:
                    file_id = forwarded_msg.animation.file_id


                if file_id:
                    # Simulate a direct download link. In a real scenario, you'd use a service
                    # like your own file server, or generate a direct link from Telegram's file_id
                    # if your bot supports it (e.g., via a web server that serves files).
                    # For this example, we'll use a placeholder.
                    simulated_download_link = f"https://yourdomain.com/files/{file_id}"
                    extracted_links[f"Part {current_msg_id - first_msg_id + 1}"] = simulated_download_link
                else:
                    extracted_links[f"Part {current_msg_id - first_msg_id + 1}"] = "No downloadable file found"

            except Exception as e:
                logger.error(f"Error processing message {current_msg_id}: {e}")
                extracted_links[f"Part {current_msg_id - first_msg_id + 1}"] = f"Error: {e}"
            current_msg_id += 1

        # Store these extracted links temporarily
        add_temp_quality_links(user_id, series_key, language, season, quality_name, extracted_links)

        # Display summary and publish button
        summary_text = (
            f"**Quality '{quality_name}' added temporarily for:**\n"
            f"Series: `{series_key.replace('-', ' ').title()}`\n"
            f"Language: `{language}`\n"
            f"Season: `{season}`\n\n"
            f"**Extracted Links ({len(extracted_links)}):**\n"
        )
        for part, link in extracted_links.items():
            summary_text += f"- {part}: `{link}`\n"

        summary_text += "\nClick 'Publish' to save all temporary changes to the database."

        buttons = [
            [InlineKeyboardButton("Add Another Quality", callback_data=f"add_another_quality#{series_key}#{language}#{season}#{user_id}")],
            [InlineKeyboardButton("Publish All Changes", callback_data=f"publish_temp_data#{user_id}")],
            [InlineKeyboardButton("Discard All Temporary Changes", callback_data=f"discard_temp_data#{user_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        await message.reply_text(summary_text, reply_markup=reply_markup, parse_mode=enums.ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"An unexpected error occurred during file processing: {e}", exc_info=True)
        await message.reply_text(f"An unexpected error occurred during file processing: {e}")
        clear_temp_series_data(user_id) # Clear temp data on error


@Client.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    data = query.data
    user_id = str(query.from_user.id)
    parts = data.split("-")

    # --- Admin Panel Callbacks ---
    if user_id in ADMINS:
        if data.startswith("addseries_select#"):
            tmdb_id = data.split("#")[1]
            media_type = data.split("#")[2] # Get media_type from callback data
            query_user_id = data.split("#")[3]
            if query_user_id != user_id:
                await query.answer("This selection is not for you.", show_alert=True)
                return

            await query.message.edit_text("Fetching TMDB data...")
            # Use the TMDB utility function to get movie details by ID and media_type
            movie = await get_movie_details_from_tmdb(tmdb_id=int(tmdb_id), media_type=media_type)
            if not movie:
                await query.message.edit_text("Failed to retrieve TMDB data.")
                return

            series_key = movie.get('title').lower().replace(" ", "")
            series_info = {
                "key": series_key,
                "title": movie.get('title', 'N/A'),
                "released_on": movie.get('released_on', 'N/A'),
                "genre": movie.get('genre', 'N/A'),
                "rating": movie.get('rating', 'N/A'),
                "poster": movie.get('poster', None),
                "tmdb_id": movie.get('tmdb_id'), # Store TMDB ID
                "media_type": movie.get('media_type'), # Store media type
                "languages": [], # Initialize empty
                "seasons": [] # Initialize empty
            }
            add_temp_series_data(user_id, {'series_info': series_info, 'qualities': {}})

            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("Add Language & Season", callback_data=f"add_lang_temp#{series_key}#{user_id}")],
                [InlineKeyboardButton("Add Quality (Advanced)", callback_data=f"add_quality_flow_start_cb#{series_key}#{user_id}")],
                [InlineKeyboardButton("Publish All Changes", callback_data=f"publish_temp_data#{user_id}")],
                [InlineKeyboardButton("Discard All Temporary Changes", callback_data=f"discard_temp_data#{user_id}")]
            ])
            await query.message.edit_media(
                InputMediaPhoto(
                    media=movie.get('poster') or DEFAULT_POSTER,
                    caption=(
                        f"**Series Selected (Temporary):**\n"
                        f"**Title:** {movie.get('title', 'N/A')}\n"
                        f"**Released On:** {movie.get('released_on', 'N/A')}\n"
                        f"**Genre:** {movie.get('genre', 'N/A')}\n"
                        f"**Rating:** {movie.get('rating', 'N/A')}\n\n"
                        f"Series Key: `{series_key}`"
                    )
                ),
                reply_markup=reply_markup
            )
            return

        elif data.startswith("cancel_addseries#"):
            query_user_id = data.split("#")[1]
            if query_user_id != user_id:
                await query.answer("This action is not for you.", show_alert=True)
                return
            clear_temp_series_data(user_id)
            await query.message.edit_text("Series addition cancelled and temporary data cleared.")
            return

        elif data.startswith("add_lang_temp#"):
            series_key = data.split("#")[1]
            query_user_id = data.split("#")[2]
            if query_user_id != user_id:
                await query.answer("This action is not for you.", show_alert=True)
                return

            temp_data = get_temp_series_data(user_id)
            if not temp_data or temp_data.get('series_info', {}).get('key') != series_key:
                await query.answer("No temporary series data found or mismatch.", show_alert=True)
                return

            # Ask for language input
            m = await query.message.reply_text("Please enter the language to add (e.g., 'English', 'Hindi'):")
            try:
                text_message = await client.listen(query.message.chat.id, filters=filters.text & filters.user(user_id), timeout=300)
                language = text_message.text.strip().capitalize()

                temp_data['series_info'].setdefault('languages', []).append(language)
                add_temp_series_data(user_id, temp_data) # Update temp data

                # Also ask for season
                await text_message.reply_text(f"Language '{language}' added temporarily. Now, enter the **season name** for this language (e.g., 'Season 1', 'Complete Season'):")
                season_message = await client.listen(query.message.chat.id, filters=filters.text & filters.user(user_id), timeout=300)
                season_name = season_message.text.strip()

                temp_data['series_info'].setdefault('seasons', []).append(season_name)
                add_temp_series_data(user_id, temp_data) # Update temp data

                await season_message.reply_text(f"Season '{season_name}' added temporarily for '{language}'.")

                # Update the admin panel UI
                await update_admin_panel_ui(client, query.message, user_id, series_key)

            except asyncio.TimeoutError:
                await m.reply_text("Timeout! You didn't respond in time.")
            except Exception as e:
                logger.error(f"Error adding language/season: {e}")
                await m.reply_text(f"An error occurred: {e}")
            finally:
                try:
                    await m.delete()
                except:
                    pass # Message might already be deleted

            return

        elif data.startswith("add_quality_flow_start_cb#"):
            series_key = data.split("#")[1]
            query_user_id = data.split("#")[2]
            if query_user_id != user_id:
                await query.answer("This action is not for you.", show_alert=True)
                return

            temp_data = get_temp_series_data(user_id)
            if not temp_data or temp_data.get('series_info', {}).get('key') != series_key:
                await query.answer("No temporary series data found or mismatch.", show_alert=True)
                return

            # Get available languages and seasons from temp data
            available_languages = temp_data.get('series_info', {}).get('languages', [])
            available_seasons = temp_data.get('series_info', {}).get('seasons', [])

            if not available_languages or not available_seasons:
                await query.answer("Please add at least one language and season first.", show_alert=True)
                return

            # Create buttons for language selection
            lang_buttons = [
                InlineKeyboardButton(lang, callback_data=f"select_lang_for_quality#{series_key}#{lang}#{user_id}")
                for lang in available_languages
            ]
            lang_buttons_chunked = chunk_buttons(lang_buttons, chunk_size=2)

            reply_markup = InlineKeyboardMarkup(lang_buttons_chunked)
            await query.message.edit_text(
                "Select a language for which you want to add quality:",
                reply_markup=reply_markup
            )
            return

        elif data.startswith("select_lang_for_quality#"):
            series_key = data.split("#")[1]
            language = data.split("#")[2]
            query_user_id = data.split("#")[3]
            if query_user_id != user_id:
                await query.answer("This action is not for you.", show_alert=True)
                return

            temp_data = get_temp_series_data(user_id)
            available_seasons = temp_data.get('series_info', {}).get('seasons', [])

            season_buttons = [
                InlineKeyboardButton(season, callback_data=f"select_season_for_quality#{series_key}#{language}#{season}#{user_id}")
                for season in available_seasons
            ]
            season_buttons_chunked = chunk_buttons(season_buttons, chunk_size=2)

            reply_markup = InlineKeyboardMarkup(season_buttons_chunked)
            await query.message.edit_text(
                f"Selected Language: **{language}**\nNow, select a season for which you want to add quality:",
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )
            return

        elif data.startswith("select_season_for_quality#"):
            series_key = data.split("#")[1]
            language = data.split("#")[2]
            season = data.split("#")[3]
            query_user_id = data.split("#")[4]
            if query_user_id != user_id:
                await query.answer("This action is not for you.", show_alert=True)
                return

            # Set admin state to waiting for quality name
            ADMIN_STATES[user_id] = {
                'state': 'waiting_for_quality_name',
                'series_key': series_key,
                'language': language,
                'season': season,
                'message_id': query.message.id,
                'chat_id': query.message.chat.id
            }
            await query.message.edit_text(
                f"Selected Season: **{season}**\n\n"
                f"Please enter the **quality name** (e.g., '720p HEVC', '1080p x264')."
            )
            return

        elif data.startswith("add_another_quality#"):
            series_key = data.split("#")[1]
            language = data.split("#")[2]
            season = data.split("#")[3]
            query_user_id = data.split("#")[4]
            if query_user_id != user_id:
                await query.answer("This action is not for you.", show_alert=True)
                return

            # Reset state to ask for quality name for the same series/lang/season
            ADMIN_STATES[user_id] = {
                'state': 'waiting_for_quality_name',
                'series_key': series_key,
                'language': language,
                'season': season,
                'message_id': query.message.id,
                'chat_id': query.message.chat.id
            }
            await query.message.edit_text(
                f"Okay, adding another quality for **{series_key.replace('-', ' ').title()} - {language} - {season}**:\n"
                "Please enter the **quality name** (e.g., '720p HEVC', '1080p x264')."
            )
            return

        elif data.startswith("publish_temp_data#"):
            query_user_id = data.split("#")[1]
            if query_user_id != user_id:
                await query.answer("This action is not for you.", show_alert=True)
                return

            await query.message.edit_text("Publishing all temporary data to the main database...")
            success = publish_temp_data(user_id)
            if success:
                await query.message.edit_text("All temporary data published successfully!")
            else:
                await query.message.edit_text("No temporary data to publish or an error occurred.")
            return

        elif data.startswith("discard_temp_data#"):
            query_user_id = data.split("#")[1]
            if query_user_id != user_id:
                await query.answer("This action is not for you.", show_alert=True)
                return

            clear_temp_series_data(user_id)
            await query.message.edit_text("All temporary data discarded.")
            return

    # --- Existing User Callbacks ---
    if data == "close_data":
        await query.message.delete()
    elif data == "pages":
        await query.answer()
    elif data.startswith("adds#"): # This is the old add series callback, should be replaced by new /addseries command
        await query.answer("This method is deprecated. Please use the new `/addseries` command.", show_alert=True)
        return

    # Changing the poster (existing functionality)
    elif data.startswith("change_poster#"):
        series_key = data.split("#")[1]
        if str(query.from_user.id) not in ADMINS:
            await query.answer("You are not authorized to do this.", show_alert=True)
            return

        await query.message.reply_text("Please send the new poster as a photo or video. I will listen for 5 minutes.")
        try:
            media_message = await client.listen(query.message.chat.id, filters=filters.photo | filters.video, timeout=300)
            file_id = None
            if media_message.photo:
                file_id = media_message.photo.file_id
            elif media_message.video:
                file_id = media_message.video.file_id

            if file_id:
                # Simulate upload to hosting service (e.g., ImgBB)
                # In a real scenario, you'd download the file and upload it.
                # For now, we'll just use a placeholder or a direct Telegram file link if possible.
                # For simplicity, let's assume you have a function to get a direct link or upload.
                # For this example, we'll just use a dummy URL.
                poster_url = f"https://yourdomain.com/posters/{file_id}.jpg" # Placeholder

                # Update the poster URL using the utility function
                tadd_poster_to_db(series_key, poster_url)
                await query.message.edit_media(InputMediaPhoto(media=poster_url), caption=f"Poster updated for `{series_key}`.")
            else:
                await query.message.reply_text("No valid media found in the forwarded message.")
        except asyncio.TimeoutError:
            await query.message.reply_text("Timeout! You didn't send a media file in time.")
        except Exception as e:
            await query.message.reply_text(f"An error occurred: {e}")
        return

    elif data.startswith("add_lang#"): # This is the old add language, should be replaced by new /addseries flow
        await query.answer("This method is deprecated. Please use the new `/addseries` command to add languages during series setup.", show_alert=True)
        return

    elif data.startswith("delete_group#"):
        series_key = data.split("#")[1]
        if str(query.from_user.id) not in ADMINS:
            await query.answer("You are not authorized to do this.", show_alert=True)
            return
        tdelete_group(series_key)
        await query.message.reply_text(f"Series with key `{series_key}` deleted successfully.")
        return

    elif data.startswith("gt:"):
        start_parameter = data.split(":")[1]
        try:
            teststring = f"https://t.me/{temp.U_NAME}?start={start_parameter}"
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={start_parameter}")
        except pyrogram.errors.exceptions.bad_request_400.UrlInvalid:
            await query.answer("Invalid URL provided.", show_alert=True)
        return

    elif data.startswith("get:"):
        start_parameter = data.split(":")[1]
        try:
            teststringt = f"https://t.me/{temp.U_NAME}?start={start_parameter}"
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={start_parameter}")
        except pyrogram.errors.exceptions.bad_request_400.UrlInvalid:
            await query.answer("Invalid URL provided.", show_alert=True)
        return

    elif data.startswith("spellcheck-"):
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
                f"<b>○ Title:</b> <code>{series['title']}</code>\n<b>○ Released On:</b> <code>{series['released_on']}</code>\n<b>○ Genre:</b> <code>{series['genre']}</code>\n<b>○ Rating:</b> <code>{series['rating']}</code>\n\n"
                "Available Languages:\n"
            )
            buttons = [InlineKeyboardButton(lang, callback_data=f"{series_key}-{lang.lower().replace(' ', '')}-{user_id}") for lang in languages]
            buttons_chunked = chunk_buttons(buttons, chunk_size=2)
            reply_markup = InlineKeyboardMarkup(buttons_chunked)
            try:
                if poster_url:
                    await query.message.edit_media(media=InputMediaPhoto(poster_url), reply_markup=reply_markup)
                else:
                    await query.message.edit_media(media=InputMediaPhoto(DEFAULT_POSTER), reply_markup=reply_markup)
                await query.message.edit_caption(caption=reply_text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
            except pyrogram.errors.MediaEmpty:
                await alert_admins(client, series_key)
                await query.message.edit_media(media=InputMediaPhoto(DEFAULT_POSTER), reply_markup=reply_markup)
                await query.message.edit_caption(caption=reply_text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
        else:
            await query.message.edit_text(text="Series not found.", disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
        return

    # Existing series/language/season selection
    if len(parts) == 3:
        series_key, language, query_user_id = parts
        if query_user_id != user_id:
            await query.answer("Request Yourself", show_alert=True)
            return

        series = get_series_name(series_key)
        if series:
            seasons = series.get("seasons", []) # Get seasons from series object
            reply_text = (
                f"<b>○ Title:</b> <code>{series['title'].title()}</code>\n<b>○ Released On:</b> <code>{series['released_on']}</code>\n<b>○ Genre:</b> <code>{series['genre']}</code>\n<b>○ Rating:</b> <code>{series['rating']}</code>\n\n"
                f"<b>○ Language:</b> <code>{language.title()}</code>\n\n"
                "Available Seasons:\n"
            )

            buttons = [InlineKeyboardButton(season, callback_data=f"{series_key}-{language}-{season.lower().replace(' ', '')}-{user_id}") for season in seasons]
            buttons_chunked = chunk_buttons(buttons)
            buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"spellcheck-{series_key}-{user_id}")])
            reply_markup = InlineKeyboardMarkup(buttons_chunked)
            await query.message.edit_text(
                text=reply_text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
        return

    elif len(parts) == 4:
        series_key, language, season, query_user_id = parts
        if query_user_id != user_id:
            await query.answer("Request Yourself", show_alert=True)
            return

        series = get_series_name(series_key)
        link_key = f"{series_key.lower().replace(' ', '')}-{language.lower().replace(' ', '')}-{season.lower().replace(' ', '')}"
        links = get_links(link_key)
        if links:
            buttons = [
                InlineKeyboardButton(quality, callback_data=f"gt:{link}")
                for quality, link in links.items()
            ]
            buttons_chunked = chunk_buttons(buttons, chunk_size=2)
            if buttons_chunked:
                buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"{series_key}-{language}-{user_id}")])
                reply_markup = InlineKeyboardMarkup(buttons_chunked)
                await query.message.edit_text(
                    text=(
                        f"<b>○ Title:</b> <code>{series['title'].title()}</code>\n"
                        f"<b>○ Released On:</b> <code>{series['released_on']}</code>\n"
                        f"<b>○ Genre:</b> <code>{series['genre']}</code>\n"
                        f"<b>○ Rating:</b> <code>{series['rating']}</code>\n\n"
                        f"<b>○ Language:</b> <code>{language.title()}</code>\n"
                        f"<b>○ Season:</b> <code>{season.replace('-', ' ').title()}</code>\n\n"
                        "Select the quality you need...!"
                    ),
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML
                )
            else:
                await query.message.edit_text(
                    text="No qualities available for this language and season.",
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML
                )
        else:
            await query.message.edit_text(
                text="No links found for the selected season and language.",
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
        return

async def update_admin_panel_ui(client, message, user_id, series_key):
    """Updates the admin panel UI after an action (e.g., adding language/season)."""
    temp_data = get_temp_series_data(user_id)
    series_info = temp_data.get('series_info', {})
    qualities_data = temp_data.get('qualities', {})

    caption_text = (
        f"**Series Selected (Temporary):**\n"
        f"**Title:** {series_info.get('title', 'N/A')}\n"
        f"**Released On:** {series_info.get('released_on', 'N/A')}\n"
        f"**Genre:** {series_info.get('genre', 'N/A')}\n"
        f"**Rating:** {series_info.get('rating', 'N/A')}\n\n"
        f"Series Key: `{series_key}`\n"
        f"TMDB ID: `{series_info.get('tmdb_id', 'N/A')}`\n"
        f"Media Type: `{series_info.get('media_type', 'N/A').upper()}`\n\n"
        f"**Languages Added:** {', '.join(series_info.get('languages', [])) or 'None'}\n"
        f"**Seasons Added:** {', '.join(series_info.get('seasons', [])) or 'None'}\n\n"
        f"**Temporary Qualities Added:**\n"
    )

    if qualities_data:
        for sk, langs in qualities_data.items():
            if sk == series_key: # Only show qualities for the current series
                for lang, seasons in langs.items():
                    for season, qualities in seasons.items():
                        for quality_name, links in qualities.items():
                            caption_text += f"- `{lang}` - `{season}` - `{quality_name}` ({len(links)} parts)\n"
    else:
        caption_text += "None yet."

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Language & Season", callback_data=f"add_lang_temp#{series_key}#{user_id}")],
        [InlineKeyboardButton("Add Quality (Advanced)", callback_data=f"add_quality_flow_start_cb#{series_key}#{user_id}")],
        [InlineKeyboardButton("Publish All Changes", callback_data=f"publish_temp_data#{user_id}")],
        [InlineKeyboardButton("Discard All Temporary Changes", callback_data=f"discard_temp_data#{user_id}")]
    ])

    try:
        await message.edit_media(
            InputMediaPhoto(
                media=series_info.get('poster') or DEFAULT_POSTER,
                caption=caption_text
            ),
            reply_markup=reply_markup
        )
    except pyrogram.errors.MediaEmpty:
        await message.edit_media(
            InputMediaPhoto(
                media=DEFAULT_POSTER,
                caption=caption_text
            ),
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error updating admin panel UI: {e}")
        await message.reply_text(f"Error updating UI: {e}\n\n{caption_text}", reply_markup=reply_markup)

