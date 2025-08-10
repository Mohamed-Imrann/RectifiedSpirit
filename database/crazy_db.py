import pymongo
import logging
from typing import Dict, List, Any, Optional, Union
from info import DATABASE_URI

logger = logging.getLogger(__name__)

# MongoDB connection
client = pymongo.MongoClient(DATABASE_URI)
db = client['series_database']
series_collection = db['series']
episodes_collection = client["file_database"]["episodes"]

def add_series(series_data: dict):
    """Adds a new series document to the database. Uses _id as the primary key."""
    try:
        series_collection.insert_one(series_data)
        logger.info(f"Series '{series_data.get('title', 'N/A')}' added with key: {series_data['_id']}")
        return True
    except Exception as e:
        logger.error(f"Error adding series '{series_data.get('title', 'N/A')}': {e}")
        return False

def get_series():
    """Returns all series documents."""
    return list(series_collection.find({}))

def get_series_by_key(series_key: str):
    """Retrieves a single series document by its _id."""
    return series_collection.find_one({"_id": series_key})

def update_series_field(series_key: str, field: str, value):
    """Updates a top-level field of a series document."""
    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {field: value}})
        if result.modified_count > 0:
            logger.info(f"Series '{series_key}' field '{field}' updated.")
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating series '{series_key}' field '{field}': {e}")
        return False

def get_poster_file_id(series_key: str):
    """Retrieves the main poster file_id for a series."""
    series = series_collection.find_one({"_id": series_key}, {"poster_file_id": 1})
    return series.get("poster_file_id") if series else None

def update_poster_file_id(series_key: str, poster_file_id: str):
    """Updates the main poster file_id for a series."""
    return update_series_field(series_key, "poster_file_id", poster_file_id)

def add_or_update_language(series_key: str, language_name: str, poster_file_id: str = None):
    """Adds a new language or updates an existing one for a series."""
    series = series_collection.find_one({"_id": series_key})
    if not series:
        logger.error(f"Series '{series_key}' not found for language update.")
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
        new_language = {"name": language_name, "seasons": []}
        if poster_file_id:
            new_language["poster_file_id"] = poster_file_id
        languages.append(new_language)
    
    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
        if result.modified_count > 0 or result.upserted_id:
            logger.info(f"Language '{language_name}' added/updated for series '{series_key}'.")
            return True
        return False
    except Exception as e:
        logger.error(f"Error adding/updating language '{language_name}' for series '{series_key}': {e}")
        return False

def get_languages(series_key: str):
    """Returns the list of languages for a series."""
    series = series_collection.find_one({"_id": series_key}, {"languages": 1})
    return series.get("languages", []) if series else []

def delete_language(series_key: str, language_name: str):
    """Deletes a language and all its nested data (seasons, qualities, file links)."""
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return False

    languages = series.get("languages", [])
    updated_languages = [lang for lang in languages if lang["name"].lower() != language_name.lower()]
    
    if len(updated_languages) == len(languages):  # Language not found
        return False

    # Delete associated file links from episodes collection
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            for season in lang.get("seasons", []):
                for quality in season.get("qualities", []):
                    if quality.get("link_key"):
                        episodes_collection.delete_one({"file_link_key": quality["link_key"]})
                        logger.info(f"Deleted episode link for {quality['link_key']}")
            break

    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {"languages": updated_languages}})
        if result.modified_count > 0:
            logger.info(f"Language '{language_name}' and its data deleted for series '{series_key}'.")
            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting language '{language_name}' for series '{series_key}': {e}")
        return False

def add_or_update_season(series_key: str, language_name: str, season_name: str, poster_file_id: str = None):
    """Adds a new season or updates an existing one for a specific language."""
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
                new_season = {"name": season_name, "qualities": []}
                if poster_file_id:
                    new_season["poster_file_id"] = poster_file_id
                seasons.append(new_season)
            lang["seasons"] = seasons
            break
    
    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
        if result.modified_count > 0:
            logger.info(f"Season '{season_name}' added/updated for series '{series_key}' language '{language_name}'.")
            return True
        return False
    except Exception as e:
        logger.error(f"Error adding/updating season '{season_name}' for series '{series_key}' language '{language_name}': {e}")
        return False

def get_seasons(series_key: str, language_name: str):
    """Returns the list of seasons for a specific language in a series."""
    series = series_collection.find_one({"_id": series_key}, {"languages": 1})
    if series:
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                return lang.get("seasons", [])
    return []

def delete_season(series_key: str, language_name: str, season_name: str):
    """Deletes a season and all its nested data (qualities, file links)."""
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return False

    languages = series.get("languages", [])
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            seasons = lang.get("seasons", [])
            updated_seasons = [s for s in seasons if s["name"].lower() != season_name.lower()]
            
            if len(updated_seasons) == len(seasons):  # Season not found
                return False

            # Delete associated file links from episodes collection
            for season in seasons:
                if season["name"].lower() == season_name.lower():
                    for quality in season.get("qualities", []):
                        if quality.get("link_key"):
                            episodes_collection.delete_one({"file_link_key": quality["link_key"]})
                            logger.info(f"Deleted episode link for {quality['link_key']}")
                    break
            
            lang["seasons"] = updated_seasons
            break
    
    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
        if result.modified_count > 0:
            logger.info(f"Season '{season_name}' and its data deleted for series '{series_key}' language '{language_name}'.")
            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting season '{season_name}' for series '{series_key}' language '{language_name}': {e}")
        return False

def add_or_update_quality(series_key: str, language_name: str, season_name: str, quality_name: str, link_key: str = None, codec: str = None):
    """Adds a new quality or updates an existing one for a specific season."""
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
                            if codec:
                                quality["codec"] = codec
                            quality_exists = True
                            break
                    if not quality_exists:
                        new_quality = {"name": quality_name}
                        if link_key:
                            new_quality["link_key"] = link_key
                        if codec:
                            new_quality["codec"] = codec
                        qualities.append(new_quality)
                    season["qualities"] = qualities
                    break
            break
    
    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
        if result.modified_count > 0:
            logger.info(f"Quality '{quality_name}' added/updated for series '{series_key}' language '{language_name}' season '{season_name}'.")
            return True
        return False
    except Exception as e:
        logger.error(f"Error adding/updating quality '{quality_name}' for series '{series_key}' language '{language_name}' season '{season_name}': {e}")
        return False

def get_qualities(series_key: str, language_name: str, season_name: str):
    """Returns the list of qualities for a specific season in a language."""
    series = series_collection.find_one({"_id": series_key}, {"languages": 1})
    if series:
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                for season in lang.get("seasons", []):
                    if season["name"].lower() == season_name.lower():
                        return season.get("qualities", [])
    return []

def get_quality_link(series_key: str, language_name: str, season_name: str, quality_name: str):
    """Returns the link_key for a specific quality."""
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
    """Deletes a quality and its associated file links."""
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
                    
                    if len(updated_qualities) == len(qualities):  # Quality not found
                        return False

                    # Delete associated file links from episodes collection
                    for quality in qualities:
                        if quality["name"].lower() == quality_name.lower():
                            if quality.get("link_key"):
                                episodes_collection.delete_one({"file_link_key": quality["link_key"]})
                                logger.info(f"Deleted episode link for {quality['link_key']}")
                            break
                    
                    season["qualities"] = updated_qualities
                    break
            break
    
    try:
        result = series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
        if result.modified_count > 0:
            logger.info(f"Quality '{quality_name}' and its data deleted for series '{series_key}' language '{language_name}' season '{season_name}'.")
            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting quality '{quality_name}' for series '{series_key}' language '{language_name}' season '{season_name}': {e}")
        return False

def publish_series(series_key: str):
    """
    Sets the 'published' status of a series to True and cleans up empty groups.
    Also removes any quality entries that do not have a 'link_key'.
    """
    import copy
    series = series_collection.find_one({"_id": series_key})
    if not series:
        logger.error(f"Series '{series_key}' not found for publishing.")
        return False

    # Create a deep copy to modify and then save
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
                    # If quality has no link_key or is PENDING_LINK, delete its potential entry in episodes_collection
                    if quality.get("link_key"):
                        episodes_collection.delete_one({"file_link_key": quality["link_key"]})
                        logger.info(f"Removed unlinked/pending quality {quality.get('name')} and its episode link.")
            if cleaned_qualities:
                season["qualities"] = cleaned_qualities
                cleaned_seasons.append(season)
            else:
                logger.info(f"Removed empty season {season.get('name')} from language {lang.get('name')}.")
        if cleaned_seasons:
            lang["seasons"] = cleaned_seasons
            cleaned_languages.append(lang)
        else:
            logger.info(f"Removed empty language {lang.get('name')}.")
    
    series_to_publish["languages"] = cleaned_languages
    series_to_publish["published"] = True

    try:
        result = series_collection.replace_one({"_id": series_key}, series_to_publish)
        if result.modified_count > 0:
            logger.info(f"Series '{series_key}' published successfully and cleaned up.")
            return True
        return False
    except Exception as e:
        logger.error(f"Error publishing series '{series_key}': {e}")
        return False

def get_series_name(series_key: str):
    """Retrieves a series document by its _id with a simplified structure for the user interface."""
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return None
    
    # Simplify the structure for the user interface
    simplified = {
        'key': series['_id'],
        'title': series.get('title', 'N/A'),
        'released_on': series.get('released_on', 'N/A'),
        'genre': series.get('genre', 'N/A'),
        'rating': series.get('rating', 'N/A'),
        'media_type': series.get('media_type', 'N/A'),
        'poster_url': series.get('poster_file_id'),
        'languages': {}
    }
    
    # Simplify languages structure
    for lang in series.get("languages", []):
        lang_key = lang['name'].lower().replace(" ", "_")
        simplified['languages'][lang_key] = {
            'name': lang['name'],
            'poster_url': lang.get('poster_file_id'),
            'seasons': {}
        }
        
        # Simplify seasons structure
        for season in lang.get("seasons", []):
            season_key = season['name'].lower().replace(" ", "_")
            simplified['languages'][lang_key]['seasons'][season_key] = {
                'name': season['name'],
                'poster_url': season.get('poster_file_id'),
                'qualities': {}
            }
            
            # Simplify qualities structure
            for quality in season.get("qualities", []):
                quality_key = quality['name'].lower().replace(" ", "_")
                simplified['languages'][lang_key]['seasons'][season_key]['qualities'][quality_key] = {
                    'name': quality['name'],
                    'file_link_key': quality.get('link_key'),
                    'codec': quality.get('codec')
                }
    
    return simplified

def get_poster_manuel(series_key: str):
    """Retrieves the poster URL for a series."""
    series = series_collection.find_one({"_id": series_key}, {"poster_file_id": 1})
    return series.get("poster_file_id") if series else None

def get_links_for_quality(file_link_key: str):
    """Retrieves the file links for a quality from the episodes collection."""
    if not file_link_key:
        return [], None, None, None
    
    # Parse the link_key to get channel_id and message IDs
    try:
        parts = file_link_key.split('_')
        if len(parts) < 2:
            return [], None, None, None
        
        channel_id = parts[0]
        first_msg_id = int(parts[1])
        last_msg_id = int(parts[-1])
        
        # Get all messages in the range
        files_to_send = []
        for msg_id in range(first_msg_id, last_msg_id + 1):
            file_data = episodes_collection.find_one({"file_link_key": file_link_key, "message_id": msg_id})
            if file_data:
                files_to_send.append({
                    "file_id": file_data.get("file_id"),
                    "caption": file_data.get("caption", "")
                })
        
        return files_to_send, channel_id, first_msg_id, last_msg_id
    except Exception as e:
        logger.error(f"Error getting links for quality {file_link_key}: {e}")
        return [], None, None, None
