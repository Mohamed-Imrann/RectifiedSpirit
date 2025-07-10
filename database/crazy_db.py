from pymongo import MongoClient
from info import DATABASE_URI
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

client = MongoClient(DATABASE_URI)
db = client['series_database']
series_collection = db['series']

def add_series(series_data):
    """Adds or updates a series document."""
    series_collection.update_one({"_id": series_data['_id']}, {"$set": series_data}, upsert=True)

def get_series():
    """Returns a list of all series documents."""
    return list(series_collection.find())

def get_series_by_key(series_key):
    """Retrieves a single series document by its key (which is _id)."""
    return series_collection.find_one({"_id": series_key})

def delete_series(series_key):
    """Deletes a series document."""
    series_collection.delete_one({"_id": series_key})

def delete_all_series():
    """Deletes all series documents."""
    series_collection.delete_many({})

def update_series_field(series_key, field, value):
    """Updates a top-level field in a series document."""
    series_collection.update_one({"_id": series_key}, {"$set": {field: value}})

def add_or_update_language(series_key, language_name, poster_file_id=None):
    """Adds a new language or updates its poster for a series."""
    series = get_series_by_key(series_key)
    if not series:
        return False

    languages = series.get("languages", [])
    found = False
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            if poster_file_id:
                lang["poster_file_id"] = poster_file_id
            found = True
            break
    
    if not found:
        new_language = {"name": language_name, "seasons": []}
        if poster_file_id:
            new_language["poster_file_id"] = poster_file_id
        languages.append(new_language)
    
    series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
    return True

def get_languages(series_key):
    """Returns a list of language names for a series."""
    series = get_series_by_key(series_key)
    if series:
        return [lang["name"] for lang in series.get("languages", [])]
    return []

def delete_language(series_key, language_name):
    """Deletes a language and all its nested data from a series."""
    series = get_series_by_key(series_key)
    if not series:
        return False
    
    languages = series.get("languages", [])
    updated_languages = [lang for lang in languages if lang["name"].lower() != language_name.lower()]
    
    series_collection.update_one({"_id": series_key}, {"$set": {"languages": updated_languages}})
    return len(languages) != len(updated_languages) # True if something was deleted

def add_or_update_season(series_key, language_name, season_name, poster_file_id=None):
    """Adds a new season or updates its poster for a specific language."""
    series = get_series_by_key(series_key)
    if not series:
        return False

    languages = series.get("languages", [])
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            seasons = lang.get("seasons", [])
            found = False
            for season in seasons:
                if season["name"].lower() == season_name.lower():
                    if poster_file_id:
                        season["poster_file_id"] = poster_file_id
                    found = True
                    break
            if not found:
                new_season = {"name": season_name, "qualities": []}
                if poster_file_id:
                    new_season["poster_file_id"] = poster_file_id
                seasons.append(new_season)
            lang["seasons"] = seasons
            break
    
    series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
    return True

def get_seasons(series_key, language_name):
    """Returns a list of season names for a specific language."""
    series = get_series_by_key(series_key)
    if series:
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                return [season["name"] for season in lang.get("seasons", [])]
    return []

def delete_season(series_key, language_name, season_name):
    """Deletes a season and all its nested data from a specific language."""
    series = get_series_by_key(series_key)
    if not series:
        return False
    
    languages = series.get("languages", [])
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            seasons = lang.get("seasons", [])
            updated_seasons = [season for season in seasons if season["name"].lower() != season_name.lower()]
            lang["seasons"] = updated_seasons
            series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
            return len(seasons) != len(updated_seasons) # True if something was deleted
    return False

def add_or_update_quality(series_key, language_name, season_name, quality_name, link_key, codec=None):
    """Adds a new quality or updates its link/codec for a specific season."""
    series = get_series_by_key(series_key)
    if not series:
        return False

    languages = series.get("languages", [])
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            seasons = lang.get("seasons", [])
            for season in seasons:
                if season["name"].lower() == season_name.lower():
                    qualities = season.get("qualities", [])
                    found = False
                    for quality in qualities:
                        if quality["name"].lower() == quality_name.lower():
                            quality["link_key"] = link_key
                            if codec:
                                quality["codec"] = codec
                            found = True
                            break
                    if not found:
                        new_quality = {"name": quality_name, "link_key": link_key}
                        if codec:
                            new_quality["codec"] = codec
                        qualities.append(new_quality)
                    season["qualities"] = qualities
                    break
            lang["seasons"] = seasons
            break
    
    series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
    return True

def get_qualities(series_key, language_name, season_name):
    """Returns a list of quality names for a specific season."""
    series = get_series_by_key(series_key)
    if series:
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                for season in lang.get("seasons", []):
                    if season["name"].lower() == season_name.lower():
                        return [quality["name"] for quality in season.get("qualities", [])]
    return []

def get_quality_link(series_key, language_name, season_name, quality_name):
    """Returns the link_key for a specific quality."""
    series = get_series_by_key(series_key)
    if series:
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                for season in lang.get("seasons", []):
                    if season["name"].lower() == season_name.lower():
                        for quality in season.get("qualities", []):
                            if quality["name"].lower() == quality_name.lower():
                                return quality.get("link_key")
    return None

def delete_quality(series_key, language_name, season_name, quality_name):
    """Deletes a quality from a specific season."""
    series = get_series_by_key(series_key)
    if not series:
        return False
    
    languages = series.get("languages", [])
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            seasons = lang.get("seasons", [])
            for season in seasons:
                if season["name"].lower() == season_name.lower():
                    qualities = season.get("qualities", [])
                    updated_qualities = [quality for quality in qualities if quality["name"].lower() != quality_name.lower()]
                    season["qualities"] = updated_qualities
                    series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
                    return len(qualities) != len(updated_qualities) # True if something was deleted
            lang["seasons"] = seasons
            break
    return False

def get_poster_file_id(series_key, language_name=None, season_name=None):
    """Retrieves the poster file_id for a series, language, or season."""
    series = get_series_by_key(series_key)
    if not series:
        return None
    
    if language_name is None and season_name is None:
        return series.get("poster_file_id")
    
    if language_name:
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                if season_name is None:
                    return lang.get("poster_file_id")
                else:
                    for season in lang.get("seasons", []):
                        if season["name"].lower() == season_name.lower():
                            return season.get("poster_file_id")
    return None

def update_poster_file_id(series_key, file_id, language_name=None, season_name=None):
    """Updates the poster file_id for a series, language, or season."""
    series = get_series_by_key(series_key)
    if not series:
        return False
    
    if language_name is None and season_name is None:
        series_collection.update_one({"_id": series_key}, {"$set": {"poster_file_id": file_id}})
        return True
    
    languages = series.get("languages", [])
    for lang in languages:
        if lang["name"].lower() == language_name.lower():
            if season_name is None:
                lang["poster_file_id"] = file_id
                series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
                return True
            else:
                seasons = lang.get("seasons", [])
                for season in seasons:
                    if season["name"].lower() == season_name.lower():
                        season["poster_file_id"] = file_id
                        series_collection.update_one({"_id": series_key}, {"$set": {"languages": languages}})
                        return True
    return False

def publish_series(series_key):
    """Sets the series as published and removes empty groups."""
    series = get_series_by_key(series_key)
    if not series:
        return False

    # Clean up empty languages, seasons, qualities
    cleaned_languages = []
    for lang in series.get("languages", []):
        cleaned_seasons = []
        for season in lang.get("seasons", []):
            cleaned_qualities = [q for q in season.get("qualities", []) if q.get("link_key")]
            if cleaned_qualities:
                season["qualities"] = cleaned_qualities
                cleaned_seasons.append(season)
        if cleaned_seasons:
            lang["seasons"] = cleaned_seasons
            cleaned_languages.append(lang)
    
    series["languages"] = cleaned_languages
    series["published"] = True
    
    series_collection.update_one({"_id": series_key}, {"$set": series})
    return True
