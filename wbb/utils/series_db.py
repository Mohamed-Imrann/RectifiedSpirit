# wbb/core/database/series_db.py
import logging
from copy import deepcopy
from datetime import datetime
from typing import List, Dict, Any, Optional

from wbb import app, log, mongo_client, db

# Initialize collections
series_collection = db.series
episodes_collection = mongo_client["file_database"]["episodes"]
admin_assignments_collection = db.admin_assignments

logger = logging.getLogger(__name__)

# Helper functions
def _find(obj_list, name: str):
    """Find item in list by name (case-insensitive)"""
    return next((o for o in obj_list if o.get("name", "").lower() == name.lower()), None)

async def add_series(series_data: dict) -> bool:
    try:
        await series_collection.insert_one(series_data)
        logger.info(f"Series '{series_data.get('title', 'N/A')}' added")
        return True
    except Exception as e:
        logger.error(f"Error adding series: {e}")
        return False

async def get_series() -> List[Dict]:
    return await series_collection.find({}).to_list(length=None)

async def get_series_by_key(series_key: str) -> Optional[Dict]:
    return await series_collection.find_one({"_id": series_key})

async def update_series_field(series_key: str, field: str, value) -> bool:
    try:
        result = await series_collection.update_one(
            {"_id": series_key}, 
            {"$set": {field: value}}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error updating series: {e}")
        return False

async def update_series(series_key: str, update_data: dict) -> bool:
    try:
        result = await series_collection.update_one(
            {"_id": series_key},
            {"$set": update_data}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error updating series: {e}")
        return False

# Poster management
async def get_poster_file_id(series_key: str) -> Optional[str]:
    series = await get_series_by_key(series_key)
    return series.get("poster_file_id") if series else None

async def update_poster_file_id(series_key: str, poster_file_id: str) -> bool:
    return await update_series_field(series_key, "poster_file_id", poster_file_id)

# Language management
async def add_or_update_language(series_key: str, language_name: str, poster_file_id: str = None) -> bool:
    series = await get_series_by_key(series_key)
    if not series:
        return False

    languages = series.get("languages", [])
    language = _find(languages, language_name)
    
    if not language:
        language = {"name": language_name, "seasons": [], "season_layout": []}
        languages.append(language)
    
    if poster_file_id:
        language["poster_file_id"] = poster_file_id
    
    return await update_series_field(series_key, "languages", languages)

async def get_languages(series_key: str) -> List[Dict]:
    series = await get_series_by_key(series_key)
    return series.get("languages", []) if series else []

async def delete_language(series_key: str, language_name: str) -> bool:
    series = await get_series_by_key(series_key)
    if not series:
        return False

    languages = series.get("languages", [])
    updated_languages = [lang for lang in languages if lang["name"].lower() != language_name.lower()]
    
    if len(updated_languages) == len(languages):
        return False

    return await update_series_field(series_key, "languages", updated_languages)

# Season management
async def add_or_update_season(series_key: str, language_name: str, season_name: str, poster_file_id: str = None) -> bool:
    series = await get_series_by_key(series_key)
    if not series:
        return False

    languages = series.get("languages", [])
    language = _find(languages, language_name)
    if not language:
        return False

    seasons = language.get("seasons", [])
    season = _find(seasons, season_name)
    
    if not season:
        season = {"name": season_name, "qualities": [], "quality_layout": []}
        seasons.append(season)
    
    if poster_file_id:
        season["poster_file_id"] = poster_file_id
    
    return await update_series_field(series_key, "languages", languages)

async def get_seasons(series_key: str, language_name: str) -> List[Dict]:
    languages = await get_languages(series_key)
    language = _find(languages, language_name)
    return language.get("seasons", []) if language else []

async def delete_season(series_key: str, language_name: str, season_name: str) -> bool:
    series = await get_series_by_key(series_key)
    if not series:
        return False

    languages = series.get("languages", [])
    language = _find(languages, language_name)
    if not language:
        return False

    seasons = language.get("seasons", [])
    updated_seasons = [s for s in seasons if s["name"].lower() != season_name.lower()]
    
    if len(updated_seasons) == len(seasons):
        return False

    language["seasons"] = updated_seasons
    return await update_series_field(series_key, "languages", languages)

# Quality management
async def add_or_update_quality(series_key: str, language_name: str, season_name: str, 
                               quality_name: str, link_key: str = None) -> bool:
    series = await get_series_by_key(series_key)
    if not series:
        return False

    languages = series.get("languages", [])
    language = _find(languages, language_name)
    if not language:
        return False

    seasons = language.get("seasons", [])
    season = _find(seasons, season_name)
    if not season:
        return False

    qualities = season.get("qualities", [])
    quality = _find(qualities, quality_name)
    
    if not quality:
        quality = {"name": quality_name}
        qualities.append(quality)
    
    if link_key:
        quality["link_key"] = link_key
    
    return await update_series_field(series_key, "languages", languages)

async def get_qualities(series_key: str, language_name: str, season_name: str) -> List[Dict]:
    seasons = await get_seasons(series_key, language_name)
    season = _find(seasons, season_name)
    return season.get("qualities", []) if season else []

async def get_quality_link(series_key: str, language_name: str, season_name: str, quality_name: str) -> Optional[str]:
    qualities = await get_qualities(series_key, language_name, season_name)
    quality = _find(qualities, quality_name)
    return quality.get("link_key") if quality else None

async def delete_quality(series_key: str, language_name: str, season_name: str, quality_name: str) -> bool:
    series = await get_series_by_key(series_key)
    if not series:
        return False

    languages = series.get("languages", [])
    language = _find(languages, language_name)
    if not language:
        return False

    seasons = language.get("seasons", [])
    season = _find(seasons, season_name)
    if not season:
        return False

    qualities = season.get("qualities", [])
    updated_qualities = [q for q in qualities if q["name"].lower() != quality_name.lower()]
    
    if len(updated_qualities) == len(qualities):
        return False

    season["qualities"] = updated_qualities
    return await update_series_field(series_key, "languages", languages)

# Admin assignments
async def get_admin_channel(user_id: int) -> Optional[int]:
    assignment = await admin_assignments_collection.find_one({"user_id": user_id})
    return assignment.get("channel_id") if assignment else None

async def add_admin_assignment(user_id: int, channel_id: int) -> bool:
    try:
        await admin_assignments_collection.update_one(
            {"user_id": user_id},
            {"$set": {"channel_id": channel_id}},
            upsert=True
        )
        logger.info(f"Added admin assignment: {user_id} -> {channel_id}")
        return True
    except Exception as e:
        logger.error(f"Error adding admin assignment: {e}")
        return False

async def remove_admin_assignment(user_id: int) -> bool:
    try:
        result = await admin_assignments_collection.delete_one({"user_id": user_id})
        if result.deleted_count > 0:
            logger.info(f"Removed admin assignment for user: {user_id}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error removing admin assignment: {e}")
        return False

async def get_admin_assignments() -> Dict[int, int]:
    try:
        assignments = {}
        async for doc in admin_assignments_collection.find({}):
            assignments[doc["user_id"]] = doc["channel_id"]
        return assignments
    except Exception as e:
        logger.error(f"Error getting admin assignments: {e}")
        return {}
