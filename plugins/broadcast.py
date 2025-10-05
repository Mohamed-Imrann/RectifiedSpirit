#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from bot import Bot
from pyrogram import Client, filters, enums
import datetime, time, os, asyncio, logging 
from pyrogram.errors import InputUserDeactivated, UserNotParticipant, FloodWait, UserIsBlocked, PeerIdInvalid
from pyrogram.errors.exceptions.bad_request_400 import MessageTooLong, PeerIdInvalid
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram import filters, enums
from database.users_chats_db import db
from info import ADMINS
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, 
    InputMediaPhoto
)
# Global dictionary to store original announcement messages
announcement_messages = {}

# Infrastructure Update Message Function
async def send_infrastructure_update_message(client: Bot, user_id: int, username: str):
    """Send infrastructure update message to a user"""
    message_text = f"""
🌟 **EXCITING BOT UPGRADE!** 🌟

✨ Our bot infrastructure has been completely transformed to bring you a seamless experience like never before! ✨

🚀 **What's New?**
• Lightning-fast response times
• Sleek, intuitive interface
• Enhanced stability and performance
• Revolutionary new features
• Smoother navigation throughout

👨‍💻 **All credit goes to Me @{username}** Because i've Made it fully from Scratch for this incredible transformation! 
Your dedication and expertise have taken our bot to the next level! 🙏

💼 **BOT CODE RESTOCKED!**
Our premium bot is now back in stock and available for purchase!

🔥 **Special Offer:** Get 20% off with code "UPGRADE20" for the next 48 hours only!

Thank you for being part of our journey. We're excited for you to experience the future of bot technology! 🚀
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛒 Purchase Bot Codes", url="https://t.me/SflixBots"),
            InlineKeyboardButton("🔮 View New Features", callback_data="view_features")
        ],
        [
            InlineKeyboardButton("💬 Support Chat", url="https://t.me/AbhishekIssac"),
            InlineKeyboardButton("📢 Updates Channel", url="https://t.me/SflixBots")
        ],
        [
            InlineKeyboardButton("🎁 Claim Discount", callback_data="claim_discount")
        ]
    ])
    
    try:
        image_url = "https://files.catbox.moe/jfmwpz.jpg"  # Replace with your own image URL
        sent_message = await client.send_photo(
            chat_id=user_id,
            photo=image_url,
            caption=message_text,
            reply_markup=keyboard,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        
        # Store the original message content for later restoration
        announcement_messages[sent_message.id] = {
            'photo_id': sent_message.photo.file_id,
            'caption': message_text,
            'reply_markup': keyboard,
            'username': username
        }
        
        logger.info(f"Sent infrastructure update message to user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error sending infrastructure update message to user {user_id}: {e}")
        return False

# Callback Handler for Infrastructure Update Buttons
@Bot.on_callback_query(filters.regex("view_features|claim_discount|back_to_announcement"))
async def handle_infrastructure_callbacks(client: Bot, callback_query: CallbackQuery):
    """Handle callbacks from the infrastructure update message"""
    data = callback_query.data
    message_id = callback_query.message.id
    
    if data == "view_features":
        features_text = """
🔥 **NEW FEATURES HIGHLIGHTS** 🔥

🚀 **Performance Boost**
• 300% faster response times
• Optimized database queries
• Reduced memory usage

✨ **UI/UX Improvements**
• Completely redesigned interface
• Intuitive navigation system
• Enhanced visual feedback

🔒 **Security Enhancements**
• Advanced encryption protocols
• Improved user authentication
• Secure data transmission

🛠️ **New Tools**
• Advanced search functionality
• Customizable user preferences
• Enhanced media management

🎯 **Smart Features**
• AI-powered recommendations
• Contextual help system
• Automated workflows

Experience the future of bot technology today!
        """
        
        try:
            await callback_query.message.edit_text(
                features_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_announcement")]
                ]),
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error showing features: {e}")
    
    elif data == "claim_discount":
        discount_text = """
🎉 **DISCOUNT UNLOCKED!** 🎉

Congratulations! You've unlocked a special 20% discount on all bot codes!

Use code: **UPGRADE20**

This offer is valid for the next 48 hours only. Don't miss out!

🛒 [Purchase Now](https://t.me/AbhishekSflix)

Thank you for being a valued user! 🙏
        """
        
        try:
            await callback_query.message.edit_text(
                discount_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_announcement")]
                ]),
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error showing discount: {e}")
    
    elif data == "back_to_announcement":
        try:
            await callback_query.answer("Returning to announcement...")
            
            # Check if we have the original message stored
            if message_id in announcement_messages:
                original = announcement_messages[message_id]
                
                # Restore the original message
                await callback_query.message.edit_media(
                    media=InputMediaPhoto(
                        media=original['photo_id'],
                        caption=original['caption'],
                        parse_mode=enums.ParseMode.MARKDOWN
                    ),
                    reply_markup=original['reply_markup']
                )
            else:
                # If we don't have the original message stored, create a new one
                username = "AbhishekSflix"  # Default username if not available
                await send_infrastructure_update_message(client, callback_query.from_user.id, username)
                
        except Exception as e:
            logger.error(f"Error returning to announcement: {e}")
            # Fallback: send a new message if restoration fails
            try:
                await callback_query.message.reply_text("Sorry, we couldn't restore the original message. Please check our updates channel for the latest information.")
            except:
                pass

# New Command: Infrastructure Update Broadcast
@Bot.on_message(filters.command(["infra_update", "iu"]) & filters.user(ADMINS))
async def infra_update_broadcast(bot, message):
    """Send infrastructure update message to all users"""
    if len(message.command) < 2:
        await message.reply("Usage: `/infra_update <username>`")
        return
    
    username = message.command[1]
    confirmation = await message.reply(
        f"Preparing to send infrastructure update message to all users. Credit will be given to @{username}.\n\n"
        "Reply with 'yes' to confirm or 'no' to cancel."
    )
    
    # Wait for confirmation
    response = await bot.listen(message.chat.id, timeout=30)
    if response.text.lower() != "yes":
        await confirmation.edit("Announcement cancelled.")
        return
    
    await confirmation.edit("Sending infrastructure update message to all users... This may take a while.")
    
    # Get all users from the database
    users = await db.get_all_users()
    start_time = time.time()
    total_users = await db.total_users_count()
    
    success = 0
    failed = 0
    blocked = 0
    deleted = 0
    
    async for user in users:
        user_id = int(user['id'])
        result = await send_infrastructure_update_message(bot, user_id, username)
        
        if result:
            success += 1
        else:
            # Try to determine the reason for failure
            try:
                # Check if user is blocked
                await bot.send_message(user_id, "Test")
                failed += 1
            except UserIsBlocked:
                blocked += 1
                await db.delete_user(user_id)
            except InputUserDeactivated:
                deleted += 1
                await db.delete_user(user_id)
            except Exception:
                failed += 1
        
        # Update progress every 100 users
        if (success + failed + blocked + deleted) % 100 == 0:
            elapsed_time = datetime.timedelta(seconds=int(time.time() - start_time))
            await confirmation.edit(
                f"𝖨𝗇 𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌: {success + failed + blocked + deleted} / {total_users}\n"
                f"𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {success}\n"
                f"𝖡𝗅𝗈𝖼𝗄𝖾𝖽: {blocked}\n"
                f"𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {deleted}\n"
                f"𝖥𝖺𝗂𝗅𝖾𝖽: {failed}\n"
                f"𝖤𝗅𝖺𝗉𝗌𝖾𝖽 𝖳𝗂𝗆𝖾: {elapsed_time}"
            )
        
        # Small delay to avoid flooding
        await asyncio.sleep(0.1)
    
    time_taken = datetime.timedelta(seconds=int(time.time()-start_time))
    await confirmation.edit(
        f"𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌 𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽:\n"
        f"𝖳𝗈𝗍𝖺𝗅: {total_users}\n"
        f"𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {success}\n"
        f"𝖡𝗅𝗈𝖼𝗄𝖾𝖽: {blocked}\n"
        f"𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {deleted}\n"
        f"𝖥𝖺𝗂𝗅𝖾𝖽: {failed}\n"
        f"𝖤𝗅𝖺𝗉𝗌𝖾𝖽 𝖳𝗂𝗆𝖾: {time_taken}"
    )

# Existing Broadcast Commands
@Bot.on_message(filters.command(["bb", "broadcast"]) & filters.user(ADMINS) & filters.reply)
async def speed_verupikkals(bot, message):
    if len(message.command) == 1:
        matrix = 0  # No matrix value provided, skip no users
    else:
        try:
            matrix = int(message.text.split(None, 1)[1])  # Extract matrix value
        except ValueError:
            await message.reply("Invalid matrix value. Please enter a valid number.")
            return  # Exit function if matrix value is invalid
    start_time = time.time()
    b_msg = message.reply_to_message
    sts = await message.reply("🚀")
    users = await db.get_all_users()
    users_list = await users.to_list(None)  
    total_users = len(users_list)    
    users = await db.get_all_users() 
    # Skip specified number of users
    skipped_count = 0
    success = 0
    failed = 0
    async for user in users:  # Iterate directly over cursor
        if skipped_count < matrix:
            skipped_count += 1             
        else:# Skip users until reaching the desired matrix value
            try:
                await b_msg.copy(chat_id=int(user['id']))
                success += 1
            except FloodWait as e:
                await asyncio.sleep(e.x)
                await b_msg.copy(chat_id=int(user['id']))
            except InputUserDeactivated:
                await db.delete_user(int(user['id']))
                failed += 1
            except UserIsBlocked:
                await db.delete_user(int(user['id']))
                failed += 1
            except Exception as e:                
                failed += 1

        process = success + failed

        if process % 500 == 1:
            elapsed_time = datetime.timedelta(seconds=int(time.time() - start_time))
            await sts.edit(f"𝖨𝗇 𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌: {process+matrix} / {total_users}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {success}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {failed}\n𝖤𝗅𝖺𝗉𝗌𝖾𝖽 𝖳𝗂𝗆𝖾: {elapsed_time}")

    # No need for separate start_time variable as loop starts here
    time_taken = datetime.timedelta(seconds=int(time.time()-start_time))
    await sts.edit(f"𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌 𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽:\n𝖳𝗈𝗍𝖺𝗅: {total_users}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {success}\n𝖲𝗄𝗂𝗉𝗉𝖾𝖽: {skipped_count}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {failed}\n𝖤𝗅𝖺𝗉𝗌𝖾𝖽 𝖳𝗂𝗆𝖾: {time_taken}")

@Bot.on_message(filters.command(["cb", "clean_broadcast"]) & filters.user(ADMINS))
async def remove_junkuser__db(bot, message):
    users = await db.get_all_users()
    b_msg = message 
    sts = await message.reply_text(text='🚀') 
    start_time = time.time()
    total_users = await db.total_users_count()
    blocked = 0
    deleted = 0
    failed = 0
    done = 0
    async for user in users:
        pti, sh = await clear_junk(int(user['id']), b_msg)
        if pti == False:
            if sh == "Blocked":
                blocked+=1
            elif sh == "Deleted":
                deleted += 1
            elif sh == "Error":
                failed += 1
        done += 1
        if not done % 20:
            await sts.edit(f"𝖨𝗇 𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌.\n𝖳𝗈𝗍𝖺𝗅 𝖴𝗌𝖾𝗋𝗌: {total_users}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {done} / {total_users}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {blocked}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {deleted}")    
    time_taken = datetime.timedelta(seconds=int(time.time()-start_time))
    await sts.delete()
    await bot.send_message(message.chat.id, f"𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌 𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽.\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽 𝖨𝗇: {time_taken} 𝖲𝖾𝖼𝗈𝗇𝖽𝗌.\n𝖳𝗈𝗍𝖺𝗅 𝖴𝗌𝖾𝗋𝗌 {total_users}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {done} / {total_users}\n𝖡𝗅𝗈𝖼𝗄𝖾𝖽: {blocked}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {deleted}")

@Bot.on_message(filters.command(["gg", "group_broadcast"]) & filters.user(ADMINS) & filters.reply)
async def broadcast_group(bot, message):
    groups = await db.get_all_chats()
    b_msg = message.reply_to_message
    sts = await message.reply_text(text='🚀')
    start_time = time.time()
    total_groups = await db.total_chat_count()
    done = 0
    failed = ""
    success = 0
    deleted = 0
    async for group in groups:
        pti, sh, ex = await broadcast_messages_group(int(group['id']), b_msg)
        if pti == True:
            if sh == "Succes":
                success += 1
        elif pti == False:
            if sh == "deleted":
                deleted+=1 
                failed += ex 
                try:
                    await bot.leave_chat(int(group['id']))
                except Exception as e:
                    print(f"{e} > {group['id']}")  
        done += 1
        if not done % 20:
            await sts.edit(f"𝖨𝗇 𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌.\n𝖳𝗈𝗍𝖺𝗅 𝖦𝗋𝗈𝗎𝗉𝗌: {total_groups}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {done} / {total_groups}\n𝖲𝗎𝖼𝖼𝖾𝗌𝗌: {success}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {deleted}")    
    time_taken = datetime.timedelta(seconds=int(time.time()-start_time))
    await sts.delete()
    try:
        await message.reply_text(f"𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌 𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽.\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽 𝖨𝗇: {time_taken} 𝖲𝖾𝖼𝗈𝗇𝖽𝗌.\n𝖳𝗈𝗍𝖺𝗅 𝖦𝗋𝗈𝗎𝗉𝗌: {total_groups}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {done} / {total_groups}\n𝖲𝗎𝖼𝖼𝖾𝗌𝗌: {success}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {deleted}\n\n𝖱𝖾𝖺𝗌𝗈𝗇:- {failed}")
    except MessageTooLong:
        with open('reason.txt', 'w+') as outfile:
            outfile.write(failed)
        await message.reply_document('reason.txt', caption=f"𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌 𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽.\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽 𝖨𝗇: {time_taken} 𝖲𝖾𝖼𝗈𝗇𝖽𝗌.\n𝖳𝗈𝗍𝖺𝗅 𝖦𝗋𝗈𝗎𝗉𝗌: {total_groups}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {done} / {total_groups}\n𝖲𝗎𝖼𝖼𝖾𝗌𝗌: {success}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {deleted}")
        os.remove("reason.txt")
    
@Bot.on_message(filters.command(["cg", "clean_gbroadcast"]) & filters.user(ADMINS))
async def junk_clear_group(bot, message):
    groups = await db.get_all_chats()
    b_msg = message
    sts = await message.reply_text(text='🚀')
    start_time = time.time()
    total_groups = await db.total_chat_count()
    done = 0
    failed = ""
    deleted = 0
    async for group in groups:
        pti, sh, ex = await junk_group(int(group['id']), b_msg)        
        if pti == False:
            if sh == "deleted":
                deleted+=1 
                failed += ex 
                try:
                    await bot.leave_chat(int(group['id']))
                except Exception as e:
                    print(f"{e} > {group['id']}")  
        done += 1
        if not done % 20:
            await sts.edit(f"𝖨𝗇 𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌.\n𝖳𝗈𝗍𝖺𝗅 𝖦𝗋𝗈𝗎𝗉𝗌: {total_groups}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {done} / {total_groups}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {deleted}")    
    time_taken = datetime.timedelta(seconds=int(time.time()-start_time))
    await sts.delete()
    try:
        await bot.send_message(message.chat.id, f"𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌 𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽.\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽 𝖨𝗇: {time_taken} 𝖲𝖾𝖼𝗈𝗇𝖽𝗌.\n𝖳𝗈𝗍𝖺𝗅 𝖦𝗋𝗈𝗎𝗉𝗌: {total_groups}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {done} / {total_groups}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {deleted}\n\n𝖱𝖾𝖺𝗌𝗈𝗇:- {failed}")
    except MessageTooLong:
        with open('junk.txt', 'w+') as outfile:
            outfile.write(failed)
        await message.reply_document('junk.txt', caption=f"𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌 𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽.\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽 𝖨𝗇 {time_taken} 𝖲𝖾𝖼𝗈𝗇𝖽𝗌.\n𝖳𝗈𝗍𝖺𝗅 𝖦𝗋𝗈𝗎𝗉𝗌 {total_groups}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {done} / {total_groups}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {deleted}")
        os.remove("junk.txt")

# Helper Functions
async def broadcast_messages_group(chat_id, message):
    try:
        await message.copy(chat_id=chat_id)
        return True, "Succes", 'mm'
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await broadcast_messages_group(chat_id, message)
    except Exception as e:
        await db.delete_chat(int(chat_id))       
        logging.info(f"{chat_id} - PeerIdInvalid")
        return False, "deleted", f'{e}\n\n'
    
async def junk_group(chat_id, message):
    try:
        kk = await message.copy(chat_id=chat_id)
        await kk.delete(True)
        return True, "Succes", 'mm'
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await junk_group(chat_id, message)
    except Exception as e:
        await db.delete_chat(int(chat_id))       
        logging.info(f"{chat_id} - PeerIdInvalid")
        return False, "deleted", f'{e}\n\n'
    
async def clear_junk(user_id, message):
    try:
        key = await message.copy(chat_id=user_id)
        await key.delete(True)
        return True, "Success"
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await clear_junk(user_id, message)
    except InputUserDeactivated:
        await db.delete_user(int(user_id))
        logging.info(f"{user_id}-Removed from Database, since deleted account.")
        return False, "Deleted"
    except UserIsBlocked:
        logging.info(f"{user_id} -Blocked the bot.")
        return False, "Blocked"
    except PeerIdInvalid:
        await db.delete_user(int(user_id))
        logging.info(f"{user_id} - PeerIdInvalid")
        return False, "Error"
    except Exception as e:
        return False, "Error"

async def broadcast_messages(user_id, message):
    try:
        await message.copy(chat_id=user_id)
        return True, "Success"
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await broadcast_messages(user_id, message)
    except InputUserDeactivated:
        await db.delete_user(int(user_id))
        logging.info(f"{user_id}-Removed from Database, since deleted account.")
        return False, "Deleted"
    except UserIsBlocked:
        logging.info(f"{user_id} -Blocked the bot.")
        return False, "Blocked"
    except PeerIdInvalid:
        await db.delete_user(int(user_id))
        logging.info(f"{user_id} - PeerIdInvalid")
        return False, "Error"
    except Exception as e:
        return False, "Error"
