# database/gfilters_db.py

import logging
from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_URI, DATABASE_NAME
from pyrogram import enums
from database.postgres import pgDb

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

mongo = AsyncIOMotorClient(DATABASE_URI)
mydb = mongo[DATABASE_NAME]


async def add_gfilter(gfilters, text, reply_text, btn, file, alert):
    group_id = int(gfilters)
    mycol = mydb[str(gfilters)]

    data = {
        "text": str(text),
        "reply": str(reply_text),
        "btn": str(btn),
        "file": str(file),
        "alert": str(alert),
    }

    try:
        # Mongo first
        await mycol.update_one({"text": str(text)}, {"$set": data}, upsert=True)
        # then PG mirror
        await pgDb.upsert_gfilter(group_id, str(text), str(reply_text), str(btn), str(file), str(alert))
    except Exception:
        logger.exception("Some error occured!", exc_info=True)


async def find_gfilter(gfilters, name):
    group_id = int(gfilters)
    # PG first
    reply_text, btn, alert, fileid = await pgDb.find_gfilter(group_id, name)
    if reply_text is not None or btn is not None or fileid is not None:
        return reply_text, btn, alert, fileid

    # fallback mongo
    mycol = mydb[str(gfilters)]
    doc = await mycol.find_one({"text": name})
    if not doc:
        return None, None, None, None

    # self-heal to PG
    await pgDb.upsert_gfilter(group_id, doc.get("text", ""), doc.get("reply", ""), doc.get("btn", ""), doc.get("file", ""), doc.get("alert", ""))
    return doc.get("reply"), doc.get("btn"), doc.get("alert"), doc.get("file")


async def get_gfilters(gfilters):
    group_id = int(gfilters)
    # PG first (cached)
    texts = await pgDb.get_gfilters(group_id)
    if texts:
        return texts

    # fallback mongo + self-heal
    mycol = mydb[str(gfilters)]
    texts = []
    async for doc in mycol.find({}):
        texts.append(doc.get("text"))
        await pgDb.upsert_gfilter(group_id, doc.get("text", ""), doc.get("reply", ""), doc.get("btn", ""), doc.get("file", ""), doc.get("alert", ""))
    return texts


async def delete_gfilter(message, text, gfilters):
    group_id = int(gfilters)
    mycol = mydb[str(gfilters)]
    myquery = {"text": text}

    count = await mycol.count_documents(myquery)
    if count == 1:
        # Mongo first
        await mycol.delete_one(myquery)
        # then PG
        await pgDb.delete_gfilter(group_id, text)

        await message.reply_text(
            f"'`{text}`'  deleted. I'll not respond to that gfilter anymore.",
            quote=True,
            parse_mode=enums.ParseMode.MARKDOWN
        )
    else:
        await message.reply_text("Couldn't find that gfilter!", quote=True)


async def del_allg(message, gfilters):
    group_id = int(gfilters)
    mycol = mydb[str(gfilters)]
    try:
        # Mongo first
        await mycol.drop()
        # then PG
        await pgDb.delete_all_gfilters(group_id)
        await message.edit_text("All gfilters has been removed !")
    except Exception:
        await message.edit_text("Couldn't remove all gfilters !")


async def count_gfilters(gfilters):
    group_id = int(gfilters)
    # PG first
    c = await pgDb.count_gfilters(group_id)
    return False if c == 0 else c


async def gfilter_stats():
    return await pgDb.gfilter_stats()
