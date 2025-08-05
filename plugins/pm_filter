import re
import pyrogram 
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from info import ADMINS, SPELL_CHECK_IMAGE, NO_POSTER_FOUND_IMG, AUTO_DELETE_TIME, AUTO_DELETE_MSG, BOT_USERNAME, SUPPORT_GROUP_LINK, UPDATES_CHANNEL_LINK, BOT_OWNER_LINK, REQ_CHANNEL_ONE, REQ_CHANNEL_TWO
from database.crazy_db import (
    get_series, get_series_by_key, get_languages, get_seasons, get_qualities, get_quality_link, get_specific_poster
)
from database.gfilters_mdb import (
    find_gfilter,
    get_gfilters,
    del_allg # Import del_allg for global filter deletion
)
from utils import temp, get_size, get_settings, delete_file # Import delete_file from utils
from plugins.request_forcesub import create_request_forcesub_buttons # Import for force sub buttons
from utils import is_subscribed # Import for AUTH_CHANNEL check
import asyncio
import difflib
import logging
import random

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

requestor = {} # To track who initiated a request in a group chat

async def DeleteMessage(msg):
    await asyncio.sleep(AUTO_DELETE_TIME) # Messages will be deleted after AUTO_DELETE_TIME
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message {msg.id}: {e}")

def find_close_matches(query, possibilities, n=3, cutoff=0.6):
    return difflib.get_close_matches(query, possibilities, n, cutoff)

def chunk_buttons(buttons, chunk_size=3):
    return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]

@Client.on_message(filters.text & (filters.private | filters.group))
async def handle_message(client, message):
    # First, check for global filters
    glob_handled = await global_filters(client, message)
    if not glob_handled:
        # If no global filter matched, proceed to series filter
        await series_filter(client, message)

async def global_filters(client, message, text=False):
    group_id = message.chat.id
    name = text or message.text 
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id 
    keywords = await get_gfilters("gfilters")
    
    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[\\W])" + re.escape(keyword) + r"( |$|[\\W])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_gfilter("gfilters", keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
            
            try:
                if fileid == "None":
                    if btn == "[]":
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)
                        piroxrk = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                elif btn == "[]":
                    piroxrk = await client.send_cached_media(
                        group_id,
                        fileid,
                        caption=reply_text or "",
                        reply_to_message_id=reply_id
                    )
                else:
                    button = eval(btn)
                    piroxrk = await message.reply_cached_media(
                        fileid,
                        caption=reply_text or "",
                        reply_markup=InlineKeyboardMarkup(button),
                        reply_to_message_id=reply_id
                    )
                return True # Global filter handled the message
            except Exception as e:
                logger.exception(e)
                return False # Error occurred, but still considered handled
    return False # No global filter matched

async def series_filter(client, message):
    text = message.text.strip()
    series_list_data = get_series() # Get all series documents
    
    # Filter for published series only
    published_series = [s for s in series_list_data if s.get('published', False)]

    series_keys = [s['_id'] for s in published_series]
    series_titles = [s['title'] for s in published_series]

    series_data = None

    # Try exact match by key or title
    for s in published_series:
        if text.lower() == s['_id'].lower() or text.lower() == s['title'].lower():
            series_data = s
            break
    
    # If no exact match, try close matches using titles for user-friendly search
    if not series_data:
        # Use fuzzy matching on titles for better user experience with spaces/typos
        best_match_title = None
        highest_score = 0
        for title in series_titles:
            score = difflib.SequenceMatcher(None, text.lower(), title.lower()).ratio()
            if score > highest_score:
                highest_score = score
                best_match_title = title
        
        if best_match_title and highest_score >= 0.6: # Threshold for a "good enough" match
            # Find all close matches above a certain threshold
            close_matches_titles = [
                s['title'] for s in published_series 
                if difflib.SequenceMatcher(None, text.lower(), s['title'].lower()).ratio() >= 0.6
            ]
            # Sort by similarity score (descending)
            close_matches_titles.sort(key=lambda x: difflib.SequenceMatcher(None, text.lower(), x.lower()).ratio(), reverse=True)
            
            buttons = []
            for match_title in close_matches_titles[:5]: # Limit to top 5 suggestions
                matched_series = next((s for s in published_series if s['title'] == match_title), None)
                if matched_series:
                    buttons.append(
                        InlineKeyboardButton(match_title, callback_data=f"user_series_select:{matched_series['_id']}")
                    )
            
            if buttons:
                buttons_chunked = chunk_buttons(buttons, chunk_size=1)
                reply_markup = InlineKeyboardMarkup(buttons_chunked)
                etho = await message.reply_photo(photo=random.choice(SPELL_CHECK_IMAGE), caption="<b>Choose Your Series:</b>", reply_markup=reply_markup)
                reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.from_user.id
                requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
                asyncio.create_task(DeleteMessage(etho))
                return

    if series_data:
        await send_series_details_to_user(client, message, series_data)

async def send_series_details_to_user(client, message, series_data, edit_message=None):
    languages = series_data.get("languages", [])
    
    # Filter out languages with no seasons
    languages = [lang for lang in languages if lang.get('seasons')]

    if not languages:
        if edit_message:
            await edit_message.edit_text("No languages available for this series yet.")
        else:
            await message.reply_text("No languages available for this series yet.")
        return

    reply_text = (
        f"○ <b>Title:</b> <code>{series_data['title']}</code>\n"
        f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>\n"
        f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>\n"
        f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>\n\n"
        "Select the language you need...!"
    )
    
    poster_to_use = get_specific_poster(series_data['_id']) or NO_POSTER_FOUND_IMG
    
    buttons = []
    for lang in languages:
        buttons.append(InlineKeyboardButton(lang['name'], callback_data=f"user_lang:{series_data['_id']}:{lang['name']}"))
    
    buttons_chunked = chunk_buttons(buttons, chunk_size=2)
    reply_markup = InlineKeyboardMarkup(buttons_chunked)
    
    try:
        if edit_message:
            await edit_message.edit_media(
                media=InputMediaPhoto(media=poster_to_use, caption=reply_text, parse_mode=enums.ParseMode.HTML),
                reply_markup=reply_markup
            )
            etho = edit_message
        else:
            etho = await message.reply_photo(photo=poster_to_use, caption=reply_text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
        
        reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.from_user.id
        requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
        asyncio.create_task(DeleteMessage(etho))
    except pyrogram.errors.MediaEmpty:
        logger.error(f"MediaEmpty error for poster: {poster_to_use}. Falling back to NO_POSTER_FOUND_IMG.")
        if edit_message:
            await edit_message.edit_media(
                media=InputMediaPhoto(media=NO_POSTER_FOUND_IMG, caption=reply_text, parse_mode=enums.ParseMode.HTML),
                reply_markup=reply_markup
            )
            etho = edit_message
        else:
            etho = await message.reply_photo(photo=NO_POSTER_FOUND_IMG, caption=reply_text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
        
        reply_etho_user_id = etho.reply_to_message.from_user.id if etho.reply_to_message else message.from_user.id
        requestor[f"{etho.chat.id}•{etho.id}"] = reply_etho_user_id
        asyncio.create_task(DeleteMessage(etho))
    except Exception as e:
        logger.error(f"Error sending series details to user: {e}")
        if edit_message:
            await edit_message.edit_text("An error occurred while fetching series details.")
        else:
            await message.reply_text("An error occurred while fetching series details.")

# --- Centralized Callback Handler ---

@Client.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    data = query.data
    clicked_user = query.from_user.id
    chat_id = query.message.chat.id
    message_id = query.message.id

    # Determine who initiated the request for group chats
    reply_msg = query.message.reply_to_message  
    requested_user = requestor.get(f"{chat_id}•{message_id}")
    if not requested_user and reply_msg and reply_msg.from_user:
        requested_user = reply_msg.from_user.id
    elif not requested_user: # Fallback for direct messages or if requestor dict is empty
        requested_user = clicked_user

    # Prevent other users from interacting with a specific user's request in groups
    if chat_id < 0 and requested_user and clicked_user != requested_user:
        await query.answer("Not your request!", show_alert=True)
        return

    # --- General Purpose Callbacks ---
    if data == "close_data":
        await query.message.delete()
        await query.answer("Closed.")
    elif data == "gfiltersdeleteallconfirm":
        await del_allg(query.message, 'gfilters')
        await query.answer("Dᴏɴᴇ !")
    elif data == "gfiltersdeleteallcancel":
        try:
            await query.message.reply_to_message.delete()
        except:
            pass
        await query.message.delete()
        await query.answer("Pʀᴏᴄᴇss Cᴀɴᴄᴇʟʟᴇᴅ !")

    # --- Global Filter Alert Callbacks ---
    elif data.startswith("gfilteralert:"):
        await handle_gfilter_alert(query)
    elif data.startswith("alertmessage:"): # Assuming this is for local filters, not global
        await query.answer("This alert is not configured.", show_alert=True)

    # --- File Sending Callbacks ---
    elif data.startswith("b:"): # Deep link for files
        await handle_file_request(client, query, data.split(":")[1], is_deep_link=True)
    elif data.startswith("file"): # Direct file request from inline/search results
        ident, file_id = data.split("#")
        await handle_file_request(client, query, file_id, ident=ident)

    # --- Series Management UI Callbacks (User Facing) ---
    elif data.startswith("user_series_select:"):
        series_key = data.split(":")[1]
        await handle_user_series_selection(client, query, series_key)
    elif data.startswith("user_lang:"):
        _, series_key, language_name = data.split(":")
        await handle_user_language_selection(client, query, series_key, language_name)
    elif data.startswith("user_season:"):
        _, series_key, language_name, season_name = data.split(":")
        await handle_user_season_selection(client, query, series_key, language_name, season_name)

    # Admin UI Callbacks are handled by plugins/crazy.py's own decorators.

# --- Specialized Callback Handlers ---

async def handle_gfilter_alert(query: CallbackQuery):
    parts = query.data.split(":")
    i = parts[1]
    keyword = parts[2]
    reply_text, btn, alerts, fileid = await find_gfilter('gfilters', keyword)
    if alerts is not None:
        # alerts are stored as a string representation of a list, so eval it
        alerts = eval(alerts) 
        alert = alerts[int(i)]
        alert = alert.replace("\\n", "\n").replace("\\t", "\t")
        await query.answer(alert, show_alert=True)
    else:
        await query.answer("No alert message found.", show_alert=True)

async def handle_file_request(client: Client, query: CallbackQuery, file_identifier: str, ident: str = None, is_deep_link: bool = False):
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    
    # Check force subscribe channels (REQ_CHANNEL_ONE, REQ_CHANNEL_TWO)
    force_sub_buttons = await create_request_forcesub_buttons(user_id)
    if force_sub_buttons:
        await query.answer("Please join channels below to get files!", show_alert=True)
        await client.send_message(
            chat_id=user_id,
            text="<b>Please join channels below to use bot</b>",
            reply_markup=InlineKeyboardMarkup(force_sub_buttons),
            parse_mode=enums.ParseMode.HTML
        )
        return

    # Check AUTH_CHANNEL (if configured)
    if AUTH_CHANNEL and not await is_subscribed(client, userid=user_id):
        try:
            invite_link = await client.create_chat_invite_link(int(AUTH_CHANNEL))
            btn = [[InlineKeyboardButton("❆ Jᴏɪɴ Oᴜʀ Bᴀᴄᴋ-Uᴘ Cʜᴀɴɴᴇʟ ❆", url=invite_link.invite_link)]]
            await query.answer("Please join the backup channel!", show_alert=True)
            await client.send_message(
                chat_id=user_id,
                text="♦️ <b><u>READ THIS INSTRUCTION</u></b> ♦️\n\n🗣 <i>Follow instructions to access movies</i>",
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode=enums.ParseMode.MARKDOWN
            )
            return
        except Exception as e:
            logger.error(f"Error checking AUTH_CHANNEL or creating invite link: {e}")
            await query.answer("An error occurred with channel verification. Please try again later.", show_alert=True)
            return

    # If all checks pass, proceed to send file
    if is_deep_link:
        # This is a deep link from a 'b:' callback, which means it's a link_key from crazy_db
        # The link_key format is "get_{raw_channel_id}.{start_msg_id}.{end_msg_id}"
        parts = file_identifier.split(".") # Split by dot now
        if len(parts) == 4 and parts[0] == "get": # Ensure it starts with "get" and has 4 parts
            raw_channel_id = parts[1]
            start_msg_id = int(parts[2])
            end_msg_id = int(parts[3])
            
            # Convert raw_channel_id back to Pyrogram format
            channel_id_pyrogram = int(f"-100{raw_channel_id}")
            
            # Fetch messages from the DB channel
            copied_messages = []
            current_msg_id = start_msg_id
            while current_msg_id <= end_msg_id:
                try:
                    msg = await client.get_messages(chat_id=channel_id_pyrogram, message_ids=current_msg_id)
                    if msg:
                        copied_msg = await msg.copy(chat_id=user_id)
                        copied_messages.append(copied_msg)
                        await asyncio.sleep(0.5) # Small delay
                except Exception as e:
                    logger.error(f"Error copying message {current_msg_id} from {channel_id_pyrogram}: {e}")
                current_msg_id += 1
            
            if copied_messages:
                delete_data = await client.send_message(
                    chat_id=user_id,
                    text=AUTO_DELETE_MSG.format(time=AUTO_DELETE_TIME)
                )
                asyncio.create_task(delete_file(copied_messages, client, delete_data))
                await query.answer('Files sent to your PM!', show_alert=True)
            else:
                await query.answer('Failed to retrieve files. They might have been deleted or are inaccessible.', show_alert=True)
        else:
            await query.answer('Invalid file link.', show_alert=True)
    else:
        # This is a direct file_id from inline query results (not from crazy_db)
        # This part assumes a get_file_details function exists elsewhere (e.g., in utils or another plugin)
        # For now, I'll keep the placeholder logic.
        # files_ = await get_file_details(file_identifier) # This function is not in provided code
        # if not files_:
        #     await query.answer('No such file exists.', show_alert=True)
        #     return
        
        # file_data = files_[0]
        # title = file_data.file_name
        # size = get_size(file_data.file_size)
        # f_caption = file_data.caption
        
        # For now, if not a deep link, assume it's an invalid file_identifier or needs a different lookup
        await query.answer("Direct file sending not fully implemented for this type of file_identifier.", show_alert=True)
        return

        # settings = await get_settings(chat_id) # Get chat settings
        
        # if settings['botpm']: # If botpm is enabled, send to PM
        #     try:
        #         sent_msg = await client.send_cached_media(
        #             chat_id=user_id,
        #             file_id=file_data.file_id,
        #             caption=f_caption,
        #             protect_content=True if ident == "filep" else False,
        #             reply_markup=InlineKeyboardMarkup(
        #                 [
        #                     [
        #                         InlineKeyboardButton('Sᴜᴘᴘᴏʀᴛ Gʀᴏᴜᴘ', url=SUPPORT_GROUP_LINK),
        #                         InlineKeyboardButton('Uᴘᴅᴀᴛᴇs Cʜᴀɴɴᴇʟ', url=UPDATES_CHANNEL_LINK)
        #                     ],
        #                     [
        #                         InlineKeyboardButton("Bᴏᴛ Oᴡɴᴇʀ", url=BOT_OWNER_LINK)
        #                     ]
        #                 ]
        #             )
        #         )
        #         await query.answer('Check PM, I have sent files in PM', show_alert=True)
        #     except pyrogram.errors.UserIsBlocked:
        #         await query.answer('Unblock the bot first!', show_alert=True)
        #     except pyrogram.errors.PeerIdInvalid:
        #         await query.answer(url=f"https://t.me/{BOT_USERNAME}?start=file_{file_identifier}") # Fallback to deep link if PM fails
        #     except Exception as e:
        #         logger.error(f"Error sending cached media to PM: {e}")
        #         await query.answer(url=f"https://t.me/{BOT_USERNAME}?start=file_{file_identifier}") # Fallback to deep link
        # else: # If botpm is disabled, send in group (if allowed)
        #     await query.answer("Bot PM is disabled. Files can only be sent in PM.", show_alert=True)


async def handle_user_series_selection(client: Client, query: CallbackQuery, series_key: str):
    series_data = get_series_by_key(series_key)
    if series_data and series_data.get('published', False):
        await send_series_details_to_user(client, query.message, series_data, edit_message=query.message)
    else:
        await query.message.edit_text(
            "Series not found or not published.",
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML
        )
    await query.answer() # Answer the callback query

async def handle_user_language_selection(client: Client, query: CallbackQuery, series_key: str, language_name: str):
    series_data = get_series_by_key(series_key)

    if series_data and series_data.get('published', False):
        current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
        seasons = current_lang.get("seasons", []) if current_lang else []
        seasons = [s for s in seasons if s.get('qualities')] # Filter out seasons with no qualities

        if not seasons:
            await query.answer("No seasons available for this language yet.", show_alert=True)
            return

        reply_text = (
            f"○ <b>Title:</b> <code>{series_data['title']}</code>\n"
            f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>\n"
            f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>\n"
            f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>\n"
            f"○ <b>Language:</b> <code>{language_name.title()}</code>\n\n"
            "Select the season you need...!"
        )
        
        poster_to_use = get_specific_poster(series_data['_id'], language_name=language_name) or NO_POSTER_FOUND_IMG
        
        buttons = []
        for season in seasons:
            buttons.append(InlineKeyboardButton(season['name'], callback_data=f"user_season:{series_key}:{language_name}:{season['name']}"))
        
        buttons_chunked = chunk_buttons(buttons)
        buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"user_series_select:{series_key}")]) # Back to series selection
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
        try:
            await query.message.edit_media(
                media=InputMediaPhoto(media=poster_to_use, caption=reply_text, parse_mode=enums.ParseMode.HTML),
                reply_markup=reply_markup
            )
        except pyrogram.errors.MediaEmpty:
            logger.error(f"MediaEmpty error for poster: {poster_to_use} during edit. Falling back to NO_POSTER_FOUND_IMG.")
            await query.message.edit_media(
                media=InputMediaPhoto(
                    media=NO_POSTER_FOUND_IMG,
                    caption=reply_text,
                    parse_mode=enums.ParseMode.HTML
                ),
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error editing message media for language details: {e}")
            await query.message.edit_text("An error occurred while fetching language details.")
    else:
        await query.message.edit_text(
            "Series not found or not published.",
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML
        )
    await query.answer() # Answer the callback query

async def handle_user_season_selection(client: Client, query: CallbackQuery, series_key: str, language_name: str, season_name: str):
    series_data = get_series_by_key(series_key)

    if series_data and series_data.get('published', False):
        current_lang = next((lang for lang in series_data.get("languages", []) if lang["name"].lower() == language_name.lower()), None)
        current_season = next((s for s in current_lang.get("seasons", []) if s["name"].lower() == season_name.lower()), None) if current_lang else None
        qualities = current_season.get("qualities", []) if current_season else []
        qualities = [q for q in qualities if q.get('link_key')] # Filter out qualities with no links

        if not qualities:
            await query.answer("No qualities available for this season yet.", show_alert=True)
            return

        reply_text = (
            f"○ <b>Title:</b> <code>{series_data['title']}</code>\n"
            f"○ <b>Released On:</b> <code>{series_data.get('released_on', 'N/A')}</code>\n"
            f"○ <b>Genre:</b> <code>{series_data.get('genre', 'N/A')}</code>\n"
            f"○ <b>Rating:</b> <code>{series_data.get('rating', 'N/A')}</code>\n"
            f"○ <b>Language:</b> <code>{language_name.title()}</code>\n"
            f"○ <b>Season:</b> <code>{season_name.title()}</code>\n\n"
            "Select the quality you need...!"
        )
        
        poster_to_use = get_specific_poster(series_key, language_name=language_name, season_name=season_name) or NO_POSTER_FOUND_IMG
        
        buttons = []
        for quality in qualities:
            buttons.append(InlineKeyboardButton(quality['name'], callback_data=f"b:{quality['link_key']}"))
        
        buttons_chunked = chunk_buttons(buttons, chunk_size=2)
        buttons_chunked.append([InlineKeyboardButton("Back", callback_data=f"user_lang:{series_key}:{language_name}")]) # Back to season selection
        reply_markup = InlineKeyboardMarkup(buttons_chunked)
        
        try:
            await query.message.edit_media(
                media=InputMediaPhoto(media=poster_to_use, caption=reply_text, parse_mode=enums.ParseMode.HTML),
                reply_markup=reply_markup
            )
        except pyrogram.errors.MediaEmpty:
            logger.error(f"MediaEmpty error for poster: {poster_to_use} during edit. Falling back to NO_POSTER_FOUND_IMG.")
            await query.message.edit_media(
                media=InputMediaPhoto(
                    media=NO_POSTER_FOUND_IMG,
                    caption=reply_text,
                    parse_mode=enums.ParseMode.HTML
                ),
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error editing message media for season details: {e}")
            await query.message.edit_text("An error occurred while fetching season details.")
    else:
        await query.message.edit_text(
            "Series not found or not published.",
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML
        )
    await query.answer() # Answer the callback query
