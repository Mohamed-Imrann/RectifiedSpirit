import datetime, time, os, asyncio, logging 
from pyrogram.errors import InputUserDeactivated, UserNotParticipant, FloodWait, UserIsBlocked, PeerIdInvalid
from pyrogram.errors.exceptions.bad_request_400 import MessageTooLong, PeerIdInvalid
from pyrogram.types import Message, InlineKeyboardButton
from pyrogram import Client, filters, enums
from database.users_chats_db import db
from info import ADMINS
        
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@Client.on_message(filters.command(["bb", "broadcast"]) & filters.user(ADMINS) & filters.reply)
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
            await sts.edit(f"𝖨𝗇 𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌𝗌: {process+matrix} / {total_users}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {success}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {failed}\n𝖤𝗅𝖺𝗉𝗌𝖾𝖽 𝖳𝗂𝗆𝖾: {elapsed_time}")

    # No need for separate start_time variable as loop starts here
    time_taken = datetime.timedelta(seconds=int(time.time()-start_time))
    await sts.edit(f"𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌 𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽:\n𝖳𝗈𝗍𝖺𝗅: {total_users}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {success}\n𝖲𝗄𝗂𝗉𝗉𝖾𝖽: {skipped_count}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {failed}\n𝖤𝗅𝖺𝗉𝗌𝖾𝖽 𝖳𝗂𝗆𝖾: {time_taken}")

@Client.on_message(filters.command(["cb", "clean_broadcast"]) & filters.user(ADMINS))
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

@Client.on_message(filters.command(["gg", "group_broadcast"]) & filters.user(ADMINS) & filters.reply)
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
    
@Client.on_message(filters.command(["cg", "clean_gbroadcast"]) & filters.user(ADMINS))
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
        await bot.send_message(message.chat.id, f"𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌 𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽.\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽 𝖨𝗇 {time_taken} 𝖲𝖾𝖼𝗈𝗇𝖽𝗌.\n𝖳𝗈𝗍𝖺𝗅 𝖦𝗋𝗈𝗎𝗉𝗌 {total_groups}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {done} / {total_groups}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {deleted}\n\n𝖱𝖾𝖺𝗌𝗈𝗇:- {failed}")
    except MessageTooLong:
        with open('junk.txt', 'w+') as outfile:
            outfile.write(failed)
        await message.reply_document('junk.txt', caption=f"𝖯𝗋𝗈𝗀𝗋𝖾𝗌𝗌 𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽.\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽 𝖨𝗇 {time_taken} 𝖲𝖾𝖼𝗈𝗇𝖽𝗌.\n𝖳𝗈𝗍𝖺𝗅 𝖦𝗋𝗈𝗎𝗉𝗌 {total_groups}\n𝖢𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝖽: {done} / {total_groups}\n𝖣𝖾𝗅𝖾𝗍𝖾𝖽: {deleted}")
        os.remove("junk.txt")

@Client.on_message(filters.command("broadcast") & filters.user(ADMINS))
async def broadcast_message(client: Client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("Reply to a message to broadcast it.")
        return

    all_users = await db.get_all_users()  # Fetch all user IDs from the database
    
    sent_count = 0
    failed_count = 0

    status_message = await message.reply_text("Starting broadcast...")

    async for user in all_users:
        try:
            await message.reply_to_message.copy(user['id'])
            sent_count += 1
        except FloodWait as e:
            await asyncio.sleep(e.x)
            await message.reply_to_message.copy(user['id'])
        except InputUserDeactivated:
            await db.delete_user(user['id'])
            logging.info(f"{user['id']}-Removed from Database, since deleted account.")
            failed_count += 1
        except UserIsBlocked:
            logging.info(f"{user['id']} -Blocked the bot.")
            failed_count += 1
        except PeerIdInvalid:
            await db.delete_user(user['id'])
            logging.info(f"{user['id']} - PeerIdInvalid")
            failed_count += 1
        except Exception as e:
            failed_count += 1
            print(f"Failed to send to {user['id']}: {e}")
        
        # Update status periodically
        if (sent_count + failed_count) % 100 == 0:
            try:
                await status_message.edit_text(f"Broadcasting... Sent: {sent_count}, Failed: {failed_count}")
            except Exception:
                pass # Ignore MessageNotModified errors
                
    await status_message.edit_text(f"Broadcast finished!\nSent to: {sent_count} users\nFailed for: {failed_count} users")

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
