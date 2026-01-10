# database/crazy_db.py

import os
import copy
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_URI
from database.postgres import pgDb

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

client = AsyncIOMotorClient(DATABASE_URI)

series_db = client["series_database"]
series_collection = series_db["series"]
admin_assignments_collection = series_db["admin_assignments"]

# stays in Mongo (as in your code)
episodes_collection = client["file_database"]["episodes"]


async def _load_series(series_key: str) -> Optional[Dict[str, Any]]:
    doc = await pgDb.get_series_doc(series_key)
    if doc:
        return doc
    # fallback to mongo + self-heal into PG
    doc = await series_collection.find_one({"_id": series_key})
    if doc:
        await pgDb.upsert_series_doc(series_key, doc)
    return doc


async def _save_series(series_key: str, doc: Dict[str, Any]) -> bool:
    # WRITE ORDER: Mongo first, then Postgres
    await series_collection.replace_one({"_id": series_key}, doc, upsert=True)
    await pgDb.upsert_series_doc(series_key, doc)
    return True


# ---------------- Series CRUD ----------------

async def add_series(series_data: dict):
    try:
        series_key = series_data["_id"]
        # Mongo first
        await series_collection.insert_one(series_data)
        # then PG
        await pgDb.upsert_series_doc(series_key, series_data)
        logger.info(f"Series '{series_data.get('title', 'N/A')}' added with key: {series_key}")
        return True
    except Exception as e:
        logger.error(f"Error adding series: {e}")
        return False


async def get_series() -> List[dict]:
    # PG first
    docs = await pgDb.get_all_series(limit=2000, offset=0)
    if docs:
        return docs
    # fallback
    docs = await series_collection.find({}).to_list(length=None)
    for d in docs:
        await pgDb.upsert_series_doc(d["_id"], d)
    return docs


async def get_series_by_key(series_key: str):
    return await _load_series(series_key)


async def get_series_name(series_key: str):
    return await get_series_by_key(series_key)


async def update_series_field(series_key: str, field: str, value):
    try:
        doc = await _load_series(series_key)
        if not doc:
            return False
        doc[field] = value
        return await _save_series(series_key, doc)
    except Exception as e:
        logger.error(f"Error updating series: {e}")
        return False


async def get_poster_file_id(series_key: str):
    doc = await _load_series(series_key)
    return doc.get("poster_file_id") if doc else None


async def update_poster_file_id(series_key: str, poster_file_id: str):
    return await update_series_field(series_key, "poster_file_id", poster_file_id)


async def get_poster_by_key(series_key: str):
    return await get_poster_file_id(series_key)


async def get_poster_manuel(series_key: str):
    return await get_poster_by_key(series_key)


# ---------------- Languages / Seasons / Qualities ----------------

async def add_or_update_language(series_key: str, language_name: str, poster_file_id: str = None):
    doc = await _load_series(series_key)
    if not doc:
        return False

    languages = doc.get("languages", [])
    found = False
    for lang in languages:
        if lang.get("name", "").lower() == language_name.lower():
            if poster_file_id:
                lang["poster_file_id"] = poster_file_id
            found = True
            break

    if not found:
        new_language = {"name": language_name, "seasons": [], "season_layout": []}
        if poster_file_id:
            new_language["poster_file_id"] = poster_file_id
        languages.append(new_language)

    doc["languages"] = languages
    return await _save_series(series_key, doc)


async def get_languages(series_key: str):
    doc = await _load_series(series_key)
    return doc.get("languages", []) if doc else []


async def delete_language(series_key: str, language_name: str):
    doc = await _load_series(series_key)
    if not doc:
        return False

    languages = doc.get("languages", [])
    target = None
    for lang in languages:
        if lang.get("name", "").lower() == language_name.lower():
            target = lang
            break
    if not target:
        return False

    # delete linked episodes (Mongo) for that language
    for season in target.get("seasons", []):
        for quality in season.get("qualities", []):
            lk = quality.get("link_key")
            if lk:
                await episodes_collection.delete_one({"file_link_key": lk})

    doc["languages"] = [l for l in languages if l.get("name", "").lower() != language_name.lower()]

    # keep your layout trimming logic
    language_layout = doc.get("language_layout", [])
    if len(language_layout) > len(doc["languages"]):
        doc["language_layout"] = language_layout[: len(doc["languages"])]

    return await _save_series(series_key, doc)


async def add_or_update_season(series_key: str, language_name: str, season_name: str, poster_file_id: str = None):
    doc = await _load_series(series_key)
    if not doc:
        return False

    for lang in doc.get("languages", []):
        if lang.get("name", "").lower() == language_name.lower():
            seasons = lang.get("seasons", [])
            for s in seasons:
                if s.get("name", "").lower() == season_name.lower():
                    if poster_file_id:
                        s["poster_file_id"] = poster_file_id
                    break
            else:
                new_season = {"name": season_name, "qualities": [], "quality_layout": []}
                if poster_file_id:
                    new_season["poster_file_id"] = poster_file_id
                seasons.append(new_season)
            lang["seasons"] = seasons
            return await _save_series(series_key, doc)

    return False


async def get_seasons(series_key: str, language_name: str):
    doc = await _load_series(series_key)
    if not doc:
        return []
    for lang in doc.get("languages", []):
        if lang.get("name", "").lower() == language_name.lower():
            return lang.get("seasons", [])
    return []


async def delete_season(series_key: str, language_name: str, season_name: str):
    doc = await _load_series(series_key)
    if not doc:
        return False

    for lang in doc.get("languages", []):
        if lang.get("name", "").lower() == language_name.lower():
            seasons = lang.get("seasons", [])
            target = None
            for s in seasons:
                if s.get("name", "").lower() == season_name.lower():
                    target = s
                    break
            if not target:
                return False

            for q in target.get("qualities", []):
                lk = q.get("link_key")
                if lk:
                    await episodes_collection.delete_one({"file_link_key": lk})

            lang["seasons"] = [s for s in seasons if s.get("name", "").lower() != season_name.lower()]

            season_layout = lang.get("season_layout", [])
            if len(season_layout) > len(lang["seasons"]):
                lang["season_layout"] = season_layout[: len(lang["seasons"])]

            return await _save_series(series_key, doc)

    return False


async def add_or_update_quality(series_key: str, language_name: str, season_name: str, quality_name: str, link_key: str = None):
    doc = await _load_series(series_key)
    if not doc:
        return False

    for lang in doc.get("languages", []):
        if lang.get("name", "").lower() == language_name.lower():
            for season in lang.get("seasons", []):
                if season.get("name", "").lower() == season_name.lower():
                    qualities = season.get("qualities", [])
                    for q in qualities:
                        if q.get("name", "").lower() == quality_name.lower():
                            if link_key:
                                q["link_key"] = link_key
                            break
                    else:
                        new_q = {"name": quality_name}
                        if link_key:
                            new_q["link_key"] = link_key
                        qualities.append(new_q)
                    season["qualities"] = qualities
                    return await _save_series(series_key, doc)
    return False


async def get_qualities(series_key: str, language_name: str, season_name: str):
    doc = await _load_series(series_key)
    if not doc:
        return []
    for lang in doc.get("languages", []):
        if lang.get("name", "").lower() == language_name.lower():
            for season in lang.get("seasons", []):
                if season.get("name", "").lower() == season_name.lower():
                    return season.get("qualities", [])
    return []


async def get_quality_link(series_key: str, language_name: str, season_name: str, quality_name: str):
    qualities = await get_qualities(series_key, language_name, season_name)
    for q in qualities:
        if q.get("name", "").lower() == quality_name.lower():
            return q.get("link_key")
    return None


async def delete_quality(series_key: str, language_name: str, season_name: str, quality_name: str):
    doc = await _load_series(series_key)
    if not doc:
        return False

    for lang in doc.get("languages", []):
        if lang.get("name", "").lower() == language_name.lower():
            for season in lang.get("seasons", []):
                if season.get("name", "").lower() == season_name.lower():
                    qualities = season.get("qualities", [])
                    target = None
                    for q in qualities:
                        if q.get("name", "").lower() == quality_name.lower():
                            target = q
                            break
                    if not target:
                        return False

                    lk = target.get("link_key")
                    if lk:
                        await episodes_collection.delete_one({"file_link_key": lk})

                    season["qualities"] = [q for q in qualities if q.get("name", "").lower() != quality_name.lower()]

                    quality_layout = season.get("quality_layout", [])
                    if len(quality_layout) > len(season["qualities"]):
                        season["quality_layout"] = quality_layout[: len(season["qualities"])]

                    return await _save_series(series_key, doc)

    return False


# ---------------- Publish / Subscribers ----------------

async def publish_series(series_key: str):
    doc = await _load_series(series_key)
    if not doc:
        return False

    series_to_publish = copy.deepcopy(doc)

    cleaned_languages = []
    for lang in series_to_publish.get("languages", []):
        cleaned_seasons = []
        for season in lang.get("seasons", []):
            cleaned_qualities = []
            for quality in season.get("qualities", []):
                if quality.get("link_key") and quality["link_key"] != "PENDING_LINK":
                    cleaned_qualities.append(quality)
                else:
                    lk = quality.get("link_key")
                    if lk:
                        await episodes_collection.delete_one({"file_link_key": lk})
            if cleaned_qualities:
                season["qualities"] = cleaned_qualities
                cleaned_seasons.append(season)
        if cleaned_seasons:
            lang["seasons"] = cleaned_seasons
            cleaned_languages.append(lang)

    series_to_publish["languages"] = cleaned_languages
    series_to_publish["published"] = True

    return await _save_series(series_key, series_to_publish)


async def subscribe_to_season(series_key: str, language_name: str, user_id: int):
    doc = await _load_series(series_key)
    if not doc:
        return False

    for lang in doc.get("languages", []):
        if lang.get("name", "").lower() == language_name.lower():
            subs = lang.get("season_subscribers", [])
            if int(user_id) not in subs:
                subs.append(int(user_id))
            lang["season_subscribers"] = subs
            return await _save_series(series_key, doc)
    return False


async def subscribe_to_quality(series_key: str, language_name: str, season_name: str, user_id: int):
    doc = await _load_series(series_key)
    if not doc:
        return False

    for lang in doc.get("languages", []):
        if lang.get("name", "").lower() == language_name.lower():
            for season in lang.get("seasons", []):
                if season.get("name", "").lower() == season_name.lower():
                    subs = season.get("quality_subscribers", [])
                    if int(user_id) not in subs:
                        subs.append(int(user_id))
                    season["quality_subscribers"] = subs
                    return await _save_series(series_key, doc)
    return False


async def get_season_subscribers(series_key: str, language_name: str):
    doc = await _load_series(series_key)
    if not doc:
        return []
    for lang in doc.get("languages", []):
        if lang.get("name", "").lower() == language_name.lower():
            return lang.get("season_subscribers", [])
    return []


async def get_quality_subscribers(series_key: str, language_name: str, season_name: str):
    doc = await _load_series(series_key)
    if not doc:
        return []
    for lang in doc.get("languages", []):
        if lang.get("name", "").lower() == language_name.lower():
            for season in lang.get("seasons", []):
                if season.get("name", "").lower() == season_name.lower():
                    return season.get("quality_subscribers", [])
    return []


# ---------------- Admin assignments ----------------

async def add_admin_assignment(user_id: int, channel_id: int):
    try:
        # Mongo first
        await admin_assignments_collection.update_one(
            {"user_id": int(user_id)},
            {"$set": {"channel_id": int(channel_id)}},
            upsert=True
        )
        # then PG
        await pgDb.upsert_admin_assignment(user_id, channel_id)
        logger.info(f"Added admin assignment: {user_id} -> {channel_id}")
        return True
    except Exception as e:
        logger.error(f"Error adding admin assignment: {e}")
        return False


async def remove_admin_assignment(user_id: int):
    try:
        # Mongo first
        await admin_assignments_collection.delete_one({"user_id": int(user_id)})
        # then PG
        await pgDb.remove_admin_assignment(user_id)
        logger.info(f"Removed admin assignment for user: {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error removing admin assignment: {e}")
        return False


async def get_admin_assignments():
    # PG first
    data = await pgDb.get_admin_assignments()
    if data:
        return data
    # fallback mongo
    assignments = {}
    async for doc in admin_assignments_collection.find({}):
        assignments[int(doc["user_id"])] = int(doc["channel_id"])
        await pgDb.upsert_admin_assignment(int(doc["user_id"]), int(doc["channel_id"]))
    return assignments


async def get_admin_channel(user_id: int):
    # PG first (cached)
    cid = await pgDb.get_admin_channel(user_id)
    if cid:
        return cid
    # fallback mongo + self-heal
    assignment = await admin_assignments_collection.find_one({"user_id": int(user_id)})
    if assignment:
        await pgDb.upsert_admin_assignment(int(user_id), int(assignment.get("channel_id")))
        return assignment.get("channel_id")
    return None


async def write_admin_assignments_to_env():
    try:
        assignments = await get_admin_assignments()
        env_lines = []

        if os.path.exists("./dynamic.env"):
            with open("./dynamic.env", "r") as f:
                env_lines = f.readlines()

        env_lines = [line for line in env_lines if not line.startswith("ADMIN_ASSIGNMENTS=")]
        assignments_str = ",".join([f"{uid}:{cid}" for uid, cid in assignments.items()])
        env_lines.append(f"ADMIN_ASSIGNMENTS={assignments_str}\n")

        with open("./dynamic.env", "w") as f:
            f.writelines(env_lines)

        logger.info("Admin assignments written to dynamic.env")
        return True
    except Exception as e:
        logger.error(f"Error writing admin assignments to env: {e}")
        return False
