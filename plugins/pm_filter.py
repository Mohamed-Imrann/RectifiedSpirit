import asyncio
import re
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, InputMediaPhoto
from database.crazy_db import get_series_by_key, get_series_by_title, get_all_series_keys
from info import ADMINS, LOG_CHANNEL, DB_CHANNEL, RAW_DB_CHANNEL, IMDB, IMDB_POSTER, PM_TXT, SPELL_CHECK_TXT, CHANNELS_TXT, START_TXT, TMDB_API_KEY, NO_POSTER_FOUND_IMG
from Script import script
from utils import get_poster_from_tmdb, get_shortlink

# Regex to match series keys (e.g., S001, S002)
SERIES_KEY_REGEX = re.compile(r'^[Ss]\d{3}$')

# A dictionary to store user's last interaction time
# This is to prevent spamming the bot with rapid button clicks
user_last_interaction = defaultdict(int)
COOLDOWN_TIME = 2 # seconds

NO_POSTER_FOUND_IMG = ["https://envs.sh/esA.jpg"] # Placeholder image

async def get_series_poster_for_user(series_key: str, language_name: str = None, season_name: str = None):
    """
    Retrieves the most specific poster available for a series, language, or season.
    Falls back to higher-level posters if more specific ones are not found.
    """
    poster = get_specific_poster(series_key, language_name, season_name)
    return poster if poster else NO_POSTER_FOUND_IMG[0]

@Client.on_message(filters.private & filters.text & filters.incoming & filters.user(ADMINS))
async def pm_admin_filter(client: Client, message: Message):
    text = message.text.lower()
    if text.startswith("/"):
        return # Let other handlers deal with commands

    # Check if it's a series key
    if SERIES_KEY_REGEX.match(text):
        series_key = text.upper()
        series_data = await get_series_by_key(series_key)
        if series_data:
            await send_series_details(client, message, series_data)
            return
        else:
            await message.reply_text("No series found with that key.")
            return

    # Try to search by title
    series_data = await get_series_by_title(text)
    if series_data:
        await send_series_details(client, message, series_data)
    else:
        # If no series found, offer spell check or general message
        if SPELL_CHECK_TXT:
            await message.reply_text(SPELL_CHECK_TXT)
        else:
            await message.reply_text(PM_TXT)

@Client.on_message(filters.private & filters.text & filters.incoming & ~filters.user(ADMINS))
async def pm_user_filter(client: Client, message: Message):
    # For non-admin users, just respond with a general message
    if PM_TXT:
        await message.reply_text(PM_TXT)
    else:
        await message.reply_text(START_TXT) # Fallback to START_TXT if PM_TXT is not set

async def send_series_details(client: Client, message: Message, series_data: dict):
    title = series_data.get("title", "N/A")
    overview = series_data.get("overview", "No overview available.")
    poster_path = series_data.get("poster_path")
    languages = series_data.get("languages", {})
    
    caption = f"**{title}**\n\n{overview}"

    reply_markup = []
    for lang_code, lang_data in languages.items():
        lang_name = lang_data.get("name", lang_code.upper())
        seasons = lang_data.get("seasons", {})
        
        lang_buttons = []
        for season_num, season_data in seasons.items():
            season_name = season_data.get("name", f"Season {season_num}")
            # Assuming 'files' or 'links' exist for each season
            # For simplicity, let's just create a button for the season
            # In a real scenario, this would lead to another menu or direct links
            lang_buttons.append(InlineKeyboardButton(season_name, callback_data=f"season_{series_data['key']}_{lang_code}_{season_num}"))
        
        if lang_buttons:
            reply_markup.append([InlineKeyboardButton(lang_name, callback_data=f"lang_{series_data['key']}_{lang_code}")])
            # Add season buttons in a new row for each language
            reply_markup.append(lang_buttons)

    if not reply_markup:
        reply_markup.append([InlineKeyboardButton("No content available", callback_data="no_content")])

    keyboard = InlineKeyboardMarkup(reply_markup)

    poster_url = None
    if IMDB_POSTER and poster_path: # IMDB_POSTER is a flag to enable/disable poster fetching
        poster_url = await get_poster_from_tmdb(poster_path, TMDB_API_KEY)
    
    if poster_url:
        try:
            await message.reply_photo(photo=poster_url, caption=caption, reply_markup=keyboard)
        except Exception as e:
            print(f"Error sending photo: {e}. Sending text message instead.")
            await message.reply_text(caption, reply_markup=keyboard)
    else:
        # Fallback to default poster if IMDB_POSTER is False or poster not found
        if NO_POSTER_FOUND_IMG:
            try:
                await message.reply_photo(photo=NO_POSTER_FOUND_IMG[0], caption=caption, reply_markup=keyboard)
            except Exception as e:
                print(f"Error sending default photo: {e}. Sending text message instead.")
                await message.reply_text(caption, reply_markup=keyboard)
        else:
            await message.reply_text(caption, reply_markup=keyboard)

# Callback query handler for language and season buttons
@Client.on_callback_query(filters.regex(r"^(lang|season)_"))
async def callback_handler(client: Client, query):
    data = query.data
    parts = data.split("_")
    action = parts[0]
    series_key = parts[1]
    lang_code = parts[2]

    series_data = await get_series_by_key(series_key)
    if not series_data:
        await query.answer("Series data not found.", show_alert=True)
        return

    if action == "lang":
        # User clicked on a language button, show seasons for that language
        lang_data = series_data.get("languages", {}).get(lang_code)
        if lang_data:
            seasons = lang_data.get("seasons", {})
            if seasons:
                season_buttons = []
                for season_num, season_data in seasons.items():
                    season_name = season_data.get("name", f"Season {season_num}")
                    season_buttons.append(InlineKeyboardButton(season_name, callback_data=f"season_{series_key}_{lang_code}_{season_num}"))
                
                keyboard = InlineKeyboardMarkup([season_buttons])
                await query.message.edit_caption(
                    caption=f"**{series_data['title']} - {lang_data.get('name', lang_code.upper())}**\n\nSelect a season:",
                    reply_markup=keyboard
                )
            else:
                await query.answer("No seasons available for this language.", show_alert=True)
        else:
            await query.answer("Language data not found.", show_alert=True)
    elif action == "season":
        season_num = parts[3]
        lang_data = series_data.get("languages", {}).get(lang_code)
        if lang_data:
            season_data = lang_data.get("seasons", {}).get(season_num)
            if season_data:
                # Assuming season_data contains 'files' or 'links'
                files = season_data.get("files", []) # Or links
                if files:
                    file_buttons = []
                    for file_info in files:
                        file_name = file_info.get("name", "File")
                        file_link = file_info.get("link") # Assuming a direct link or shortlink
                        if file_link:
                            # Use get_shortlink if available and needed
                            final_link = await get_shortlink(file_link) # Assuming get_shortlink exists in utils
                            file_buttons.append(InlineKeyboardButton(file_name, url=final_link))
                    
                    if file_buttons:
                        keyboard = InlineKeyboardMarkup([file_buttons])
                        await query.message.edit_caption(
                            caption=f"**{series_data['title']} - {lang_data.get('name', lang_code.upper())} - {season_data.get('name', f'Season {season_num}')}**\n\nHere are the files:",
                            reply_markup=keyboard
                        )
                    else:
                        await query.answer("No files found for this season.", show_alert=True)
                else:
                    await query.answer("No files found for this season.", show_alert=True)
            else:
                await query.answer("Season data not found.", show_alert=True)
        else:
            await query.answer("Language data not found.", show_alert=True)
    
    await query.answer() # Acknowledge the query

def chunk_buttons(buttons, chunk_size=2):
    """
    Helper function to chunk buttons into lists of lists with a specified chunk size.
    """
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

@Client.on_message(filters.private & filters.text & filters.incoming & filters.user(ADMINS))
async def pm_admin_commands(client: Client, message: Message):
    # This handler will primarily be for admin messages not related to the series management UI
    # The series management UI commands and callbacks are handled in crazy.py
    if message.text == "/start":
        await message.reply_text(START_TXT.format(first_name=message.from_user.first_name, last_name=message.from_user.last_name), disable_web_page_preview=True)
    elif message.text == "/c":
        # Example: show channels
        await message.reply_text(CHANNELS_TXT, disable_web_page_preview=True)
    elif message.text == "/imdb":
        await message.reply_text(IMDB_POSTER, disable_web_page_preview=True)
    else:
        # For non-command text, we can still respond
        # await message.reply_text("Hello, Admin! I'm here to help manage your series. Use commands like /newseries, /editseries, /cloneseries, or /seriview to get started.")
        pass # Let crazy.py handle other text inputs for its state machine

@Client.on_message(filters.text & filters.private & filters.incoming & ~filters.user(ADMINS))
async def pm_text_filter(client: Client, message: Message):
    if message.text == "/start":
        await message.reply_text(START_TXT.format(first_name=message.from_user.first_name, last_name=message.from_user.last_name), disable_web_page_preview=True)
        return
    
    # Check subscription status for non-admin users
    if PM_TXT and not await is_subscribed(client, message):
        try:
            temp_msg = await message.reply_text(PM_TXT, disable_web_page_preview=True)
            await asyncio.sleep(60)
            await temp_msg.delete()
            return
        except Exception as e:
            logger.error(f"Error sending PM_TXT or deleting message: {e}")
            return # Don't proceed if subscription check or message sending fails

    query = message.text.strip().lower()
    if not query:
        return

    # Basic anti-flood mechanism
    current_time = time.time()
    if current_time - user_last_interaction[message.from_user.id] < COOLDOWN_TIME:
        return # Ignore rapid messages
    user_last_interaction[message.from_user.id] = current_time

    try:
        results = await get_search_results(query, filter=True)
        if not results:
            if SPELL_CHECK_TXT:
                imdb_data = await get_poster(query, bulk=True)
                if imdb_data:
                    buttons = [[InlineKeyboardButton(f"{i.get('title')} ({i.get('year')})", callback_data=f"spellcheck_{i.get('imdb_id')}") for i in imdb_data]]
                    markup = InlineKeyboardMarkup(buttons)
                    await message.reply_text(SPELL_CHECK_TXT.format(query), reply_markup=markup, disable_web_page_preview=True)
            return

        # Filter out unpublished series from search results for users
        published_results = [
            r for r in results if r.get('data', {}).get('published', False)
        ]

        if not published_results:
            if SPELL_CHECK_TXT:
                imdb_data = await get_poster(query, bulk=True)
                if imdb_data:
                    buttons = [[InlineKeyboardButton(f"{i.get('title')} ({i.get('year')})", callback_data=f"spellcheck_{i.get('imdb_id')}") for i in imdb_data]]
                    markup = InlineKeyboardMarkup(buttons)
                    await message.reply_text(SPELL_CHECK_TXT.format(query), reply_markup=markup, disable_web_page_preview=True)
            return

        # Group results by series key if a single series contains multiple matches (e.g., different languages/seasons of the same show)
        grouped_results = defaultdict(list)
        for r in published_results:
            series_key = r.get('data', {}).get('_id') # The series key from crazy_db
            if series_key:
                grouped_results[series_key].append(r)
            else:
                # Fallback for old filters or files not linked to a crazy_db series
                grouped_results[r['file_name']].append(r) # Group by filename if no series key

        if len(grouped_results) == 1 and next(iter(grouped_results.values()))[0].get('data', {}).get('_id'):
            # If only one series, proceed to show its languages/seasons if available via crazy_db
            series_data = get_series_by_key(next(iter(grouped_results.keys())))
            if series_data and series_data.get('published') and series_data.get('languages'):
                await show_series_languages(client, message, series_data)
                return

        buttons = []
        for series_key, files in grouped_results.items():
            series_data = get_series_by_key(series_key)
            if series_data and series_data.get('published'):
                title = series_data.get('title', series_key)
                # Show the primary entry point for this series
                buttons.append(
                    InlineKeyboardButton(f"🎬 {title}", callback_data=f"series_select:{series_key}")
                )
            else:
                # For non-crazy_db entries or unpublished crazy_db entries, display file details
                # This part is simplified, could be expanded to list individual files if needed
                for file_data in files:
                    buttons.append(
                        InlineKeyboardButton(
                            f"📁 {file_data.get('file_name', 'Unknown File')}",
                            callback_data=f"files:{file_data['_id']}" # Assuming _id is unique for files
                        )
                    )

        if not buttons: # If all found series were unpublished or no valid buttons could be created
            if SPELL_CHECK_TXT:
                imdb_data = await get_poster(query, bulk=True)
                if imdb_data:
                    buttons = [[InlineKeyboardButton(f"{i.get('title')} ({i.get('year')})", callback_data=f"spellcheck_{i.get('imdb_id')}") for i in imdb_data]]
                    markup = InlineKeyboardMarkup(buttons)
                    await message.reply_text(SPELL_CHECK_TXT.format(query), reply_markup=markup, disable_web_page_preview=True)
            return

        reply_markup = InlineKeyboardMarkup(chunk_buttons(buttons, chunk_size=2)) # Arrange buttons for better display
        await message.reply_text(
            "Here are the results found for your query. Please select a series or file:",
            reply_markup=reply_markup,
            parse_mode="html"
        )

    except FloodWait as e:
        logger.warning(f"FloodWait in pm_text_filter: {e.value} seconds")
        await asyncio.sleep(e.value)
    except Exception as e:
        logger.error(f"Error in pm_text_filter: {e}", exc_info=True)
        await message.reply_text("An error occurred while processing your request.")

@Client.on_callback_query(filters.regex(r"^spellcheck_") & ~filters.user(ADMINS))
async def spellcheck_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if time.time() - user_last_interaction[user_id] < COOLDOWN_TIME:
        await callback_query.answer("Please wait a moment before trying again.", show_alert=True)
        return
    user_last_interaction[user_id] = time.time()

    imdb_id = callback_query.data.split("_", 1)[1]
    await callback_query.answer("Searching...", cache_time=0)

    try:
        # Fetch details using imdb_id
        movie_data = await get_poster(imdb_id, id=True)
        if not movie_data:
            await callback_query.message.edit_text("Could not find details for this ID.")
            return

        # Try to find a matching series in the crazy_db
        imdb_title = movie_data.get('title')
        found_series = None
        all_series = get_series_by_key("") # Use an empty string or a special key to get all series
        for series in all_series:
            series_title = series.get('title', '')
            if fuzz.ratio(imdb_title.lower(), series_title.lower()) > 80 and series.get('published'):
                found_series = series
                break
        
        if found_series:
            await show_series_languages(client, callback_query.message, found_series)
        else:
            text = f"<b>Title:</b> {movie_data.get('title', 'N/A')}\n" \
                   f"<b>Year:</b> {movie_data.get('year', 'N/A')}\n" \
                   f"<b>IMDb ID:</b> <code>{movie_data.get('imdb_id', 'N/A')}</code>\n\n" \
                   "No matching published series found in the database for this entry. You can try another search or contact admin."
            
            poster = movie_data.get('poster') or NO_POSTER_FOUND_IMG[0]
            
            try:
                await callback_query.message.edit_media(
                    InputMediaPhoto(media=poster, caption=text, parse_mode="html"),
                    reply_markup=None # Remove buttons as no series found
                )
            except MessageNotModified:
                pass # If content is the same, no need to edit
            except Exception as e:
                logger.error(f"Error editing message media in spellcheck_callback: {e}")
                await callback_query.message.edit_text(text, reply_markup=None, parse_mode="html")

    except Exception as e:
        logger.error(f"Error in spellcheck_callback: {e}")
        await callback_query.message.edit_text("An error occurred while fetching details.")

async def show_series_languages(client: Client, message: Message, series_data: dict):
    series_key = series_data['_id']
    title = series_data.get('title', 'N/A')
    languages = series_data.get('languages', [])

    if not languages:
        text = f"<b>Title:</b> <code>{title}</code>\n\nNo languages found for this series. Please try again later or contact the admin."
        poster = await get_series_poster_for_user(series_key)
        try:
            if message.photo: # If original message was a photo
                await message.edit_media(InputMediaPhoto(media=poster, caption=text, parse_mode="html"))
            else:
                await message.edit_text(text, parse_mode="html")
        except MessageNotModified:
            pass
        return

    text = f"<b>Series:</b> <code>{title}</code>\n\nSelect a language:"
    buttons = []
    for lang in languages:
        if lang.get("seasons"): # Only show languages that have seasons
            buttons.append(
                InlineKeyboardButton(lang['name'], callback_data=f"user_lang:{series_key}:{lang['name']}")
            )
    
    if not buttons: # If no languages have seasons, don't show language selection
        text = f"<b>Series:</b> <code>{title}</code>\n\nNo active content (seasons/qualities) found for this series. Please try again later or contact the admin."
        poster = await get_series_poster_for_user(series_key)
        try:
            if message.photo:
                await message.edit_media(InputMediaPhoto(media=poster, caption=text, parse_mode="html"))
            else:
                await message.edit_text(text, parse_mode="html")
        except MessageNotModified:
            pass
        return

    reply_markup = InlineKeyboardMarkup(chunk_buttons(buttons, chunk_size=2)) # chunk_size=2 for horizontal layout
    
    poster = await get_series_poster_for_user(series_key)
    try:
        if message.photo:
            await message.edit_media(
                InputMediaPhoto(media=poster, caption=text, parse_mode="html"),
                reply_markup=reply_markup
            )
        else:
            await message.reply_photo(
                photo=poster,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="html"
            )
            await message.delete() # Delete original text message if new photo message is sent
    except MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"Error sending/editing language selection message: {e}")
        # Fallback to text message if photo fails
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="html")

@Client.on_callback_query(filters.regex(r"^series_select:") & ~filters.user(ADMINS))
async def series_select_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if time.time() - user_last_interaction[user_id] < COOLDOWN_TIME:
        await callback_query.answer("Please wait a moment before trying again.", show_alert=True)
        return
    user_last_interaction[user_id] = time.time()

    series_key = callback_query.data.split(":")[1]
    await callback_query.answer("Loading series details...", cache_time=0)

    series_data = get_series_by_key(series_key)
    if not series_data or not series_data.get('published'):
        await callback_query.message.edit_text("Series not found or not published.")
        return

    await show_series_languages(client, callback_query.message, series_data)

@Client.on_callback_query(filters.regex(r"^user_lang:") & ~filters.user(ADMINS))
async def user_language_select_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if time.time() - user_last_interaction[user_id] < COOLDOWN_TIME:
        await callback_query.answer("Please wait a moment before trying again.", show_alert=True)
        return
    user_last_interaction[user_id] = time.time()

    _, series_key, language_name = callback_query.data.split(":")
    await callback_query.answer(f"Loading seasons for {language_name}...", cache_time=0)

    series_data = get_series_by_key(series_key)
    if not series_data or not series_data.get('published'):
        await callback_query.message.edit_text("Series not found or not published.")
        return

    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    if not current_lang:
        await callback_query.message.edit_text("Language not found for this series.")
        return

    seasons = current_lang.get("seasons", [])
    if not seasons:
        await callback_query.message.edit_text(f"No seasons found for {language_name} in {series_data.get('title', 'N/A')}.")
        return

    text = f"<b>Series:</b> <code>{series_data.get('title', 'N/A')}</code>\n" \
           f"<b>Language:</b> <code>{language_name}</code>\n\n" \
           "Select a season:"
    
    buttons = []
    for season in seasons:
        if season.get("qualities"): # Only show seasons that have qualities
            buttons.append(
                InlineKeyboardButton(season['name'], callback_data=f"user_season:{series_key}:{language_name}:{season['name']}")
            )
    
    if not buttons: # If no seasons have qualities, don't show season selection
        await callback_query.message.edit_text(f"No active content (qualities) found for {language_name} in {series_data.get('title', 'N/A')}. Please try again later or contact the admin.")
        return

    reply_markup = InlineKeyboardMarkup(chunk_buttons(buttons, chunk_size=2))
    
    poster = await get_series_poster_for_user(series_key, language_name=language_name)
    try:
        await callback_query.message.edit_media(
            InputMediaPhoto(media=poster, caption=text, parse_mode="html"),
            reply_markup=reply_markup
        )
    except MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"Error editing message media in user_language_select_callback: {e}")
        await callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="html")

@Client.on_callback_query(filters.regex(r"^user_season:") & ~filters.user(ADMINS))
async def user_season_select_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if time.time() - user_last_interaction[user_id] < COOLDOWN_TIME:
        await callback_query.answer("Please wait a moment before trying again.", show_alert=True)
        return
    user_last_interaction[user_id] = time.time()

    _, series_key, language_name, season_name = callback_query.data.split(":")
    await callback_query.answer(f"Loading qualities for {season_name}...", cache_time=0)

    series_data = get_series_by_key(series_key)
    if not series_data or not series_data.get('published'):
        await callback_query.message.edit_text("Series not found or not published.")
        return

    current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
    current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None) if current_lang else None
    
    if not current_season:
        await callback_query.message.edit_text("Season not found for this language.")
        return

    qualities = current_season.get("qualities", [])
    if not qualities:
        await callback_query.message.edit_text(f"No qualities found for {season_name} in {language_name}.")
        return

    text = f"<b>Series:</b> <code>{series_data.get('title', 'N/A')}</code>\n" \
           f"<b>Language:</b> <code>{language_name}</code>\n" \
           f"<b>Season:</b> <code>{season_name}</code>\n\n" \
           "Select a quality:"
    
    buttons = []
    for quality in qualities:
        if quality.get("link_key") and quality["link_key"] != "PENDING_LINK": # Only show qualities with actual links
            buttons.append(
                InlineKeyboardButton(quality['name'], callback_data=f"user_quality:{series_key}:{language_name}:{season_name}:{quality['name']}")
            )
    
    if not buttons: # If no qualities have valid links, don't show quality selection
        await callback_query.message.edit_text(f"No active content (files) found for {season_name} in {language_name} for {series_data.get('title', 'N/A')}. Please try again later or contact the admin.")
        return

    reply_markup = InlineKeyboardMarkup(chunk_buttons(buttons, chunk_size=2))

    poster = await get_series_poster_for_user(series_key, language_name=language_name, season_name=season_name)
    try:
        await callback_query.message.edit_media(
            InputMediaPhoto(media=poster, caption=text, parse_mode="html"),
            reply_markup=reply_markup
        )
    except MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"Error editing message media in user_season_select_callback: {e}")
        await callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="html")

@Client.on_callback_query(filters.regex(r"^user_quality:") & ~filters.user(ADMINS))
async def user_quality_select_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if time.time() - user_last_interaction[user_id] < COOLDOWN_TIME:
        await callback_query.answer("Please wait a moment before trying again.", show_alert=True)
        return
    user_last_interaction[user_id] = time.time()

    _, series_key, language_name, season_name, quality_name = callback_query.data.split(":")
    await callback_query.answer(f"Fetching files for {quality_name}...", cache_time=0)

    series_data = get_series_by_key(series_key)
    if not series_data or not series_data.get('published'):
        await callback_query.message.edit_text("Series not found or not published.")
        return

    link_key = None
    codec = None

    # Navigate through the series_data to find the quality's link_key and codec
    for lang in series_data.get("languages", []):
        if lang["name"].lower() == language_name.lower():
            for season in lang.get("seasons", []):
                if season["name"].lower() == season_name.lower():
                    for quality in season.get("qualities", []):
                        if quality["name"].lower() == quality_name.lower():
                            link_key = quality.get("link_key")
                            codec = quality.get("codec")
                            break
                    if link_key:
                        break
            if link_key:
                break

    if not link_key or link_key == "PENDING_LINK":
        await callback_query.message.edit_text(f"Files for {quality_name} are not yet available. Please try again later or contact the admin.")
        return
    
    # Parse the link_key: "get_{channel_id}_{first_msg_id}_{last_msg_id}"
    try:
        parts = link_key.split('_')
        db_channel_raw_id = int(parts[1])
        first_msg_id = int(parts[2])
        last_msg_id = int(parts[3])
        
        # Convert raw_id back to Pyrogram format channel ID (e.g., -100XXXXXXXXX)
        db_channel_id = int(f"-100{db_channel_raw_id}")

        # Construct the caption for the message
        caption_text = (
            f"<b>Series:</b> <code>{series_data.get('title', 'N/A')}</code>\n"
            f"<b>Language:</b> <code>{language_name}</code>\n"
            f"<b>Season:</b> <code>{season_name}</code>\n"
            f"<b>Quality:</b> <code>{quality_name}</code>\n"
        )
        if codec:
            caption_text += f"<b>Codec:</b> <code>{codec}</code>\n"
        caption_text += "\n" \
                        f"Files from [here](https://t.me/c/{db_channel_raw_id}/{first_msg_id}) to [here](https://t.me/c/{db_channel_raw_id}/{last_msg_id})\n\n" \
                        "Click the button below to get your files."
        
        button_text = f"Get {quality_name} Files"
        get_files_url = f"https://t.me/c/{db_channel_raw_id}/{first_msg_id}-{last_msg_id}" # Direct range link
        # Note: Pyrogram's send_message and forward_messages are better for actual file delivery.
        # This direct link is for simplicity but might not be ideal for large numbers of files.
        # A more robust solution would involve forwarding messages from the DB_CHANNEL.

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(button_text, url=get_files_url)],
            [InlineKeyboardButton("⬅️ Back to Qualities", callback_data=f"user_season:{series_key}:{language_name}:{season_name}")]
        ])

        poster = await get_series_poster_for_user(series_key, language_name=language_name, season_name=season_name)
        try:
            await callback_query.message.edit_media(
                InputMediaPhoto(media=poster, caption=caption_text, parse_mode="html"),
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        except MessageNotModified:
            pass
        except Exception as e:
            logger.error(f"Error editing message media in user_quality_select_callback: {e}")
            await callback_query.message.edit_text(caption_text, reply_markup=reply_markup, parse_mode="html", disable_web_page_preview=True)

    except ValueError:
        await callback_query.message.edit_text("Invalid file link found in database. Please contact admin.")
    except Exception as e:
        logger.error(f"Error in user_quality_select_callback: {e}", exc_info=True)
        await callback_query.message.edit_text("An error occurred while fetching files. Please contact admin.")

@Client.on_callback_query(filters.regex(r"^files:") & ~filters.user(ADMINS))
async def file_details_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if time.time() - user_last_interaction[user_id] < COOLDOWN_TIME:
        await callback_query.answer("Please wait a moment before trying again.", show_alert=True)
        return
    user_last_interaction[user_id] = time.time()

    file_id = callback_query.data.split(":")[1]
    await callback_query.answer("Fetching file details...", cache_time=0)

    try:
        files = await get_file_details(file_id)
        if not files:
            await callback_query.message.edit_text("File not found in database.")
            return

        file_data = files[0] # Assuming get_file_details returns a list and we only need the first item for a specific file_id

        caption = f"<b>File Name:</b> <code>{file_data.file_name}</code>\n" \
                  f"<b>Size:</b> <code>{get_size(file_data.file_size)}</code>\n"
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Get File", callback_data=f"get_file:{file_data.file_id}")]
        ])
        
        try:
            # If the original message was a photo/video, try to edit media. Otherwise, send new message.
            if callback_query.message.photo or callback_query.message.video:
                await callback_query.message.edit_media(
                    InputMediaPhoto(media=file_data.file_id, caption=caption, parse_mode="html"), # Use file_id as media
                    reply_markup=reply_markup
                )
            else:
                await callback_query.message.edit_text(caption, reply_markup=reply_markup, parse_mode="html")
        except MessageNotModified:
            pass # No change, don't modify
        except Exception as e:
            logger.error(f"Error editing/sending file details message: {e}")
            await callback_query.message.edit_text(caption, reply_markup=reply_markup, parse_mode="html")

    except Exception as e:
        logger.error(f"Error in file_details_callback: {e}", exc_info=True)
        await callback_query.message.edit_text("An error occurred while fetching file details.")

@Client.on_callback_query(filters.regex(r"^get_file:") & ~filters.user(ADMINS))
async def get_file_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if time.time() - user_last_interaction[user_id] < COOLDOWN_TIME:
        await callback_query.answer("Please wait a moment before trying again.", show_alert=True)
        return
    user_last_interaction[user_id] = time.time()

    file_id_to_send = callback_query.data.split(":")[1]
    await callback_query.answer("Sending file...", cache_time=0)

    try:
        # Assuming file_id_to_send is a direct file_id from telegram
        await client.send_cached_media(
            chat_id=user_id,
            file_id=file_id_to_send,
            caption="Here's your file!"
        )
    except FloodWait as e:
        logger.warning(f"FloodWait in get_file_callback: {e.value} seconds")
        await callback_query.answer(f"Too many requests! Please wait {e.value} seconds.", show_alert=True)
        await asyncio.sleep(e.value)
        # Attempt to send again after cooldown
        try:
            await client.send_cached_media(
                chat_id=user_id,
                file_id=file_id_to_send,
                caption="Here's your file!"
            )
        except Exception as retry_e:
            logger.error(f"Error sending file after retry: {retry_e}")
            await callback_query.message.reply_text("Failed to send file after waiting. Please try again later.")
    except Exception as e:
        logger.error(f"Error sending file in get_file_callback: {e}", exc_info=True)
        await callback_query.message.reply_text("Failed to send file. It might be invalid or not accessible.")
