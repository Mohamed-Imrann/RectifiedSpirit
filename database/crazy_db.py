from pymongo import MongoClient
from info import DATABASE_URI
import logging
import copy

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

client = MongoClient(DATABASE_URI)
db = client['series_database']
series_collection = db['series']
episodes_collection = client["file_database"]["episodes"]
admin_channels_collection = db['admin_channels'] # New collection for admin channels

def add_series(series_data: dict):
    try:
        # Initialize subscribers list for the series
        series_data["subscribers"] = []
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
    """Retrieves a single series document by its _id (alias for get_series_by_key)."""
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
    """Retrieves the poster file_id for a series by its key."""
    series = series_collection.find_one({"_id": series_key}, {"poster_file_id": 1})
    return series.get("poster_file_id") if series else None

def get_poster_manuel(series_key: str):
    """Retrieves the poster file_id for a series by its key (alias for get_poster_by_key)."""
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
        new_language = {"name": language_name, "seasons": [], "season_layout": [], "subscribers": []} # Initialize subscribers
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
    updated_languages = []
    deleted_language_data = None
    
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            deleted_language_data = lang
        else:
            updated_languages.append(lang)
    
    if not deleted_language_data: # Language not found
        return False

    # Delete associated file links
    if deleted_language_data:
        for season in deleted_language_data.get("seasons", []):
            for quality in season.get("qualities", []):
                if quality.get("link_key"):
                    episodes_collection.delete_one({"file_link_key": quality["link_key"]})

    # Update language layout
    language_layout = series.get("language_layout", [])
    # Simple approach: if layout length is greater than updated languages, truncate
    # A more robust solution might involve re-calculating layout based on remaining languages
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
                new_season = {"name": season_name, "qualities": [], "quality_layout": [], "subscribers": []} # Initialize subscribers
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
            updated_seasons = []
            deleted_season_data = None

            for s in seasons:
                if s["name"].lower() == season_name.lower():
                    deleted_season_data = s
                else:
                    updated_seasons.append(s)
            
            if not deleted_season_data: # Season not found
                return False

            # Delete associated file links
            if deleted_season_data:
                for quality in deleted_season_data.get("qualities", []):
                    if quality.get("link_key"):
                        episodes_collection.delete_one({"file_link_key": quality["link_key"]})
            
            # Update season layout
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
                        new_quality = {"name": quality_name, "subscribers": []} # Initialize subscribers
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
                    updated_qualities = []
                    deleted_quality_data = None

                    for q in qualities:
                        if q["name"].lower() == quality_name.lower():
                            deleted_quality_data = q
                        else:
                            updated_qualities.append(q)
                    
                    if not deleted_quality_data: # Quality not found
                        return False

                    # Delete associated file links
                    if deleted_quality_data and deleted_quality_data.get("link_key"):
                        episodes_collection.delete_one({"file_link_key": deleted_quality_data["link_key"]})
                    
                    # Update quality layout
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
                    # If link_key is missing or PENDING_LINK, delete associated episode entry
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

# --- Admin Channel Management Functions ---
def add_admin_channel(admin_id: int, channel_id: int):
    try:
        admin_channels_collection.update_one(
            {"_id": admin_id},
            {"$set": {"channel_id": channel_id}},
            upsert=True
        )
        logger.info(f"Admin {admin_id} assigned channel {channel_id}")
        return True
    except Exception as e:
        logger.error(f"Error assigning channel to admin {admin_id}: {e}")
        return False

def get_admin_channel(admin_id: int):
    try:
        doc = admin_channels_collection.find_one({"_id": admin_id})
        return doc.get("channel_id") if doc else None
    except Exception as e:
        logger.error(f"Error getting channel for admin {admin_id}: {e}")
        return None

# --- Notification Subscription Functions ---

def add_subscriber(series_key: str, user_id: int, language_name: str = None, season_name: str = None, quality_name: str = None):
    try:
        if not language_name: # Subscribe to series updates
            series_collection.update_one(
                {"_id": series_key},
                {"$addToSet": {"subscribers": user_id}}
            )
            return True
        
        # Find the specific language, season, or quality and add subscriber
        update_query = {"_id": series_key}
        
        if quality_name:
            update_query["languages.name"] = language_name
            update_query["languages.seasons.name"] = season_name
            update_query["languages.seasons.qualities.name"] = quality_name
            update_field = "languages.$.seasons.$.qualities.$.subscribers"
        elif season_name:
            update_query["languages.name"] = language_name
            update_query["languages.seasons.name"] = season_name
            update_field = "languages.$.seasons.$.subscribers"
        else: # language_name only
            update_query["languages.name"] = language_name
            update_field = "languages.$.subscribers"
        
        result = series_collection.update_one(
            update_query,
            {"$addToSet": {update_field: user_id}}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error adding subscriber: {e}")
        return False

def remove_subscriber(series_key: str, user_id: int, language_name: str = None, season_name: str = None, quality_name: str = None):
    try:
        if not language_name: # Unsubscribe from series updates
            series_collection.update_one(
                {"_id": series_key},
                {"$pull": {"subscribers": user_id}}
            )
            return True
        
        update_query = {"_id": series_key}
        
        if quality_name:
            update_query["languages.name"] = language_name
            update_query["languages.seasons.name"] = season_name
            update_query["languages.seasons.qualities.name"] = quality_name
            update_field = "languages.$.seasons.$.qualities.$.subscribers"
        elif season_name:
            update_query["languages.name"] = language_name
            update_query["languages.seasons.name"] = season_name
            update_field = "languages.$.seasons.$.subscribers"
        else: # language_name only
            update_query["languages.name"] = language_name
            update_field = "languages.$.subscribers"
        
        result = series_collection.update_one(
            update_query,
            {"$pull": {update_field: user_id}}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error removing subscriber: {e}")
        return False

def get_subscribers(series_key: str, language_name: str = None, season_name: str = None, quality_name: str = None):
    series = series_collection.find_one({"_id": series_key})
    if not series:
        return []

    if not language_name: # Get series subscribers
        return series.get("subscribers", [])
    
    for lang in series.get("languages", []):
        if lang["name"].lower() == language_name.lower():
            if not season_name: # Get language subscribers
                return lang.get("subscribers", [])
            for season in lang.get("seasons", []):
                if season["name"].lower() == season_name.lower():
                    if not quality_name: # Get season subscribers
                        return season.get("subscribers", [])
                    for quality in season.get("qualities", []):
                        if quality["name"].lower() == quality_name.lower(): # Get quality subscribers
                            return quality.get("subscribers", [])
    return []
