import uuid
import logging
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, InputMediaPhoto, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from info import ADMINS, DB_CHANNEL, RAW_DB_CHANNEL, LOG_CHANNEL, PICS, IMDB_TEMPLATE, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG
from database.crazy_db import (
    add_series, get_series, get_series_by_key, update_series, delete_series,
    get_languages, get_seasons, get_qualities, get_quality_link, get_poster_file_id
)
from database.users_chats_db import db
from utils import find_most_similar_title, get_poster, get_message_id, get_messages_in_range, delete_messages_from_user_chat, temp
from fuzzywuzzy import fuzz
import asyncio
import re
import json
import random

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Temporary storage for ongoing series creation/editing
temp_series_data = {}

# Helper function to chunk buttons for inline keyboards
def chunk_buttons(buttons, chunk_size=3):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

@Client.on_message(filters.command("addseries") & filters.user(ADMINS))
async def add_series_command(client, message):
    user_id = message.from_user.id
    temp_series_data[user_id] = {"step": "title"}
    await message.reply_text("Okay, let's add a new series. Please send me the **Title** of the series.")

@Client.on_message(filters.command("editseries") & filters.user(ADMINS))
async def edit_series_command(client, message):
    user_id = message.from_user.id
    query = " ".join(message.command[1:])
    
    if not query:
        await message.reply_text("Please provide the series title or key to edit. Example: `/editseries The Flash`")
        return

    series_list = get_series()
    published_series = [s for s in series_list if s.get('published', False)]
    series_titles = [s['title'] for s in published_series]
    series_keys = [s['_id'] for s in published_series]

    # Try exact match by key or title first
    series_data = None
    for s in published_series:
        if query.lower() == s['_id'].lower() or query.lower() == s['title'].lower():
            series_data = s
            break

    if not series_data:
        # If no exact match, try fuzzy matching
        close_matches_titles = find_most_similar_title(query, series_titles) # Using utils.find_most_similar_title
        
        if close_matches_titles:
            buttons = []
            for match_title in close_matches_titles:
                matched_series = next((s for s in published_series if s['title'] == match_title), None)
                if matched_series:
                    buttons.append(
                        InlineKeyboardButton(match_title, callback_data=f"edit_select_series:{matched_series['_id']}")
                    )
            
            if buttons:
                buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                reply_markup = InlineKeyboardMarkup(buttons_chunked)
                await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Did you mean one of these series?</b>", reply_markup=reply_markup)
                return
        else:
            await message.reply_text(f"No series found matching '{query}'. Please try a different query or add the series first using /addseries.")
            return
    
    # If an exact match or selected from spellcheck, proceed to edit
    temp_series_data[user_id] = {"step": "edit_menu", "series_key": series_data['_id'], "series_data": series_data}
    await send_edit_series_menu(client, message, series_data)


async def send_edit_series_menu(client, message, series_data):
    series_key = series_data['_id']
    title = series_data.get('title', 'N/A')
    released_on = series_data.get('released_on', 'N/A')
    genre = series_data.get('genre', 'N/A')
    rating = series_data.get('rating', 'N/A')
    published_status = "Published ✅" if series_data.get('published', False) else "Unpublished ❌"

    text = (
        f"**Editing Series:** `{title}` (`{series_key}`)\n\n"
        f"**Current Details:**\n"
        f"○ **Title:** `{title}`\n"
        f"○ **Released On:** `{released_on}`\n"
        f"○ **Genre:** `{genre}`\n"
        f"○ **Rating:** `{rating}`\n"
        f"○ **Status:** `{published_status}`\n\n"
        "What would you like to edit?"
    )

    buttons = [
        [InlineKeyboardButton("Edit Title", callback_data=f"edit_field:{series_key}:title")],
        [InlineKeyboardButton("Edit Released On", callback_data=f"edit_field:{series_key}:released_on")],
        [InlineKeyboardButton("Edit Genre", callback_data=f"edit_field:{series_key}:genre")],
        [InlineKeyboardButton("Edit Rating", callback_data=f"edit_field:{series_key}:rating")],
        [InlineKeyboardButton("Edit Poster", callback_data=f"edit_field:{series_key}:poster")],
        [InlineKeyboardButton("Manage Languages", callback_data=f"manage_languages:{series_key}")],
        [InlineKeyboardButton(f"Toggle Publish Status ({published_status})", callback_data=f"toggle_publish:{series_key}")],
        [InlineKeyboardButton("Delete Series", callback_data=f"delete_series_confirm:{series_key}")],
        [InlineKeyboardButton("Done Editing", callback_data=f"cancel_edit:{series_key}")]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text(text, reply_markup=reply_markup, parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.text & filters.private & filters.user(ADMINS) & filters.incoming)
async def handle_series_input(client, message):
    user_id = message.from_user.id
    if user_id not in temp_series_data:
        return # Not in an active series creation/edit flow

    current_step = temp_series_data[user_id].get("step")
    series_key = temp_series_data[user_id].get("series_key")

    if current_step == "title":
        title = message.text.strip()
        if not title:
            await message.reply_text("Title cannot be empty. Please send the **Title** of the series.")
            return
        
        # Check for existing series with the same title
        existing_series = get_series_by_key(title.lower().replace(" ", "_")) # Use a simple key for now
        if existing_series:
            await message.reply_text(f"A series with the title '{title}' already exists. Please choose a different title or use /editseries to modify the existing one.")
            return

        temp_series_data[user_id]["title"] = title
        temp_series_data[user_id]["_id"] = title.lower().replace(" ", "_") # Generate a key
        temp_series_data[user_id]["step"] = "released_on"
        await message.reply_text("Now, please send the **Released On** date (e.g., 2023 or 2023-01-15).")

    elif current_step == "released_on":
        released_on = message.text.strip()
        temp_series_data[user_id]["released_on"] = released_on
        temp_series_data[user_id]["step"] = "genre"
        await message.reply_text("Next, send the **Genre** (e.g., Action, Sci-Fi, Drama).")

    elif current_step == "genre":
        genre = message.text.strip()
        temp_series_data[user_id]["genre"] = genre
        temp_series_data[user_id]["step"] = "rating"
        await message.reply_text("Please send the **Rating** (e.g., 8.5, PG-13).")

    elif current_step == "rating":
        rating = message.text.strip()
        temp_series_data[user_id]["rating"] = rating
        temp_series_data[user_id]["step"] = "poster"
        await message.reply_text("Finally, send the **Poster** for the series. This can be a photo or a direct URL.")
    
    elif current_step == "poster":
        poster_source = None
        if message.photo:
            poster_source = message.photo.file_id
            logger.info(f"Received photo file_id for poster: {poster_source}")
        elif message.text and (message.text.startswith('http://') or message.text.startswith('https://')):
            poster_source = message.text.strip()
            logger.info(f"Received URL for poster: {poster_source}")
        
        if not poster_source:
            await message.reply_text("Invalid poster. Please send a photo or a direct URL for the poster.")
            return
        
        temp_series_data[user_id]["poster_file_id"] = poster_source
        temp_series_data[user_id]["languages"] = [] # Initialize languages list
        temp_series_data[user_id]["published"] = False # Default to unpublished
        
        series_data_to_save = {k: v for k, v in temp_series_data[user_id].items() if k not in ["step", "series_key"]}
        add_series(series_data_to_save)
        
        await message.reply_text(
            f"Series '{series_data_to_save['title']}' added successfully!\n\n"
            "You can now manage its languages, seasons, and qualities using the /editseries command."
        )
        del temp_series_data[user_id] # Clear temp data

    elif current_step.startswith("edit_field:"):
        _, field_to_edit = current_step.split(":", 1)
        new_value = message.text.strip()
        
        if field_to_edit == "poster":
            poster_source = None
            if message.photo:
                poster_source = message.photo.file_id
                logger.info(f"Received photo file_id for poster update: {poster_source}")
            elif message.text and (message.text.startswith('http://') or message.text.startswith('https://')):
                poster_source = message.text.strip()
                logger.info(f"Received URL for poster update: {poster_source}")
            
            if not poster_source:
                await message.reply_text("Invalid poster. Please send a photo or a direct URL for the poster.")
                return
            new_value = poster_source
        
        if not new_value and field_to_edit != "poster": # Poster can be empty if user wants to remove it (though not explicitly supported here)
            await message.reply_text(f"The new value for {field_to_edit} cannot be empty. Please send the new value.")
            return

        update_series(series_key, {field_to_edit: new_value})
        updated_series_data = get_series_by_key(series_key)
        temp_series_data[user_id] = {"step": "edit_menu", "series_key": series_key, "series_data": updated_series_data}
        await message.reply_text(f"'{field_to_edit.replace('_', ' ').title()}' updated successfully!")
        await send_edit_series_menu(client, message, updated_series_data)

    elif current_step == "add_language":
        language_name = message.text.strip().lower()
        if not language_name:
            await message.reply_text("Language name cannot be empty. Please send the language name.")
            return
        
        series_data = get_series_by_key(series_key)
        if any(lang['name'].lower() == language_name for lang in series_data.get('languages', [])):
            await message.reply_text(f"Language '{language_name.title()}' already exists for this series. Please choose a different name or go back to manage existing languages.")
            return

        series_data['languages'].append({"name": language_name, "seasons": []})
        update_series(series_key, {"languages": series_data['languages']})
        updated_series_data = get_series_by_key(series_key)
        temp_series_data[user_id] = {"step": "manage_languages", "series_key": series_key, "series_data": updated_series_data}
        await message.reply_text(f"Language '{language_name.title()}' added successfully!")
        await send_manage_languages_menu(client, message, updated_series_data)

    elif current_step == "add_season":
        season_name = message.text.strip().lower()
        if not season_name:
            await message.reply_text("Season name cannot be empty. Please send the season name.")
            return
        
        series_data = get_series_by_key(series_key)
        language_name = temp_series_data[user_id]["current_language"]
        
        current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name), None)
        if current_lang and any(s['name'].lower() == season_name for s in current_lang.get('seasons', [])):
            await message.reply_text(f"Season '{season_name.title()}' already exists for this language. Please choose a different name or go back to manage existing seasons.")
            return

        if current_lang:
            current_lang['seasons'].append({"name": season_name, "qualities": []})
            update_series(series_key, {"languages": series_data['languages']})
            updated_series_data = get_series_by_key(series_key)
            temp_series_data[user_id] = {"step": "manage_seasons", "series_key": series_key, "series_data": updated_series_data, "current_language": language_name}
            await message.reply_text(f"Season '{season_name.title()}' added successfully!")
            await send_manage_seasons_menu(client, message, updated_series_data, language_name)
        else:
            await message.reply_text("Error: Language not found. Please try again from the main edit menu.")
            del temp_series_data[user_id]

    elif current_step == "add_quality":
        quality_name = message.text.strip().lower()
        if not quality_name:
            await message.reply_text("Quality name cannot be empty. Please send the quality name.")
            return
        
        series_data = get_series_by_key(series_key)
        language_name = temp_series_data[user_id]["current_language"]
        season_name = temp_series_data[user_id]["current_season"]

        current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name), None)
        current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name), None) if current_lang else None

        if current_season and any(q['name'].lower() == quality_name for q in current_season.get('qualities', [])):
            await message.reply_text(f"Quality '{quality_name.upper()}' already exists for this season. Please choose a different name or go back to manage existing qualities.")
            return

        if current_season:
            temp_series_data[user_id]["quality_name"] = quality_name
            temp_series_data[user_id]["step"] = "add_quality_link"
            await message.reply_text(f"Now, forward the messages containing the files for **{quality_name.upper()}** quality, or send the start and end message IDs from the DB channel (e.g., `12345-12350`).")
        else:
            await message.reply_text("Error: Season not found. Please try again from the main edit menu.")
            del temp_series_data[user_id]

    elif current_step == "add_quality_link":
        series_data = get_series_by_key(series_key)
        language_name = temp_series_data[user_id]["current_language"]
        season_name = temp_series_data[user_id]["current_season"]
        quality_name = temp_series_data[user_id]["quality_name"]

        source_channel_id, start_msg_id = await get_message_id(client, message)
        end_msg_id = start_msg_id # Assume single message if not range

        if "-" in message.text:
            try:
                start_msg_id_str, end_msg_id_str = message.text.split("-")
                start_msg_id = int(start_msg_id_str.strip())
                end_msg_id = int(end_msg_id_str.strip())
                # If a range is provided, assume the source channel is RAW_DB_CHANNEL
                source_channel_id = RAW_DB_CHANNEL[0] if RAW_DB_CHANNEL else None # Use the first RAW_DB_CHANNEL
                if not source_channel_id:
                    await message.reply_text("RAW_DB_CHANNEL is not configured. Cannot process message ID range.")
                    del temp_series_data[user_id]
                    return
                logger.info(f"Processing message ID range: {start_msg_id}-{end_msg_id} from RAW_DB_CHANNEL: {source_channel_id}")
            except ValueError:
                await message.reply_text("Invalid message ID range format. Please use `start_id-end_id` or forward messages.")
                return
        elif message.forward_from_chat:
            source_channel_id = message.forward_from_chat.id
            start_msg_id = message.forward_from_message_id
            end_msg_id = start_msg_id # Single forwarded message
            logger.info(f"Processing forwarded message from {source_channel_id}, msg_id: {start_msg_id}")
        else:
            await message.reply_text("Invalid input. Please forward messages or provide a message ID range (e.g., `12345-12350`).")
            return

        if not source_channel_id or not start_msg_id:
            await message.reply_text("Could not determine source channel or message ID. Please ensure the message is forwarded from a channel or a valid ID range is provided.")
            return

        if abs(int(source_channel_id)) not in RAW_DB_CHANNEL:
            await message.reply_text(f"The source channel `{source_channel_id}` is not a configured RAW_DB_CHANNEL. Please forward from a valid DB channel.")
            return

        status_message = await message.reply_text("Copying messages... Please wait.")
        
        copied_messages = await get_messages_in_range(client, source_channel_id, start_msg_id, end_msg_id, DB_CHANNEL)
        
        if not copied_messages:
            await status_message.edit_text("Failed to copy messages. Please check bot permissions in the DB channel and ensure messages exist in the source channel.")
            del temp_series_data[user_id]
            return

        # Create a unique link key using the first copied message's ID
        link_key = f"{copied_messages[0].chat.id}_{copied_messages[0].id}"
        
        # Update the series data with the new quality and link key
        current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name), None)
        current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name), None) if current_lang else None

        if current_season:
            current_season['qualities'].append({"name": quality_name, "link_key": link_key})
            update_series(series_key, {"languages": series_data['languages']})
            updated_series_data = get_series_by_key(series_key)
            
            # Store the copied messages for auto-deletion
            temp.MELCOW[link_key] = copied_messages
            asyncio.create_task(delete_file(copied_messages, client, "quality_link"))

            await status_message.edit_text(f"Quality '{quality_name.upper()}' added successfully with link key `{link_key}`!")
            
            # Delete the user's input message (forwarded message or ID range)
            await delete_messages_from_user_chat(client, user_id, [message.id])

            temp_series_data[user_id] = {"step": "manage_qualities", "series_key": series_key, "series_data": updated_series_data, "current_language": language_name, "current_season": season_name}
            await send_manage_qualities_menu(client, message, updated_series_data, language_name, season_name)
        else:
            await status_message.edit_text("Error: Season not found during quality link addition. Please try again from the main edit menu.")
            del temp_series_data[user_id]


@Client.on_callback_query(filters.regex(r"edit_select_series:|edit_field:|manage_languages:|manage_seasons:|manage_qualities:|add_language:|add_season:|add_quality:|toggle_publish:|delete_series_confirm:|delete_language_confirm:|delete_season_confirm:|cancel_edit:"))
async def series_admin_callback_handler(client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data
    parts = data.split(":")
    action = parts[0]
    series_key = parts[1] if len(parts) > 1 else None

    series_data = get_series_by_key(series_key) if series_key else None

    if not series_data and action not in ["cancel_edit"]:
        await query.answer("Series not found or deleted.", show_alert=True)
        await query.message.delete()
        if user_id in temp_series_data:
            del temp_series_data[user_id]
        return

    if action == "edit_select_series":
        temp_series_data[user_id] = {"step": "edit_menu", "series_key": series_key, "series_data": series_data}
        await query.message.delete() # Delete the spellcheck message
        await send_edit_series_menu(client, query.message, series_data)

    elif action == "edit_field":
        field_to_edit = parts[2]
        temp_series_data[user_id]["step"] = f"edit_field:{field_to_edit}"
        await query.answer()
        await query.message.edit_text(f"Please send the new value for **{field_to_edit.replace('_', ' ').title()}**.")

    elif action == "manage_languages":
        temp_series_data[user_id] = {"step": "manage_languages", "series_key": series_key, "series_data": series_data}
        await query.answer()
        await send_manage_languages_menu(client, query.message, series_data)

    elif action == "add_language":
        temp_series_data[user_id]["step"] = "add_language"
        await query.answer()
        await query.message.edit_text("Please send the **Name** of the new language (e.g., English, Hindi).")

    elif action.startswith("manage_seasons:"):
        language_name = parts[2]
        temp_series_data[user_id] = {"step": "manage_seasons", "series_key": series_key, "series_data": series_data, "current_language": language_name}
        await query.answer()
        await send_manage_seasons_menu(client, query.message, series_data, language_name)

    elif action == "add_season":
        language_name = parts[2]
        temp_series_data[user_id]["step"] = "add_season"
        temp_series_data[user_id]["current_language"] = language_name
        await query.answer()
        await query.message.edit_text(f"Please send the **Name** of the new season for {language_name.title()} (e.g., Season 1, S02).")

    elif action.startswith("manage_qualities:"):
        language_name = parts[2]
        season_name = parts[3]
        temp_series_data[user_id] = {"step": "manage_qualities", "series_key": series_key, "series_data": series_data, "current_language": language_name, "current_season": season_name}
        await query.answer()
        await send_manage_qualities_menu(client, query.message, series_data, language_name, season_name)

    elif action == "add_quality":
        language_name = parts[2]
        season_name = parts[3]
        temp_series_data[user_id]["step"] = "add_quality"
        temp_series_data[user_id]["current_language"] = language_name
        temp_series_data[user_id]["current_season"] = season_name
        await query.answer()
        await query.message.edit_text(f"Please send the **Name** of the new quality for {season_name.title()} ({language_name.title()}) (e.g., 480p, 720p, 1080p).")

    elif action == "toggle_publish":
        current_status = series_data.get('published', False)
        new_status = not current_status
        update_series(series_key, {"published": new_status})
        updated_series_data = get_series_by_key(series_key)
        temp_series_data[user_id]["series_data"] = updated_series_data # Update temp data
        await query.answer(f"Series is now {'Published' if new_status else 'Unpublished'}.", show_alert=True)
        await send_edit_series_menu(client, query.message, updated_series_data)

    elif action == "delete_series_confirm":
        await query.answer()
        buttons = [
            [InlineKeyboardButton("Yes, Delete It", callback_data=f"delete_series_execute:{series_key}")],
            [InlineKeyboardButton("No, Go Back", callback_data=f"cancel_edit:{series_key}")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            f"Are you sure you want to delete the series **{series_data['title']}** (`{series_key}`)? This action cannot be undone.",
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )

    elif action == "delete_series_execute":
        delete_series(series_key)
        await query.answer(f"Series '{series_data['title']}' deleted successfully!", show_alert=True)
        await query.message.edit_text(f"Series '{series_data['title']}' has been deleted.")
        if user_id in temp_series_data:
            del temp_series_data[user_id]

    elif action.startswith("delete_language_confirm:"):
        language_name = parts[2]
        await query.answer()
        buttons = [
            [InlineKeyboardButton("Yes, Delete It", callback_data=f"delete_language_execute:{series_key}:{language_name}")],
            [InlineKeyboardButton("No, Go Back", callback_data=f"manage_languages:{series_key}")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            f"Are you sure you want to delete the language **{language_name.title()}** from **{series_data['title']}**? This will also delete all its seasons and qualities.",
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )

    elif action.startswith("delete_language_execute:"):
        language_name = parts[2]
        series_data['languages'] = [lang for lang in series_data['languages'] if lang['name'].lower() != language_name.lower()]
        update_series(series_key, {"languages": series_data['languages']})
        updated_series_data = get_series_by_key(series_key)
        temp_series_data[user_id]["series_data"] = updated_series_data
        await query.answer(f"Language '{language_name.title()}' deleted successfully!", show_alert=True)
        await send_manage_languages_menu(client, query.message, updated_series_data)

    elif action.startswith("delete_season_confirm:"):
        language_name = parts[2]
        season_name = parts[3]
        await query.answer()
        buttons = [
            [InlineKeyboardButton("Yes, Delete It", callback_data=f"delete_season_execute:{series_key}:{language_name}:{season_name}")],
            [InlineKeyboardButton("No, Go Back", callback_data=f"manage_seasons:{series_key}:{language_name}")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            f"Are you sure you want to delete season **{season_name.title()}** from **{language_name.title()}** in **{series_data['title']}**? This will also delete all its qualities.",
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )

    elif action.startswith("delete_season_execute:"):
        language_name = parts[2]
        season_name = parts[3]
        
        current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name), None)
        if current_lang:
            current_lang['seasons'] = [s for s in current_lang['seasons'] if s['name'].lower() != season_name.lower()]
            update_series(series_key, {"languages": series_data['languages']})
            updated_series_data = get_series_by_key(series_key)
            temp_series_data[user_id]["series_data"] = updated_series_data
            await query.answer(f"Season '{season_name.title()}' deleted successfully!", show_alert=True)
            await send_manage_seasons_menu(client, query.message, updated_series_data, language_name)
        else:
            await query.answer("Error: Language not found.", show_alert=True)
            await send_manage_languages_menu(client, query.message, series_data)

    elif action == "cancel_edit":
        await query.answer("Editing cancelled.", show_alert=True)
        await query.message.edit_text("Series editing session ended.")
        if user_id in temp_series_data:
            del temp_series_data[user_id]


async def send_manage_languages_menu(client, message, series_data):
    series_key = series_data['_id']
    languages = series_data.get("languages", [])
    
    text = f"**Managing Languages for:** `{series_data['title']}`\n\n"
    if not languages:
        text += "No languages added yet."
    else:
        text += "Current Languages:\n" + "\n".join([f"○ `{lang['name'].title()}`" for lang in languages]) + "\n\n"
    
    buttons = []
    for lang in languages:
        buttons.append([
            InlineKeyboardButton(f"Manage {lang['name'].title()}", callback_data=f"manage_seasons:{series_key}:{lang['name']}"),
            InlineKeyboardButton(f"Delete {lang['name'].title()}", callback_data=f"delete_language_confirm:{series_key}:{lang['name']}")
        ])
    
    buttons.append([InlineKeyboardButton("Add New Language", callback_data=f"add_language:{series_key}")])
    buttons.append([InlineKeyboardButton("Back to Series Menu", callback_data=f"edit_select_series:{series_key}")])
    
    reply_markup = InlineKeyboardMarkup(buttons)
    await message.edit_text(text, reply_markup=reply_markup, parse_mode=enums.ParseMode.MARKDOWN)


async def send_manage_seasons_menu(client, message, series_data, language_name):
    series_key = series_data['_id']
    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    seasons = current_lang.get("seasons", []) if current_lang else []

    text = f"**Managing Seasons for:** `{series_data['title']}` - `{language_name.title()}`\n\n"
    if not seasons:
        text += "No seasons added yet for this language."
    else:
        text += "Current Seasons:\n" + "\n".join([f"○ `{s['name'].title()}`" for s in seasons]) + "\n\n"

    buttons = []
    for season in seasons:
        buttons.append([
            InlineKeyboardButton(f"Manage {season['name'].title()}", callback_data=f"manage_qualities:{series_key}:{language_name}:{season['name']}"),
            InlineKeyboardButton(f"Delete {season['name'].title()}", callback_data=f"delete_season_confirm:{series_key}:{language_name}:{season['name']}")
        ])
    
    buttons.append([InlineKeyboardButton(f"Add New Season", callback_data=f"add_season:{series_key}:{language_name}")])
    buttons.append([InlineKeyboardButton("Back to Languages", callback_data=f"manage_languages:{series_key}")])
    
    reply_markup = InlineKeyboardMarkup(buttons)
    await message.edit_text(text, reply_markup=reply_markup, parse_mode=enums.ParseMode.MARKDOWN)


async def send_manage_qualities_menu(client, message, series_data, language_name, season_name):
    series_key = series_data['_id']
    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None) if current_lang else None
    qualities = current_season.get("qualities", []) if current_season else []

    text = f"**Managing Qualities for:** `{series_data['title']}` - `{language_name.title()}` - `{season_name.title()}`\n\n"
    if not qualities:
        text += "No qualities added yet for this season."
    else:
        text += "Current Qualities:\n" + "\n".join([f"○ `{q['name'].upper()}` (Link Key: `{q.get('link_key', 'N/A')}`)" for q in qualities]) + "\n\n"

    buttons = []
    for quality in qualities:
        buttons.append([
            InlineKeyboardButton(f"View Link {quality['name'].upper()}", callback_data=f"b:{quality['link_key']}"),
            # InlineKeyboardButton(f"Delete {quality['name'].upper()}", callback_data=f"delete_quality_confirm:{series_key}:{language_name}:{season_name}:{quality['name']}") # Future implementation
        ])
    
    buttons.append([InlineKeyboardButton(f"Add New Quality", callback_data=f"add_quality:{series_key}:{language_name}:{season_name}")])
    buttons.append([InlineKeyboardButton("Back to Seasons", callback_data=f"manage_seasons:{series_key}:{language_name}")])
    
    reply_markup = InlineKeyboardMarkup(buttons)
    await message.edit_text(text, reply_markup=reply_markup, parse_mode=enums.ParseMode.MARKDOWN)
