from pymongo import MongoClient
from info import DATABASE_URI
import logging
import copy
import os
from datetime import datetime

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

client = MongoClient(DATABASE_URI)
db = client['series_database']
series_collection = db['series']
episodes_collection = client["file_database"]["episodes"]
admin_assignments_collection = db['admin_assignments']

def add_series(series_data: dict):
    try:
        series_collection.insert_one(series_data)
        logger.info(f"Series '{series_data.get('title', 'N/A')}' added with key: {series_data['_id']}")
        return True
    except Exception as e:
        logger.error(f"Error adding series: {e}")
        return False

def get_series():
    return list(series_collection.find({}))

def get_series_by_key(series_key: str):
    return series_collection.find_one({"_id": series_key})

def get_series_name(series_key: str):
    return get_series_by_key(series_key)

def update_series_field(series_key: str, field: str, value):
    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {field: value}})
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error updating series: {e}")
        return False

def get_poster_file_id(series_key: str):
    series = series_collection.find_one({"_id": series_key}, {"poster_file_id": 1})
    return series.get("poster_file_id") if series else None

def update_poster_file_id(series_key: str, poster_file_id: str):
    return update_series_field(series_key, "poster_file_id", poster_file_id)

def get_poster_by_key(series_key: str):
    series = series_collection.find_one({"_id": series_key}, {"poster_file_id": 1})
    return series.get("poster_file_id") if series else None

def get_poster_manuel(series_key: str):
    return get_poster_by_key(series_key)

def add_or_update_language(series_key: str, language_name: str, poster_file_id: str = None):
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return False

    languages = series.get("languages", [])
    language_exists = False
    
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            if poster_file_id:
                lang["poster_file_id"] = poster_file_id
            language_exists = True
            break
    
    if not language_exists:
        new_language = {"name": language_name, "seasons": [], "season_layout": []}
        if poster_file_id:
            new_language["poster_file_id"] = poster_file_id
        languages.append(new_language)
    
    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
        return result.modified_count > 0 or result.upserted_id
    except Exception as e:
        logger.error(f"Error adding language: {e}")
        return False

def get_languages(series_key: str):
    series = series_collection.find_one({"_id": series_key}, {"languages": 1})
    return series.get("languages", []) if series else []

def delete_language(series_key: str, language_name: str):
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return False

    languages = series.get("languages", [])
    updated_languages = [lang for lang in languages if lang["name"].lower() != language_name.lower()]
    
    if len(updated_languages) == len(languages):
        return False

    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            for season in lang.get("seasons", []):
                for quality in season.get("qualities", []):
                    if quality.get("link_key"):
                        episodes_collection.delete_one({"file_link_key": quality["link_key"]})
            break

    language_layout = series.get("language_layout", [])
    if len(language_layout) > len(updated_languages):
        language_layout = language_layout[:len(updated_languages)]

    try:
        result = series_collection.update_one(
            {"_id": series_key}, 
            {"$set": {"languages": updated_languages, "language_layout": language_layout}}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error deleting language: {e}")
        return False

def add_or_update_season(series_key: str, language_name: str, season_name: str, poster_file_id: str = None):
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return False

    languages = series.get("languages", [])
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            seasons = lang.get("seasons", [])
            season_exists = False
            for season in seasons:
                if season["name"].lower() == season_name.lower():
                    if poster_file_id:
                        season["poster_file_id"] = poster_file_id
                    season_exists = True
                    break
            if not season_exists:
                new_season = {"name": season_name, "qualities": [], "quality_layout": []}
                if poster_file_id:
                    new_season["poster_file_id"] = poster_file_id
                seasons.append(new_season)
            lang["seasons"] = seasons
            break
    
    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error adding season: {e}")
        return False

def get_seasons(series_key: str, language_name: str):
    series = series_collection.find_one({"_id": series_key}, {"languages": 1})
    if series:
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                return lang.get("seasons", [])
    return []

def delete_season(series_key: str, language_name: str, season_name: str):
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return False

    languages = series.get("languages", [])
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            seasons = lang.get("seasons", [])
            updated_seasons = [s for s in seasons if s["name"].lower() != season_name.lower()]
            
            if len(updated_seasons) == len(seasons):
                return False

            for season in seasons:
                if season["name"].lower() == season_name.lower():
                    for quality in season.get("qualities", []):
                        if quality.get("link_key"):
                            episodes_collection.delete_one({"file_link_key": quality["link_key"]})
                    break
            
            season_layout = lang.get("season_layout", [])
            if len(season_layout) > len(updated_seasons):
                season_layout = season_layout[:len(updated_seasons)]
            
            lang["seasons"] = updated_seasons
            lang["season_layout"] = season_layout
            break
    
    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error deleting season: {e}")
        return False

def add_or_update_quality(series_key: str, language_name: str, season_name: str, quality_name: str, link_key: str = None):
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return False

    languages = series.get("languages", [])
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            seasons = lang.get("seasons", [])
            for season in seasons:
                if season["name"].lower() == season_name.lower():
                    qualities = season.get("qualities", [])
                    quality_exists = False
                    for quality in qualities:
                        if quality["name"].lower() == quality_name.lower():
                            if link_key:
                                quality["link_key"] = link_key
                            quality_exists = True
                            break
                    if not quality_exists:
                        new_quality = {"name": quality_name}
                        if link_key:
                            new_quality["link_key"] = link_key
                        qualities.append(new_quality)
                    season["qualities"] = qualities
                    break
            break
    
    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error adding quality: {e}")
        return False

def get_qualities(series_key: str, language_name: str, season_name: str):
    series = series_collection.find_one({"_id": series_key}, {"languages": 1})
    if series:
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                for season in lang.get("seasons", []):
                    if season["name"].lower() == season_name.lower():
                        return season.get("qualities", [])
    return []

def get_quality_link(series_key: str, language_name: str, season_name: str, quality_name: str):
    series = series_collection.find_one({"_id": series_key}, {"languages": 1})
    if series:
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                for season in lang.get("seasons", []):
                    if season["name"].lower() == season_name.lower():
                        for quality in season.get("qualities", []):
                            if quality["name"].lower() == quality_name.lower():
                                return quality.get("link_key")
    return None

def delete_quality(series_key: str, language_name: str, season_name: str, quality_name: str):
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return False

    languages = series.get("languages", [])
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            seasons = lang.get("seasons", [])
            for season in seasons:
                if season["name"].lower() == season_name.lower():
                    qualities = season.get("qualities", [])
                    updated_qualities = [q for q in qualities if q["name"].lower() != quality_name.lower()]
                    
                    if len(updated_qualities) == len(qualities):
                        return False

                    for quality in qualities:
                        if quality["name"].lower() == quality_name.lower():
                            if quality.get("link_key"):
                                episodes_collection.delete_one({"file_link_key": quality["link_key"]})
                            break
                    
                    quality_layout = season.get("quality_layout", [])
                    if len(quality_layout) > len(updated_qualities):
                        quality_layout = quality_layout[:len(updated_qualities)]
                    
                    season["qualities"] = updated_qualities
                    season["quality_layout"] = quality_layout
                    break
            break
    
    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error deleting quality: {e}")
        return False

def publish_series(series_key: str):
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return False

    series_to_publish = copy.deepcopy(series)

    cleaned_languages = []
    for lang in series_to_publish.get("languages", []):
        cleaned_seasons = []
        for season in lang.get("seasons", []):
            cleaned_qualities = []
            for quality in season.get("qualities", []):
                if quality.get("link_key") and quality["link_key"] != "PENDING_LINK":
                    cleaned_qualities.append(quality)
                else:
                    if quality.get("link_key"):
                        episodes_collection.delete_one({"file_link_key": quality["link_key"]})
            if cleaned_qualities:
                season["qualities"] = cleaned_qualities
                cleaned_seasons.append(season)
        if cleaned_seasons:
            lang["seasons"] = cleaned_seasons
            cleaned_languages.append(lang)
    
    series_to_publish["languages"] = cleaned_languages
    series_to_publish["published"] = True

    try:
        result = series_collection.replace_one({"_id": series_key}, series_to_publish)
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error publishing series: {e}")
        return False

def subscribe_to_season(series_key: str, language_name: str, user_id: int):
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return False

    for lang in series.get("languages", []):
        if lang["name"].lower() == language_name.lower():
            subs = lang.get("season_subscribers", [])
            if user_id not in subs:
                subs.append(user_id)
                lang["season_subscribers"] = subs
            break

    try:
        series_collection.update_one({"_id": series_key}, {"$set": {"languages": series["languages"]}})
        return True
    except Exception as e:
        logger.error(f"Error subscribing to season: {e}")
        return False

def subscribe_to_quality(series_key: str, language_name: str, season_name: str, user_id: int):
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return False

    for lang in series.get("languages", []):
        if lang["name"].lower() == language_name.lower():
            for season in lang.get("seasons", []):
                if season["name"].lower() == season_name.lower():
                    subs = season.get("quality_subscribers", [])
                    if user_id not in subs:
                        subs.append(user_id)
                        season["quality_subscribers"] = subs
                    break
            break

    try:
        series_collection.update_one({"_id": series_key}, {"$set": {"languages": series["languages"]}})
        return True
    except Exception as e:
        logger.error(f"Error subscribing to quality: {e}")
        return False

def get_season_subscribers(series_key: str, language_name: str):
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return []
    for lang in series.get("languages", []):
        if lang["name"].lower() == language_name.lower():
            return lang.get("season_subscribers", [])
    return []

def get_quality_subscribers(series_key: str, language_name: str, season_name: str):
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return []
    for lang in series.get("languages", []):
        if lang["name"].lower() == language_name.lower():
            for season in lang.get("seasons", []):
                if season["name"].lower() == season_name.lower():
                    return season.get("quality_subscribers", [])
    return []

def add_admin_assignment(user_id: int, channel_id: int):
    try:
        admin_assignments_collection.update_one(
            {"user_id": user_id},
            {"$set": {"channel_id": channel_id}},
            upsert=True
        )
        logger.info(f"Added admin assignment: {user_id} -> {channel_id}")
        return True
    except Exception as e:
        logger.error(f"Error adding admin assignment: {e}")
        return False

def remove_admin_assignment(user_id: int):
    try:
        result = admin_assignments_collection.delete_one({"user_id": user_id})
        if result.deleted_count > 0:
            logger.info(f"Removed admin assignment for user: {user_id}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error removing admin assignment: {e}")
        return False

def get_admin_assignments():
    try:
        assignments = {}
        for doc in admin_assignments_collection.find({}):
            assignments[doc["user_id"]] = doc["channel_id"]
        return assignments
    except Exception as e:
        logger.error(f"Error getting admin assignments: {e}")
        return {}

def write_admin_assignments_to_env():
    try:
        assignments = get_admin_assignments()
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
