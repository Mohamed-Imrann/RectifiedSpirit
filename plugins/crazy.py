import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.crazy_db import add_series, get_series_name, add_language, add_season, add_series_links, get_languages, get_seasons, get_links, add_poster_to_db, get_poster_manuel
from info import ADMINS, PICS
from utils import temp
import random

@Client.on_message(filters.command("newseries") & filters.user(ADMINS))
async def new_series_command(client, message: Message):
    await message.reply_text(
        "Please enter the series title:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data="cancel_new_series")]
        ])
    )
    client.temp_data[message.from_user.id] = {"state": "waiting_for_series_title", "series_data": {}}

@Client.on_message(filters.command("crazy") & filters.user(ADMINS))
async def crazy_command(client: Client, message: Message):
    await message.reply_text("You called the crazy command! What's next?")

@Client.on_message(filters.text & filters.private & filters.user(ADMINS), group=2)
async def handle_new_series_input(client, message: Message):
    user_id = message.from_user.id
    if user_id not in client.temp_data:
        return # Not in a series creation flow

    state = client.temp_data[user_id].get("state")
    series_data = client.temp_data[user_id].get("series_data")

    if state == "waiting_for_series_title":
        series_data["title"] = message.text.strip()
        series_data["key"] = series_data["title"].lower().replace(" ", "")
        series_data["languages"] = []
        series_data["seasons"] = {}
        
        await message.reply_text(
            f"Series title set to: **{series_data['title']}**\n\nPlease enter the first language (e.g., English, Hindi):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data="cancel_new_series")]
            ])
        )
        client.temp_data[user_id]["state"] = "waiting_for_language"

    elif state == "waiting_for_language":
        language = message.text.strip()
        series_data["languages"].append(language)
        series_data["seasons"][language] = {}
        client.temp_data[user_id]["current_language"] = language
        
        await message.reply_text(
            f"Language **{language}** added.\n\nPlease enter the first season name for **{language}** (e.g., Season 1, Part 1):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Add Another Language", callback_data="add_another_language")],
                [InlineKeyboardButton("Done Adding Languages", callback_data="done_adding_languages")],
                [InlineKeyboardButton("Cancel", callback_data="cancel_new_series")]
            ])
        )
        client.temp_data[user_id]["state"] = "waiting_for_season"

    elif state == "waiting_for_season":
        season_name = message.text.strip()
        current_language = client.temp_data[user_id]["current_language"]
        series_data["seasons"][current_language][season_name] = {}
        client.temp_data[user_id]["current_season"] = season_name
        
        await message.reply_text(
            f"Season **{season_name}** added for **{current_language}**.\n\nPlease enter the first quality and link for **{season_name}** (e.g., 480p - https://link.to/file):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Add Another Season", callback_data="add_another_season")],
                [InlineKeyboardButton("Done Adding Seasons", callback_data="done_adding_seasons")],
                [InlineKeyboardButton("Cancel", callback_data="cancel_new_series")]
            ])
        )
        client.temp_data[user_id]["state"] = "waiting_for_quality_link"

    elif state == "waiting_for_quality_link":
        quality_link_input = message.text.strip()
        if " - " not in quality_link_input:
            await message.reply_text("Invalid format. Please use 'Quality - Link'.")
            return

        quality, link = quality_link_input.split(" - ", 1)
        current_language = client.temp_data[user_id]["current_language"]
        current_season = client.temp_data[user_id]["current_season"]
        
        series_data["seasons"][current_language][current_season][quality] = link
        
        await message.reply_text(
            f"Quality **{quality}** with link added for **{current_season}**.\n\nWhat's next?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Add Another Quality", callback_data="add_another_quality")],
                [InlineKeyboardButton("Done Adding Qualities", callback_data="done_adding_qualities")],
                [InlineKeyboardButton("Cancel", callback_data="cancel_new_series")]
            ])
        )
        client.temp_data[user_id]["state"] = "waiting_for_quality_link" # Stay in this state to add more qualities

    else:
        await message.reply_text("Something went wrong. Please start over with /newseries.")
        del client.temp_data[user_id]

@Client.on_callback_query(filters.regex("^add_another_language$") & filters.user(ADMINS))
async def add_another_language_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.message.edit_text(
        "Please enter the next language:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data="cancel_new_series")]
        ])
    )
    client.temp_data[user_id]["state"] = "waiting_for_language"
    await callback_query.answer()

@Client.on_callback_query(filters.regex("^done_adding_languages$") & filters.user(ADMINS))
async def done_adding_languages_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_data = client.temp_data[user_id]["series_data"]
    
    if not series_data["languages"]:
        await callback_query.answer("Please add at least one language.", show_alert=True)
        return

    # If no seasons were added for the last language, prompt for one
    current_language = client.temp_data[user_id].get("current_language")
    if current_language and not series_data["seasons"][current_language]:
        await callback_query.message.edit_text(
            f"No seasons added for **{current_language}**. Please enter the first season name for **{current_language}**:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data="cancel_new_series")]
            ])
        )
        client.temp_data[user_id]["state"] = "waiting_for_season"
        await callback_query.answer()
        return

    await callback_query.message.edit_text(
        "All languages and initial seasons/qualities collected. Please confirm to save the series.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Save Series", callback_data="save_new_series")],
            [InlineKeyboardButton("Cancel", callback_data="cancel_new_series")]
        ])
    )
    client.temp_data[user_id]["state"] = "confirm_save"
    await callback_query.answer()

@Client.on_callback_query(filters.regex("^add_another_season$") & filters.user(ADMINS))
async def add_another_season_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    current_language = client.temp_data[user_id]["current_language"]
    await callback_query.message.edit_text(
        f"Please enter the next season name for **{current_language}**:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data="cancel_new_series")]
        ])
    )
    client.temp_data[user_id]["state"] = "waiting_for_season"
    await callback_query.answer()

@Client.on_callback_query(filters.regex("^done_adding_seasons$") & filters.user(ADMINS))
async def done_adding_seasons_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_data = client.temp_data[user_id]["series_data"]
    current_language = client.temp_data[user_id]["current_language"]
    current_season = client.temp_data[user_id]["current_season"]

    if not series_data["seasons"][current_language][current_season]:
        await callback_query.answer("Please add at least one quality and link for the current season.", show_alert=True)
        return

    await callback_query.message.edit_text(
        "All seasons and qualities collected for the current language. What's next?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Add Another Language", callback_data="add_another_language")],
            [InlineKeyboardButton("Save Series", callback_data="save_new_series")],
            [InlineKeyboardButton("Cancel", callback_data="cancel_new_series")]
        ])
    )
    client.temp_data[user_id]["state"] = "confirm_save"
    await callback_query.answer()

@Client.on_callback_query(filters.regex("^add_another_quality$") & filters.user(ADMINS))
async def add_another_quality_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    current_language = client.temp_data[user_id]["current_language"]
    current_season = client.temp_data[user_id]["current_season"]
    await callback_query.message.edit_text(
        f"Please enter the next quality and link for **{current_season}** ({current_language}) (e.g., 720p - https://link.to/file):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data="cancel_new_series")]
        ])
    )
    client.temp_data[user_id]["state"] = "waiting_for_quality_link"
    await callback_query.answer()

@Client.on_callback_query(filters.regex("^done_adding_qualities$") & filters.user(ADMINS))
async def done_adding_qualities_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_data = client.temp_data[user_id]["series_data"]
    current_language = client.temp_data[user_id]["current_language"]
    current_season = client.temp_data[user_id]["current_season"]

    if not series_data["seasons"][current_language][current_season]:
        await callback_query.answer("Please add at least one quality and link for the current season.", show_alert=True)
        return

    await callback_query.message.edit_text(
        "Qualities for the current season are done. What's next?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Add Another Season for Current Language", callback_data="add_another_season")],
            [InlineKeyboardButton("Add Another Language", callback_data="add_another_language")],
            [InlineKeyboardButton("Save Series", callback_data="save_new_series")],
            [InlineKeyboardButton("Cancel", callback_data="cancel_new_series")]
        ])
    )
    client.temp_data[user_id]["state"] = "confirm_save"
    await callback_query.answer()

@Client.on_callback_query(filters.regex("^save_new_series$") & filters.user(ADMINS))
async def save_new_series_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    series_data = client.temp_data[user_id]["series_data"]

    # Save series metadata
    await add_series({
        "key": series_data["key"],
        "title": series_data["title"],
        "languages": series_data["languages"],
        "seasons": list(series_data["seasons"].keys()) # Store only season names in main series doc
    })

    # Save links for each season and quality
    for lang, seasons in series_data["seasons"].items():
        for season_name, qualities in seasons.items():
            link_key = f"{series_data['key'].lower().replace(' ', '')}-{lang.lower().replace(' ', '')}-{season_name.lower().replace(' ', '')}"
            await add_series_links(link_key, qualities) # qualities is a dict of {quality: link}

    await callback_query.message.edit_text(f"Series **{series_data['title']}** saved successfully!")
    del client.temp_data[user_id]
    await callback_query.answer("Series saved!", show_alert=True)

@Client.on_callback_query(filters.regex("^cancel_new_series$") & filters.user(ADMINS))
async def cancel_new_series_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id in client.temp_data:
        del client.temp_data[user_id]
    await callback_query.message.edit_text("Series creation cancelled.")
    await callback_query.answer("Cancelled.", show_alert=True)

# Placeholder for newmovie, editseries, editmovie, cloneseries, clonemovie, deletemovie, deleteallmovies
@Client.on_message(filters.command("newmovie") & filters.user(ADMINS))
async def new_movie_command(client, message: Message):
    await message.reply_text("New movie command not yet implemented.")

@Client.on_message(filters.command("editseries") & filters.user(ADMINS))
async def edit_series_command(client, message: Message):
    await message.reply_text("Edit series command not yet implemented. Use /admin_ui for advanced editing.")

@Client.on_message(filters.command("editmovie") & filters.user(ADMINS))
async def edit_movie_command(client, message: Message):
    await message.reply_text("Edit movie command not yet implemented.")

@Client.on_message(filters.command("cloneseries") & filters.user(ADMINS))
async def clone_series_command(client, message: Message):
    await message.reply_text("Clone series command not yet implemented.")

@Client.on_message(filters.command("clonemovie") & filters.user(ADMINS))
async def clone_movie_command(client, message: Message):
    await message.reply_text("Clone movie command not yet implemented.")

@Client.on_message(filters.command("deletemovie") & filters.user(ADMINS))
async def delete_movie_command(client, message: Message):
    await message.reply_text("Delete movie command not yet implemented.")

@Client.on_message(filters.command("deleteallmovies") & filters.user(ADMINS))
async def delete_all_movies_command(client, message: Message):
    await message.reply_text("Delete all movies command not yet implemented.")

@Client.on_message(filters.command("gadd") & filters.user(ADMINS))
async def gadd_command(client, message: Message):
    await message.reply_text("Global add filter command not yet implemented.")
