from motor.motor_asyncio import AsyncIOMotorClient
import logging
from info import DATABASE_URI, DATABASE_NAME, COLLECTION_NAME

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class CrazyDB:
    def __init__(self, uri, db_name, collection_name):
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]

    async def add_series(self, series_data):
        """Adds a new series document. Returns True on success, False on duplicate key error."""
        try:
            # Ensure '_id' is unique
            if await self.collection.find_one({"_id": series_data["_id"]}): # Use _id as the primary key
                logger.warning(f"Series with _id '{series_data.get('_id', 'N/A')}' already exists. Skipping insertion.")
                return False
            await self.collection.insert_one(series_data)
            logger.info(f"Series '{series_data.get('title', 'N/A')}' added successfully.")
            return True
        except Exception as e:
            logger.error(f"Error adding series '{series_data.get('title', 'N/A')}': {e}")
            return False

    async def get_series_by_key(self, key):
        """Retrieves a single series document by its key (which is _id)."""
        return await self.collection.find_one({"_id": key})

    async def get_series_by_title(self, title):
        """Case-insensitive search for series by title."""
        return await self.collection.find_one({"title": {"$regex": title, "$options": "i"}})

    async def update_series(self, key, new_data):
        """Updates a series document."""
        try:
            result = await self.collection.update_one({"_id": key}, {"$set": new_data})
            if result.modified_count > 0:
                logger.info(f"Series '{key}' updated successfully.")
                return True
            else:
                logger.warning(f"Series '{key}' not found or no changes made during update.")
                return False
        except Exception as e:
            logger.error(f"Error updating series '{key}': {e}")
            return False

    async def delete_series(self, key):
        """Deletes a series document."""
        try:
            result = await self.collection.delete_one({"_id": key})
            if result.deleted_count > 0:
                logger.info(f"Series '{key}' deleted successfully.")
            else:
                logger.warning(f"Series '{key}' not found.")
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting series '{key}': {e}")
            return False

    async def get_all_series_keys(self):
        """Returns a list of all series _id (keys)."""
        cursor = self.collection.find({}, {"_id": 1})
        keys = [doc["_id"] async for doc in cursor]
        return keys

    async def get_all_series_titles(self):
        """Returns a list of all series titles."""
        cursor = self.collection.find({}, {"title": 1, "_id": 0})
        titles = [doc["title"] async for doc in cursor]
        return titles

    async def get_all_series(self):
        """Returns all series data."""
        cursor = self.collection.find({})
        return [doc async for doc in cursor]

    async def add_or_update_language(self, series_key, language_name, poster_file_id=None):
        """Adds a new language or updates its poster for a series."""
        series = await self.get_series_by_key(series_key)
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
        
        return await self.update_series(series_key, {"languages": languages})

    async def get_languages(self, series_key):
        """Returns a list of language names for a series."""
        series = await self.get_series_by_key(series_key)
        return series.get("languages", []) if series else []

    async def delete_language(self, series_key, language_name):
        """Deletes a language and all its nested data from a series."""
        series = await self.get_series_by_key(series_key)
        if not series:
            return False
        
        languages = series.get("languages", [])
        updated_languages = [lang for lang in languages if lang["name"].lower() != language_name.lower()]
        
        return await self.update_series(series_key, {"languages": updated_languages})

    async def add_or_update_season(self, series_key, language_name, season_name, poster_file_id=None):
        """Adds a new season or updates its poster for a specific language."""
        series = await self.get_series_by_key(series_key)
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
        
        return await self.update_series(series_key, {"languages": languages})

    async def get_seasons(self, series_key, language_name):
        """Returns a list of season names for a specific language."""
        series = await self.get_series_by_key(series_key)
        if series:
            for lang in series.get("languages", []):
                if lang["name"].lower() == language_name.lower():
                    return lang.get("seasons", [])
        return []

    async def delete_season(self, series_key, language_name, season_name):
        """Deletes a season and all its nested data from a specific language."""
        series = await self.get_series_by_key(series_key)
        if not series:
            return False
        
        languages = series.get("languages", [])
        for lang in languages:
            if lang["name"].lower() == language_name.lower():
                seasons = lang.get("seasons", [])
                updated_seasons = [season for season in seasons if season["name"].lower() != season_name.lower()]
                lang["seasons"] = updated_seasons
                return await self.update_series(series_key, {"languages": languages})
        return False

    async def add_or_update_quality(self, series_key, language_name, season_name, quality_name, link_key, codec=None):
        """Adds a new quality or updates its link/codec for a specific season."""
        series = await self.get_series_by_key(series_key)
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
        
        return await self.update_series(series_key, {"languages": languages})

    async def get_qualities(self, series_key, language_name, season_name):
        """Returns a list of quality names for a specific season."""
        series = await self.get_series_by_key(series_key)
        if series:
            for lang in series.get("languages", []):
                if lang["name"].lower() == language_name.lower():
                    for season in lang.get("seasons", []):
                        if season["name"].lower() == season_name.lower():
                            return season.get("qualities", [])
        return []

    async def get_quality_link(self, series_key, language_name, season_name, quality_name):
        """Returns the link_key for a specific quality."""
        series = await self.get_series_by_key(series_key)
        if series:
            for lang in series.get("languages", []):
                if lang["name"].lower() == language_name.lower():
                    for season in lang.get("seasons", []):
                        if season["name"].lower() == season_name.lower():
                            for quality in season.get("qualities", []):
                                if quality["name"].lower() == quality_name.lower():
                                    return quality.get("link_key")
        return None

    async def delete_quality(self, series_key, language_name, season_name, quality_name):
        """Deletes a quality from a specific season."""
        series = await self.get_series_by_key(series_key)
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
                        return await self.update_series(series_key, {"languages": languages})
                lang["seasons"] = seasons
                break
        return False

    async def get_poster_file_id(self, series_key):
        """
        Retrieves the poster file ID or URL for a given series key.
        Assumes the 'poster_file_id' field in the series document can store either.
        """
        series = await self.get_series_by_key(series_key)
        return series.get("poster_file_id") if series else None

    async def update_poster_file_id(self, series_key, file_id):
        """Updates the poster file_id for a series."""
        return await self.update_series(series_key, {"poster_file_id": file_id})

    async def publish_series(self, series_key):
        """Sets the series as published and removes empty groups."""
        series = await self.get_series_by_key(series_key)
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
        
        return await self.update_series(series_key, series)

    async def get_specific_poster(self, series_key, language_name=None, season_name=None):
        series = await self.get_series_by_key(series_key)
        if not series:
            return None

        # Check for season-specific poster
        if language_name and season_name:
            for lang in series.get("languages", []):
                if lang["name"].lower() == language_name.lower():
                    for season in lang.get("seasons", []):
                        if season["name"].lower() == season_name.lower():
                            if season.get("poster_file_id"):
                                return season["poster_file_id"]

        # Check for language-specific poster
        if language_name:
            for lang in series.get("languages", []):
                if lang["name"].lower() == language_name.lower():
                    if lang.get("poster_file_id"):
                        return lang["poster_file_id"]
        
        # Fallback to series-level poster
        return series.get("poster_file_id")

crazy_db = CrazyDB(DATABASE_URI, DATABASE_NAME, COLLECTION_NAME)

# Helper functions for direct access
async def add_series(series_data):
    return await crazy_db.add_series(series_data)

async def get_series_by_key(key):
    return await crazy_db.get_series_by_key(key)

async def get_series_by_title(title):
    return await crazy_db.get_series_by_title(title)

async def update_series(key, new_data):
    return await crazy_db.update_series(key, new_data)

async def delete_series(key):
    return await crazy_db.delete_series(key)

async def get_all_series_keys():
    return await crazy_db.get_all_series_keys()

async def get_all_series_titles():
    return await crazy_db.get_all_series_titles()

async def get_all_series():
    return await crazy_db.get_all_series()

async def get_languages(series_key):
    return await crazy_db.get_languages(series_key)

async def delete_language(series_key, language_name):
    return await crazy_db.delete_language(series_key, language_name)

async def add_or_update_season(series_key, language_name, season_name, poster_file_id=None):
    return await crazy_db.add_or_update_season(series_key, language_name, season_name, poster_file_id)

async def get_seasons(series_key, language_name):
    return await crazy_db.get_seasons(series_key, language_name)

async def delete_season(series_key, language_name, season_name):
    return await crazy_db.delete_season(series_key, language_name, season_name)

async def add_or_update_quality(series_key, language_name, season_name, quality_name, link_key, codec=None):
    return await crazy_db.add_or_update_quality(series_key, language_name, season_name, quality_name, link_key, codec)

async def get_qualities(series_key, language_name, season_name):
    return await crazy_db.get_qualities(series_key, language_name, season_name)

async def get_quality_link(series_key, language_name, season_name, quality_name):
    return await crazy_db.get_quality_link(series_key, language_name, season_name, quality_name)

async def delete_quality(series_key, language_name, season_name, quality_name):
    return await crazy_db.delete_quality(series_key, language_name, season_name, quality_name)

async def get_poster_file_id(series_key):
    return await crazy_db.get_poster_file_id(series_key)

async def update_poster_file_id(series_key, file_id):
    return await crazy_db.update_poster_file_id(series_key, file_id)

async def publish_series(series_key):
    return await crazy_db.publish_series(series_key)

async def get_specific_poster(series_key, language_name=None, season_name=None):
    return await crazy_db.get_specific_poster(series_key, language_name, season_name)
