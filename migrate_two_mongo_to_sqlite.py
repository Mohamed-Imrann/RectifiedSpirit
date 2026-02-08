import os
import asyncio
from pymongo import MongoClient

from database.series_sql import init_db, upsert_series, ensure_group, add_file

def pick(d, keys, default=""):
    for k in keys:
        if k in d and d[k] is not None and str(d[k]).strip() != "":
            return d[k]
    return default

def normalize_season(x: str) -> str:
    x = (x or "").strip()
    return x if x else "S01"

def normalize_quality(x: str) -> str:
    x = (x or "").strip()
    return x if x else "Unknown"

def normalize_lang(x: str) -> str:
    x = (x or "").strip()
    return x if x else "Unknown"

def iter_docs(uri: str, dbname: str, coll: str):
    mc = MongoClient(uri)
    col = mc[dbname][coll]
    for doc in col.find({}):
        yield doc

async def ingest_doc(d):
    # ---- Try best-effort field mapping (supports different old schemas) ----
    title   = str(pick(d, ["title", "name", "series", "movie"], "")).strip()
    lang    = normalize_lang(str(pick(d, ["lang", "language", "audio"], "Unknown")))
    season  = normalize_season(str(pick(d, ["season", "s"], "S01")))
    quality = normalize_quality(str(pick(d, ["quality", "q", "res"], "Unknown")))

    # file fields
    file_id  = str(pick(d, ["file_id", "fileId", "tg_file_id", "fileid"], "")).strip()
    caption  = str(pick(d, ["caption", "cap"], "")).strip()
    msg_type = str(pick(d, ["msg_type", "type", "media_type"], "document")).strip()

    # Some bots store files as a list under "files" key
    files_list = d.get("files")
    if not file_id and isinstance(files_list, list) and files_list:
        # insert each item
        if not title:
            title = str(pick(d, ["series_title", "title"], "")).strip()
        if not title:
            return 0

        sid = await upsert_series(title)
        gid = await ensure_group(sid, lang, season, quality)

        inserted = 0
        for item in files_list:
            fid = str(pick(item, ["file_id", "fileId", "tg_file_id", "fileid"], "")).strip()
            if not fid:
                continue
            cap = str(pick(item, ["caption", "cap"], caption)).strip()
            typ = str(pick(item, ["msg_type", "type", "media_type"], msg_type or "document")).strip()
            await add_file(gid, fid, caption=cap, msg_type=typ)
            inserted += 1
        return inserted

    # Normal single-file document
    if not title or not file_id:
        return 0

    sid = await upsert_series(title)
    gid = await ensure_group(sid, lang, season, quality)
    await add_file(gid, file_id, caption=caption, msg_type=msg_type)
    return 1

async def main():
    await init_db()

    uri1  = os.getenv("OLD_MONGO_URI_1", "").strip()
    db1   = os.getenv("OLD_MONGO_DB_1", "").strip()
    col1  = os.getenv("OLD_MONGO_COLL_1", "").strip()

    uri2  = os.getenv("OLD_MONGO_URI_2", "").strip()
    db2   = os.getenv("OLD_MONGO_DB_2", "").strip()
    col2  = os.getenv("OLD_MONGO_COLL_2", "").strip()

    sources = []
    if uri1 and db1 and col1:
        sources.append((uri1, db1, col1, "mongo1"))
    if uri2 and db2 and col2:
        sources.append((uri2, db2, col2, "mongo2"))

    if not sources:
        print("❌ Missing OLD_MONGO_* envs")
        return

    total = 0
    for uri, dbn, coll, tag in sources:
        count = 0
        skipped = 0
        print(f"▶ Reading {tag}: {dbn}.{coll}")
        for d in iter_docs(uri, dbn, coll):
            try:
                ins = await ingest_doc(d)
                if ins:
                    count += ins
                else:
                    skipped += 1
            except Exception:
                skipped += 1

            if (count + skipped) % 500 == 0:
                print(f"{tag}: inserted={count} skipped={skipped}")

        total += count
        print(f"✅ Done {tag}: inserted={count} skipped={skipped}")

    print(f"\nDONE ✅ Total inserted into SQLite: {total}")

if __name__ == "__main__":
    asyncio.run(main())
