import os
import asyncio
from pymongo import MongoClient

from database.series_sql import init_db, upsert_series, ensure_group, add_file

MONGO_URI  = os.getenv("MONGO_URI", "")
MONGO_DB   = os.getenv("MONGO_DB", "olddb")
MONGO_COLL = os.getenv("MONGO_COLL", "files")

def pick(d, keys, default=""):
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip() != "":
            return v
    return default

async def main():
    await init_db()

    mc = MongoClient(MONGO_URI)
    col = mc[MONGO_DB][MONGO_COLL]

    count = 0
    skipped = 0

    for d in col.find({}):
        title = str(pick(d, ["title", "name", "series", "movie"], "")).strip()
        lang = str(pick(d, ["lang", "language"], "Unknown")).strip()
        season = str(pick(d, ["season"], "S01")).strip()
        quality = str(pick(d, ["quality", "q"], "Unknown")).strip()

        file_id = str(pick(d, ["file_id", "fileId", "tg_file_id"], "")).strip()
        caption = str(pick(d, ["caption", "cap"], "")).strip()
        msg_type = str(pick(d, ["msg_type", "type", "media_type"], "document")).strip()

        if not title or not file_id:
            skipped += 1
            continue

        sid = await upsert_series(title)
        gid = await ensure_group(sid, lang, season, quality)
        await add_file(gid, file_id, caption=caption, msg_type=msg_type)

        count += 1
        if count % 500 == 0:
            print("Migrated:", count, "Skipped:", skipped)

    print("DONE ✅ Migrated:", count, "Skipped:", skipped)

if __name__ == "__main__":
    asyncio.run(main())
