import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.utility_db import utility_db
from database.crazy_db import get_series_name, get_languages, get_seasons, get_links, series_collection, links_collection
from info import ADMINS

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@Client.on_message(filters.command("admin_ui") & filters.user(ADMINS))
async def admin_ui_command(client, message):
    await message.reply_text(
        "Welcome to the Admin UI! Please select an option:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Manage Series", callback_data="admin_manage_series")],
            [InlineKeyboardButton("Manage Movies", callback_data="admin_manage_movies")],
            [InlineKeyboardButton("Manage Global Filters", callback_data="admin_manage_gfilters")],
            [InlineKeyboardButton("Bot Stats", callback_data="admin_bot_stats")],
            [InlineKeyboardButton("Broadcast Message", callback_data="admin_broadcast")],
            [InlineKeyboardButton("Ban/Unban Users", callback_data="admin_ban_users")],
        ])
    )

@Client.on_message(filters.private & filters.user(ADMINS) & filters.command("admin"))
async def admin_panel(client: Client, message):
    await message.reply_text(
        "Welcome to the Admin Panel!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Manage Series Data", callback_data="manage_series_data")],
            # Add other admin options here
        ])
    )

@Client.on_callback_query(filters.regex("^admin_manage_series$"))
async def manage_series_callback(client, callback_query: CallbackQuery):
    await callback_query.message.edit_text(
        "Series Management:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Add New Series", callback_data="admin_add_series")],
            [InlineKeyboardButton("Edit Existing Series", callback_data="admin_edit_series")],
            [InlineKeyboardButton("Delete Series", callback_data="admin_delete_series")],
            [InlineKeyboardButton("View All Series", callback_data="admin_view_all_series")],
            [InlineKeyboardButton("Back to Main UI", callback_data="admin_main_ui")],
        ])
    )

@Client.on_callback_query(filters.regex("^admin_edit_series$"))
async def edit_series_callback(client, callback_query: CallbackQuery):
    await callback_query.message.edit_text(
        "Please enter the name of the series you want to edit:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data="admin_manage_series")]
        ])
    )
    # Store user state to expect series name
    await client.send_message(callback_query.from_user.id, "Waiting for series name...")
    client.temp_data[callback_query.from_user.id] = {"state": "waiting_for_series_name_edit"}

@Client.on_message(filters.text & filters.private & filters.user(ADMINS), group=1)
async def handle_series_name_for_edit(client, message):
    user_id = message.from_user.id
    if user_id in client.temp_data and client.temp_data[user_id].get("state") == "waiting_for_series_name_edit":
        series_name = message.text.strip()
        series_data = get_series_name(series_name)
        if series_data:
            # Store the series data in temp_data for the user
            await utility_db.update_temp_series_data(user_id, {
                "series_key": series_data["key"],
                "title": series_data["title"],
                "languages": get_languages(series_data["key"]),
                "seasons": {lang: {s: get_links(f"{series_data['key'].lower().replace(' ', '')}-{lang.lower().replace(' ', '')}-{s.lower().replace(' ', '')}") for s in get_seasons(series_data['key'])} for lang in get_languages(series_data['key'])}
            })
            
            await message.reply_text(
                f"Series '{series_data['title']}' selected. What do you want to edit?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Manage Languages", callback_data=f"admin_manage_languages_{series_data['key']}")],
                    [InlineKeyboardButton("Manage Seasons", callback_data=f"admin_manage_seasons_{series_data['key']}")],
                    [InlineKeyboardButton("Manage Qualities", callback_data=f"admin_manage_qualities_{series_data['key']}")],
                    [InlineKeyboardButton("Back to Series Management", callback_data="admin_manage_series")]
                ])
            )
        else:
            await message.reply_text(
                f"Series '{series_name}' not found. Please try again or cancel.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Cancel", callback_data="admin_manage_series")]
                ])
            )
        del client.temp_data[user_id] # Clear state after processing

# --- Language Management ---
@Client.on_callback_query(filters.regex("^admin_manage_languages_"))
async def manage_languages_callback(client, callback_query: CallbackQuery):
    series_key = callback_query.data.split("_")[3]
    user_id = callback_query.from_user.id
    
    user_data = await utility_db.get_temp_series_data(user_id)
    if not user_data or user_data.get("series_data", {}).get("series_key") != series_key:
        # If temp data is missing or for a different series, re-fetch
        series_data = get_series_name(series_key)
        if not series_data:
            await callback_query.answer("Series data not found. Please re-select the series.", show_alert=True)
            await manage_series_callback(client, callback_query)
            return
        await utility_db.update_temp_series_data(user_id, {
            "series_key": series_data["key"],
            "title": series_data["title"],
            "languages": get_languages(series_data["key"]),
            "seasons": {lang: {s: get_links(f"{series_data['key'].lower().replace(' ', '')}-{lang.lower().replace(' ', '')}-{s.lower().replace(' ', '')}") for s in get_seasons(series_data['key'])} for lang in get_languages(series_data['key'])}
        })
        user_data = await utility_db.get_temp_series_data(user_id) # Re-fetch updated temp data

    languages = user_data.get("series_data", {}).get("languages", [])
    
    buttons = []
    if languages:
        for lang in languages:
            buttons.append([InlineKeyboardButton(f"{lang} (Delete)", callback_data=f"admin_delete_language_{series_key}_{lang}")])
    else:
        buttons.append([InlineKeyboardButton("No languages found.", callback_data="do_nothing")])
    
    buttons.append([InlineKeyboardButton("Back to Edit Series", callback_data=f"admin_edit_series_selected_{series_key}")])
    
    await callback_query.message.edit_text(
        f"Languages for {user_data['series_data']['title']}:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@Client.on_callback_query(filters.regex("^admin_delete_language_"))
async def delete_language_callback(client, callback_query: CallbackQuery):
    parts = callback_query.data.split("_")
    series_key = parts[3]
    language = parts[4]
    
    # Confirm deletion
    await callback_query.message.edit_text(
        f"Are you sure you want to delete language '{language}' for series '{series_key}'? This will also delete all associated seasons and qualities from temporary data.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Yes, Delete", callback_data=f"admin_confirm_delete_language_{series_key}_{language}")],
            [InlineKeyboardButton("No, Cancel", callback_data=f"admin_manage_languages_{series_key}")]
        ])
    )

@Client.on_callback_query(filters.regex("^admin_confirm_delete_language_"))
async def confirm_delete_language_callback(client, callback_query: CallbackQuery):
    parts = callback_query.data.split("_")
    series_key = parts[4]
    language = parts[5]
    user_id = callback_query.from_user.id
    
    # Delete from temporary data
    await utility_db.delete_temp_language(user_id, language)
    
    # Optionally, delete from main crazy_db if this is meant to be permanent
    # get_series_name(series_key) # This function returns data, not an object to modify
    # To delete permanently, you'd need a function in crazy_db like:
    # crazy_db.delete_series_language_permanent(series_key, language)
    # And also delete associated links from links_collection
    # links_collection.delete_many({"series_key": {"$regex": f"^{series_key.lower().replace(' ', '')}-{language.lower().replace(' ', '')}-"}})
    
    await callback_query.answer(f"Language '{language}' deleted successfully from temporary data!", show_alert=True)
    
    # Refresh the language list
    await manage_languages_callback(client, callback_query)


# --- Season Management ---
@Client.on_callback_query(filters.regex("^admin_manage_seasons_"))
async def manage_seasons_callback(client, callback_query: CallbackQuery):
    series_key = callback_query.data.split("_")[3]
    user_id = callback_query.from_user.id
    
    user_data = await utility_db.get_temp_series_data(user_id)
    if not user_data or user_data.get("series_data", {}).get("series_key") != series_key:
        # Re-fetch series data if temp data is missing or for a different series
        series_data = get_series_name(series_key)
        if not series_data:
            await callback_query.answer("Series data not found. Please re-select the series.", show_alert=True)
            await manage_series_callback(client, callback_query)
            return
        await utility_db.update_temp_series_data(user_id, {
            "series_key": series_data["key"],
            "title": series_data["title"],
            "languages": get_languages(series_data["key"]),
            "seasons": {lang: {s: get_links(f"{series_data['key'].lower().replace(' ', '')}-{lang.lower().replace(' ', '')}-{s.lower().replace(' ', '')}") for s in get_seasons(series_data['key'])} for lang in get_languages(series_data['key'])}
        })
        user_data = await utility_db.get_temp_series_data(user_id) # Re-fetch updated temp data

    # Prompt user to select a language first if not already selected
    selected_language = user_data.get("series_data", {}).get("selected_language")
    if not selected_language:
        languages = user_data.get("series_data", {}).get("languages", [])
        if not languages:
            await callback_query.message.edit_text(
                "No languages found for this series. Please add languages first.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Back to Edit Series", callback_data=f"admin_edit_series_selected_{series_key}")]
                ])
            )
            return
        
        lang_buttons = [[InlineKeyboardButton(lang, callback_data=f"admin_select_lang_for_season_{series_key}_{lang}")] for lang in languages]
        lang_buttons.append([InlineKeyboardButton("Back to Edit Series", callback_data=f"admin_edit_series_selected_{series_key}")])
        await callback_query.message.edit_text(
            "Please select a language to manage its seasons:",
            reply_markup=InlineKeyboardMarkup(lang_buttons)
        )
        return

    seasons_data = user_data.get("series_data", {}).get("seasons", {}).get(selected_language, {})
    seasons = list(seasons_data.keys())
    
    buttons = []
    if seasons:
        for season in seasons:
            buttons.append([InlineKeyboardButton(f"{season} (Delete)", callback_data=f"admin_delete_season_{series_key}_{selected_language}_{season}")])
    else:
        buttons.append([InlineKeyboardButton("No seasons found for this language.", callback_data="do_nothing")])
    
    buttons.append([InlineKeyboardButton("Change Language", callback_data=f"admin_manage_seasons_{series_key}_change_lang")])
    buttons.append([InlineKeyboardButton("Back to Edit Series", callback_data=f"admin_edit_series_selected_{series_key}")])
    
    await callback_query.message.edit_text(
        f"Seasons for {user_data['series_data']['title']} ({selected_language}):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@Client.on_callback_query(filters.regex("^admin_select_lang_for_season_"))
async def select_lang_for_season_callback(client, callback_query: CallbackQuery):
    parts = callback_query.data.split("_")
    series_key = parts[4]
    language = parts[5]
    user_id = callback_query.from_user.id

    user_data = await utility_db.get_temp_series_data(user_id)
    if user_data:
        user_data["series_data"]["selected_language"] = language
        await utility_db.update_temp_series_data(user_id, user_data["series_data"])
    
    # Now proceed to manage seasons for the selected language
    await manage_seasons_callback(client, callback_query)

@Client.on_callback_query(filters.regex("^admin_manage_seasons_.*_change_lang$"))
async def change_season_language_callback(client, callback_query: CallbackQuery):
    series_key = callback_query.data.split("_")[3]
    user_id = callback_query.from_user.id
    
    user_data = await utility_db.get_temp_series_data(user_id)
    if user_data and "series_data" in user_data:
        user_data["series_data"]["selected_language"] = None # Clear selected language
        await utility_db.update_temp_series_data(user_id, user_data["series_data"])
    
    await manage_seasons_callback(client, callback_query) # Re-call to prompt for language selection

@Client.on_callback_query(filters.regex("^admin_delete_season_"))
async def delete_season_callback(client, callback_query: CallbackQuery):
    parts = callback_query.data.split("_")
    series_key = parts[3]
    language = parts[4]
    season_name = parts[5]
    
    # Confirm deletion
    await callback_query.message.edit_text(
        f"Are you sure you want to delete season '{season_name}' for series '{series_key}' ({language})? This will also delete all associated qualities from temporary data.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Yes, Delete", callback_data=f"admin_confirm_delete_season_{series_key}_{language}_{season_name}")],
            [InlineKeyboardButton("No, Cancel", callback_data=f"admin_manage_seasons_{series_key}")]
        ])
    )

@Client.on_callback_query(filters.regex("^admin_confirm_delete_season_"))
async def confirm_delete_season_callback(client, callback_query: CallbackQuery):
    parts = callback_query.data.split("_")
    series_key = parts[4]
    language = parts[5]
    season_name = parts[6]
    user_id = callback_query.from_user.id
    
    # Delete from temporary data
    await utility_db.delete_temp_season(user_id, language, season_name)
    
    # Optionally, delete from main crazy_db if this is meant to be permanent
    # crazy_db.delete_series_season(series_key, language, season_name) # This function exists in crazy_db
    # And also delete associated links from links_collection
    # links_collection.delete_many({"series_key": {"$regex": f"^{series_key.lower().replace(' ', '')}-{language.lower().replace(' ', '')}-{season_name.lower().replace(' ', '')}"}})
    
    await callback_query.answer(f"Season '{season_name}' deleted successfully from temporary data!", show_alert=True)
    
    # Refresh the season list
    await manage_seasons_callback(client, callback_query)


# --- Quality Management ---
@Client.on_callback_query(filters.regex("^admin_manage_qualities_"))
async def manage_qualities_callback(client, callback_query: CallbackQuery):
    series_key = callback_query.data.split("_")[3]
    user_id = callback_query.from_user.id
    
    user_data = await utility_db.get_temp_series_data(user_id)
    if not user_data or user_data.get("series_data", {}).get("series_key") != series_key:
        # Re-fetch series data if temp data is missing or for a different series
        series_data = get_series_name(series_key)
        if not series_data:
            await callback_query.answer("Series data not found. Please re-select the series.", show_alert=True)
            await manage_series_callback(client, callback_query)
            return
        await utility_db.update_temp_series_data(user_id, {
            "series_key": series_data["key"],
            "title": series_data["title"],
            "languages": get_languages(series_data["key"]),
            "seasons": {lang: {s: get_links(f"{series_data['key'].lower().replace(' ', '')}-{lang.lower().replace(' ', '')}-{s.lower().replace(' ', '')}") for s in get_seasons(series_data['key'])} for lang in get_languages(series_data['key'])}
        })
        user_data = await utility_db.get_temp_series_data(user_id) # Re-fetch updated temp data

    # Prompt user to select a language and season first if not already selected
    selected_language = user_data.get("series_data", {}).get("selected_language")
    selected_season = user_data.get("series_data", {}).get("selected_season")

    if not selected_language:
        languages = user_data.get("series_data", {}).get("languages", [])
        if not languages:
            await callback_query.message.edit_text(
                "No languages found for this series. Please add languages first.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Back to Edit Series", callback_data=f"admin_edit_series_selected_{series_key}")]
                ])
            )
            return
        
        lang_buttons = [[InlineKeyboardButton(lang, callback_data=f"admin_select_lang_for_quality_{series_key}_{lang}")] for lang in languages]
        lang_buttons.append([InlineKeyboardButton("Back to Edit Series", callback_data=f"admin_edit_series_selected_{series_key}")])
        await callback_query.message.edit_text(
            "Please select a language to manage its qualities:",
            reply_markup=InlineKeyboardMarkup(lang_buttons)
        )
        return
    
    if not selected_season:
        seasons_data = user_data.get("series_data", {}).get("seasons", {}).get(selected_language, {})
        seasons = list(seasons_data.keys())
        if not seasons:
            await callback_query.message.edit_text(
                f"No seasons found for {selected_language}. Please add seasons first.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Change Language", callback_data=f"admin_manage_qualities_{series_key}_change_lang")],
                    [InlineKeyboardButton("Back to Edit Series", callback_data=f"admin_edit_series_selected_{series_key}")]
                ])
            )
            return
        
        season_buttons = [[InlineKeyboardButton(season, callback_data=f"admin_select_season_for_quality_{series_key}_{selected_language}_{season}")] for season in seasons]
        season_buttons.append([InlineKeyboardButton("Change Language", callback_data=f"admin_manage_qualities_{series_key}_change_lang")])
        season_buttons.append([InlineKeyboardButton("Back to Edit Series", callback_data=f"admin_edit_series_selected_{series_key}")])
        await callback_query.message.edit_text(
            f"Please select a season for {selected_language} to manage its qualities:",
            reply_markup=InlineKeyboardMarkup(season_buttons)
        )
        return

    qualities_data = user_data.get("series_data", {}).get("seasons", {}).get(selected_language, {}).get(selected_season, {})
    qualities = list(qualities_data.keys())
    
    buttons = []
    if qualities:
        for quality in qualities:
            buttons.append([InlineKeyboardButton(f"{quality} (Delete)", callback_data=f"admin_delete_quality_{series_key}_{selected_language}_{selected_season}_{quality}")])
    else:
        buttons.append([InlineKeyboardButton("No qualities found for this season.", callback_data="do_nothing")])
    
    buttons.append([InlineKeyboardButton("Change Season", callback_data=f"admin_manage_qualities_{series_key}_change_season")])
    buttons.append([InlineKeyboardButton("Back to Edit Series", callback_data=f"admin_edit_series_selected_{series_key}")])
    
    await callback_query.message.edit_text(
        f"Qualities for {user_data['series_data']['title']} ({selected_language}, {selected_season}):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@Client.on_callback_query(filters.regex("^admin_select_lang_for_quality_"))
async def select_lang_for_quality_callback(client, callback_query: CallbackQuery):
    parts = callback_query.data.split("_")
    series_key = parts[4]
    language = parts[5]
    user_id = callback_query.from_user.id

    user_data = await utility_db.get_temp_series_data(user_id)
    if user_data:
        user_data["series_data"]["selected_language"] = language
        user_data["series_data"]["selected_season"] = None # Clear selected season when changing language
        await utility_db.update_temp_series_data(user_id, user_data["series_data"])
    
    await manage_qualities_callback(client, callback_query)

@Client.on_callback_query(filters.regex("^admin_select_season_for_quality_"))
async def select_season_for_quality_callback(client, callback_query: CallbackQuery):
    parts = callback_query.data.split("_")
    series_key = parts[5]
    language = parts[6]
    season_name = parts[7]
    user_id = callback_query.from_user.id

    user_data = await utility_db.get_temp_series_data(user_id)
    if user_data:
        user_data["series_data"]["selected_language"] = language # Ensure language is set
        user_data["series_data"]["selected_season"] = season_name
        await utility_db.update_temp_series_data(user_id, user_data["series_data"])
    
    await manage_qualities_callback(client, callback_query)

@Client.on_callback_query(filters.regex("^admin_manage_qualities_.*_change_lang$"))
async def change_quality_language_callback(client, callback_query: CallbackQuery):
    series_key = callback_query.data.split("_")[3]
    user_id = callback_query.from_user.id
    
    user_data = await utility_db.get_temp_series_data(user_id)
    if user_data and "series_data" in user_data:
        user_data["series_data"]["selected_language"] = None # Clear selected language
        user_data["series_data"]["selected_season"] = None # Clear selected season
        await utility_db.update_temp_series_data(user_id, user_data["series_data"])
    
    await manage_qualities_callback(client, callback_query) # Re-call to prompt for language selection

@Client.on_callback_query(filters.regex("^admin_manage_qualities_.*_change_season$"))
async def change_quality_season_callback(client, callback_query: CallbackQuery):
    series_key = callback_query.data.split("_")[3]
    user_id = callback_query.from_user.id
    
    user_data = await utility_db.get_temp_series_data(user_id)
    if user_data and "series_data" in user_data:
        user_data["series_data"]["selected_season"] = None # Clear selected season
        await utility_db.update_temp_series_data(user_id, user_data["series_data"])
    
    await manage_qualities_callback(client, callback_query) # Re-call to prompt for season selection


@Client.on_callback_query(filters.regex("^admin_delete_quality_"))
async def delete_quality_callback(client, callback_query: CallbackQuery):
    parts = callback_query.data.split("_")
    series_key = parts[3]
    language = parts[4]
    season_name = parts[5]
    quality = parts[6]
    
    # Confirm deletion
    await callback_query.message.edit_text(
        f"Are you sure you want to delete quality '{quality}' for series '{series_key}' ({language}, {season_name}) from temporary data?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Yes, Delete", callback_data=f"admin_confirm_delete_quality_{series_key}_{language}_{season_name}_{quality}")],
            [InlineKeyboardButton("No, Cancel", callback_data=f"admin_manage_qualities_{series_key}")]
        ])
    )

@Client.on_callback_query(filters.regex("^admin_confirm_delete_quality_"))
async def confirm_delete_quality_callback(client, callback_query: CallbackQuery):
    parts = callback_query.data.split("_")
    series_key = parts[4]
    language = parts[5]
    season_name = parts[6]
    quality = parts[7]
    user_id = callback_query.from_user.id
    
    # Delete from temporary data
    await utility_db.delete_temp_quality(user_id, language, season_name, quality)
    
    # Optionally, delete from main crazy_db if this is meant to be permanent
    # crazy_db.delete_series_quality_and_links(series_key, language, season_name, quality) # This function exists in crazy_db
    
    await callback_query.answer(f"Quality '{quality}' deleted successfully from temporary data!", show_alert=True)
    
    # Refresh the quality list
    await manage_qualities_callback(client, callback_query)


# --- Back button handlers for navigation ---
@Client.on_callback_query(filters.regex("^admin_edit_series_selected_"))
async def back_to_edit_series_selected(client, callback_query: CallbackQuery):
    series_key = callback_query.data.split("_")[3]
    series_data = get_series_name(series_key) # Re-fetch series data
    if series_data:
        await callback_query.message.edit_text(
            f"Series '{series_data['title']}' selected. What do you want to edit?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Manage Languages", callback_data=f"admin_manage_languages_{series_data['key']}")],
                [InlineKeyboardButton("Manage Seasons", callback_data=f"admin_manage_seasons_{series_data['key']}")],
                [InlineKeyboardButton("Manage Qualities", callback_data=f"admin_manage_qualities_{series_data['key']}")],
                [InlineKeyboardButton("Back to Series Management", callback_data="admin_manage_series")]
            ])
        )
    else:
        await callback_query.message.edit_text(
            "Series data not found. Please go back to Series Management.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back to Series Management", callback_data="admin_manage_series")]
            ])
        )

@Client.on_callback_query(filters.regex("^admin_main_ui$"))
async def back_to_main_ui(client, callback_query: CallbackQuery):
    await admin_ui_command(client, callback_query.message) # Re-call the main admin_ui command

@Client.on_callback_query(filters.regex("^manage_series_data$"))
async def manage_series_data_callback(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    temp_data = await utility_db.get_temp_series(user_id)

    if not temp_data:
        await query.message.edit_text("No temporary series data found for you.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Admin", callback_data="admin_panel")]]))
        return

    text = "Current Temporary Series Data:\n\n"
    
    # Display Languages
    languages = temp_data.get("languages", [])
    if languages:
        text += "Languages:\n"
        for lang in languages:
            text += f"- {lang}\n"
        text += "\n"
    
    # Display Seasons
    seasons = temp_data.get("seasons", [])
    if seasons:
        text += "Seasons:\n"
        for season in seasons:
            text += f"- {season}\n"
        text += "\n"

    # Display Qualities
    qualities = temp_data.get("qualities", [])
    if qualities:
        text += "Qualities:\n"
        for quality in qualities:
            text += f"- {quality}\n"
        text += "\n"

    # Construct inline keyboard with delete buttons
    keyboard = []
    if languages:
        for lang in languages:
            keyboard.append([InlineKeyboardButton(f"Delete Language: {lang}", callback_data=f"delete_lang_{lang}")])
    if seasons:
        for season in seasons:
            keyboard.append([InlineKeyboardButton(f"Delete Season: {season}", callback_data=f"delete_season_{season}")])
    if qualities:
        for quality in qualities:
            keyboard.append([InlineKeyboardButton(f"Delete Quality: {quality}", callback_data=f"delete_quality_{quality}")])
    
    keyboard.append([InlineKeyboardButton("Back to Admin", callback_data="admin_panel")])

    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


# Callback handlers for deleting languages, seasons, qualities
@Client.on_callback_query(filters.regex("^delete_lang_"))
async def delete_language_callback(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    language_to_delete = query.data.split("_", 2)[2] # e.g., "delete_lang_English" -> "English"
    
    await utility_db.delete_temp_language(user_id, language_to_delete)
    await query.answer(f"Language '{language_to_delete}' deleted.", show_alert=True)
    
    # Refresh the UI
    await manage_series_data_callback(client, query)

@Client.on_callback_query(filters.regex("^delete_season_"))
async def delete_season_callback(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    season_to_delete = query.data.split("_", 2)[2]
    
    await utility_db.delete_temp_season(user_id, season_to_delete)
    await query.answer(f"Season '{season_to_delete}' deleted.", show_alert=True)
    
    # Refresh the UI
    await manage_series_data_callback(client, query)

@Client.on_callback_query(filters.regex("^delete_quality_"))
async def delete_quality_callback(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    quality_to_delete = query.data.split("_", 2)[2]
    
    await utility_db.delete_temp_quality(user_id, quality_to_delete)
    await query.answer(f"Quality '{quality_to_delete}' deleted.", show_alert=True)
    
    # Refresh the UI
    await manage_series_data_callback(client, query)

@Client.on_callback_query(filters.regex("^admin_panel$"))
async def back_to_admin_panel(client: Client, query: CallbackQuery):
    await query.message.edit_text(
        "Welcome to the Admin Panel!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Manage Series Data", callback_data="manage_series_data")],
            # Add other admin options here
        ])
    )

# Placeholder for other admin UI functionalities
@Client.on_callback_query(filters.regex("^admin_manage_movies$"))
async def manage_movies_callback(client, callback_query: CallbackQuery):
    await callback_query.answer("Movie management not yet implemented.", show_alert=True)

@Client.on_callback_query(filters.regex("^admin_manage_gfilters$"))
async def manage_gfilters_callback(client, callback_query: CallbackQuery):
    await callback_query.answer("Global filters management not yet implemented.", show_alert=True)

@Client.on_callback_query(filters.regex("^admin_bot_stats$"))
async def bot_stats_callback(client, callback_query: CallbackQuery):
    await callback_query.answer("Bot stats not yet implemented.", show_alert=True)

@Client.on_callback_query(filters.regex("^admin_broadcast$"))
async def broadcast_callback(client, callback_query: CallbackQuery):
    await callback_query.answer("Broadcast message not yet implemented.", show_alert=True)

@Client.on_callback_query(filters.regex("^admin_ban_users$"))
async def ban_users_callback(client, callback_query: CallbackQuery):
    await callback_query.answer("Ban/Unban users not yet implemented.", show_alert=True)

@Client.on_callback_query(filters.regex("^admin_add_series$"))
async def add_series_callback(client, callback_query: CallbackQuery):
    await callback_query.answer("Add series not yet implemented.", show_alert=True)

@Client.on_callback_query(filters.regex("^admin_delete_series$"))
async def delete_series_callback(client, callback_query: CallbackQuery):
    await callback_query.answer("Delete series not yet implemented.", show_alert=True)

@Client.on_callback_query(filters.regex("^admin_view_all_series$"))
async def view_all_series_callback(client, callback_query: CallbackQuery):
    await callback_query.answer("View all series not yet implemented.", show_alert=True)

@Client.on_callback_query(filters.regex("^do_nothing$"))
async def do_nothing_callback(client, callback_query: CallbackQuery):
    await callback_query.answer() # Just dismiss the loading animation
