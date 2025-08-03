import motor.motor_asyncio
import re
from info import DATABASE_NAME, DATABASE_URL

class Database:
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users
        self.grp = self.db.groups
        self.gfilters = self.db.gfilters
        self.series_collection = self.db.series # New collection for series data

    def new_user(self, id, name):
        return dict(
            id=id,
            name=name,
            ban_status=dict(
                is_banned=False,
                ban_reason="",
            ),
        )

    def new_group(self, id, title):
        return dict(
            id=id,
            title=title,
            chat_status=dict(
                is_disabled=False,
                reason="",
            ),
        )

    async def add_user(self, id, name):
        user = self.new_user(id, name)
        await self.col.insert_one(user)

    async def add_group(self, id, title):
        group = self.new_group(id, title)
        await self.grp.insert_one(group)

    async def get_user(self, id):
        user = await self.col.find_one({"id": id})
        return user

    async def get_group(self, id):
        group = await self.grp.find_one({"id": id})
        return group

    async def get_all_users(self):
        return self.col.find({})

    async def get_all_groups(self):
        return self.grp.find({})

    async def delete_user(self, user_id):
        await self.col.delete_many({"id": user_id})

    async def delete_group(self, id):
        await self.grp.delete_many({"id": id})

    async def get_banned_users(self):
        return self.col.find({"ban_status.is_banned": True})

    async def get_disabled_chats(self):
        return self.grp.find({"chat_status.is_disabled": True})

    async def total_users_count(self):
        count = await self.col.count_documents({})
        return count

    async def total_groups_count(self):
        count = await self.grp.count_documents({})
        return count

    async def update_ban_status(self, user_id, ban_status):
        await self.col.update_one({"id": user_id}, {"$set": {"ban_status": ban_status}})

    async def update_chat_status(self, chat_id, chat_status):
        await self.grp.update_one({"id": chat_id}, {"$set": {"chat_status": chat_status}})

    async def get_gfilters(self, id):
        filters = await self.gfilters.find_one({"_id": id})
        if filters:
            return filters.get("filters", [])
        return []

    async def find_gfilter(self, id, keyword):
        filters = await self.gfilters.find_one({"_id": id})
        if filters:
            for f in filters.get("filters", []):
                if f["keyword"] == keyword:
                    return f["reply_text"], f["btn"], f["alert"], f["fileid"]
        return None, None, None, None

    async def add_gfilter(self, id, keyword, reply_text, btn, alert, fileid):
        await self.gfilters.update_one(
            {"_id": id},
            {"$push": {"filters": {"keyword": keyword, "reply_text": reply_text, "btn": btn, "alert": alert, "fileid": fileid}}},
            upsert=True
        )

    async def delete_gfilter(self, id, keyword):
        await self.gfilters.update_one(
            {"_id": id},
            {"$pull": {"filters": {"keyword": keyword}}}
        )

    # --- Series Management Functions ---

    def add_series(self, series_data: dict):
        """Adds a new series document to the database."""
        try:
            self.series_collection.insert_one(series_data)
            return True
        except Exception as e:
            print(f"Error adding series: {e}")
            return False

    def get_series(self):
        """Retrieves all series documents."""
        return list(self.series_collection.find({}))

    def get_series_by_key(self, series_key: str):
        """Retrieves a single series document by its _id (series_key)."""
        return self.series_collection.find_one({"_id": series_key})

    def update_series_field(self, series_key: str, field: str, value):
        """Updates a top-level field in a series document."""
        self.series_collection.update_one({"_id": series_key}, {"$set": {field: value}})

    def add_or_update_language(self, series_key: str, language_name: str, poster_file_id: str = None):
        """Adds a new language or updates an existing one for a series."""
        series = self.get_series_by_key(series_key)
        if not series:
            return False

        languages = series.get("languages", [])
        existing_lang_index = -1
        for i, lang in enumerate(languages):
            if lang["name"].lower() == language_name.lower():
                existing_lang_index = i
                break

        if existing_lang_index != -1:
            # Update existing language
            if poster_file_id:
                languages[existing_lang_index]["poster_file_id"] = poster_file_id
            self.series_collection.update_one(
                {"_id": series_key},
                {"$set": {"languages": languages}}
            )
        else:
            # Add new language
            new_lang = {"name": language_name, "seasons": []}
            if poster_file_id:
                new_lang["poster_file_id"] = poster_file_id
            self.series_collection.update_one(
                {"_id": series_key},
                {"$push": {"languages": new_lang}}
            )
        return True

    def delete_language(self, series_key: str, language_name: str):
        """Deletes a language from a series."""
        self.series_collection.update_one(
            {"_id": series_key},
            {"$pull": {"languages": {"name": language_name}}}
        )
        return True

    def add_or_update_season(self, series_key: str, language_name: str, season_name: str, poster_file_id: str = None):
        """Adds a new season or updates an existing one for a language within a series."""
        series = self.get_series_by_key(series_key)
        if not series:
            return False

        languages = series.get("languages", [])
        for lang in languages:
            if lang["name"].lower() == language_name.lower():
                seasons = lang.get("seasons", [])
                existing_season_index = -1
                for i, season in enumerate(seasons):
                    if season["name"].lower() == season_name.lower():
                        existing_season_index = i
                        break

                if existing_season_index != -1:
                    # Update existing season
                    if poster_file_id:
                        seasons[existing_season_index]["poster_file_id"] = poster_file_id
                    lang["seasons"] = seasons
                else:
                    # Add new season
                    new_season = {"name": season_name, "qualities": []}
                    if poster_file_id:
                        new_season["poster_file_id"] = poster_file_id
                    seasons.append(new_season)
                    lang["seasons"] = seasons
                
                self.series_collection.update_one(
                    {"_id": series_key},
                    {"$set": {"languages": languages}}
                )
                return True
        return False

    def delete_season(self, series_key: str, language_name: str, season_name: str):
        """Deletes a season from a language within a series."""
        series = self.get_series_by_key(series_key)
        if not series:
            return False

        languages = series.get("languages", [])
        for lang in languages:
            if lang["name"].lower() == language_name.lower():
                lang["seasons"] = [s for s in lang.get("seasons", []) if s["name"].lower() != season_name.lower()]
                self.series_collection.update_one(
                    {"_id": series_key},
                    {"$set": {"languages": languages}}
                )
                return True
        return False

    def add_or_update_quality(self, series_key: str, language_name: str, season_name: str, quality_name: str, link_key: str, codec: str = None):
        """Adds a new quality or updates an existing one for a season within a language."""
        series = self.get_series_by_key(series_key)
        if not series:
            return False

        languages = series.get("languages", [])
        for lang in languages:
            if lang["name"].lower() == language_name.lower():
                seasons = lang.get("seasons", [])
                for season in seasons:
                    if season["name"].lower() == season_name.lower():
                        qualities = season.get("qualities", [])
                        existing_quality_index = -1
                        for i, quality in enumerate(qualities):
                            if quality["name"].lower() == quality_name.lower():
                                existing_quality_index = i
                                break

                        if existing_quality_index != -1:
                            # Update existing quality
                            qualities[existing_quality_index]["link_key"] = link_key
                            if codec:
                                qualities[existing_quality_index]["codec"] = codec
                            season["qualities"] = qualities
                        else:
                            # Add new quality
                            new_quality = {"name": quality_name, "link_key": link_key}
                            if codec:
                                new_quality["codec"] = codec
                            qualities.append(new_quality)
                            season["qualities"] = qualities
                        
                        self.series_collection.update_one(
                            {"_id": series_key},
                            {"$set": {"languages": languages}}
                        )
                        return True
        return False

    def delete_quality(self, series_key: str, language_name: str, season_name: str, quality_name: str):
        """Deletes a quality from a season within a language."""
        series = self.get_series_by_key(series_key)
        if not series:
            return False

        languages = series.get("languages", [])
        for lang in languages:
            if lang["name"].lower() == language_name.lower():
                seasons = lang.get("seasons", [])
                for season in seasons:
                    if season["name"].lower() == season_name.lower():
                        season["qualities"] = [q for q in season.get("qualities", []) if q["name"].lower() != quality_name.lower()]
                        self.series_collection.update_one(
                            {"_id": series_key},
                            {"$set": {"languages": languages}}
                        )
                        return True
        return False

    def get_poster_file_id(self, series_key: str):
        """Retrieves the main poster file_id for a series."""
        series = self.get_series_by_key(series_key)
        return series.get("poster_file_id") if series else None

    def update_poster_file_id(self, series_key: str, file_id: str):
        """Updates the main poster file_id for a series."""
        self.series_collection.update_one({"_id": series_key}, {"$set": {"poster_file_id": file_id}})

    def publish_series(self, series_key: str):
        """
        Publishes a series, setting its 'published' status to True
        and removing any empty language, season, or quality groups.
        """
        series = self.get_series_by_key(series_key)
        if not series:
            return False

        # Deep copy to modify
        cleaned_series = series.copy()
        
        # Clean languages
        cleaned_languages = []
        for lang in cleaned_series.get("languages", []):
            cleaned_seasons = []
            for season in lang.get("seasons", []):
                cleaned_qualities = [q for q in season.get("qualities", []) if q.get("link_key") and q.get("link_key") != "PENDING_LINK"]
                if cleaned_qualities:
                    season["qualities"] = cleaned_qualities
                    cleaned_seasons.append(season)
            if cleaned_seasons:
                lang["seasons"] = cleaned_seasons
                cleaned_languages.append(lang)
        
        cleaned_series["languages"] = cleaned_languages
        cleaned_series["published"] = True

        # Update the document in the database
        self.series_collection.replace_one({"_id": series_key}, cleaned_series)
        return True

    async def search_published_series(self, query: str, limit: int = 10):
        """
        Searches for published series by title or key using regex for partial matching.
        Returns a list of matching series documents.
        """
        try:
            # Create a case-insensitive regex pattern for the query
            regex_pattern = f".*{re.escape(query)}.*"
            
            # Search criteria: published is True AND (title matches OR _id matches)
            search_criteria = {
                "published": True,
                "$or": [
                    {"title": {"$regex": regex_pattern, "$options": "i"}},
                    {"_id": {"$regex": regex_pattern, "$options": "i"}}
                ]
            }
            
            # Execute the search and return results as a list
            cursor = self.series_collection.find(search_criteria).limit(limit)
            results = []
            async for document in cursor:
                results.append(document)
            return results
        except Exception as e:
            print(f"Error in search_published_series: {e}")
            return []

    def get_languages(self, series_key: str):
        """Get all languages for a series."""
        series = self.get_series_by_key(series_key)
        return series.get("languages", []) if series else []

    def get_seasons(self, series_key: str, language_name: str):
        """Get all seasons for a specific language in a series."""
        series = self.get_series_by_key(series_key)
        if not series:
            return []
        
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                return lang.get("seasons", [])
        return []

    def get_qualities(self, series_key: str, language_name: str, season_name: str):
        """Get all qualities for a specific season in a language."""
        series = self.get_series_by_key(series_key)
        if not series:
            return []
        
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                for season in lang.get("seasons", []):
                    if season["name"].lower() == season_name.lower():
                        return season.get("qualities", [])
        return []

    def get_quality_link(self, series_key: str, language_name: str, season_name: str, quality_name: str):
        """Get the link_key for a specific quality."""
        series = self.get_series_by_key(series_key)
        if not series:
            return None
        
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                for season in lang.get("seasons", []):
                    if season["name"].lower() == season_name.lower():
                        for quality in season.get("qualities", []):
                            if quality["name"].lower() == quality_name.lower():
                                return quality.get("link_key")
        return None

    def get_specific_poster(self, series_key: str, language_name: str = None, season_name: str = None):
        """Get poster for series, language, or season."""
        series = self.get_series_by_key(series_key)
        if not series:
            return None
        
        if not language_name:
            return series.get("poster_file_id")
        
        for lang in series.get("languages", []):
            if lang["name"].lower() == language_name.lower():
                if not season_name:
                    return lang.get("poster_file_id")
                
                for season in lang.get("seasons", []):
                    if season["name"].lower() == season_name.lower():
                        return season.get("poster_file_id")
        return None


db = Database(DATABASE_URL, DATABASE_NAME)

# Convenience functions for backward compatibility
def add_series(series_data):
    return db.add_series(series_data)

def get_series():
    return db.get_series()

def get_series_by_key(series_key):
    return db.get_series_by_key(series_key)

def update_series_field(series_key, field, value):
    return db.update_series_field(series_key, field, value)

def add_or_update_language(series_key, language_name, poster_file_id=None):
    return db.add_or_update_language(series_key, language_name, poster_file_id)

def get_languages(series_key):
    return db.get_languages(series_key)

def delete_language(series_key, language_name):
    return db.delete_language(series_key, language_name)

def add_or_update_season(series_key, language_name, season_name, poster_file_id=None):
    return db.add_or_update_season(series_key, language_name, season_name, poster_file_id)

def get_seasons(series_key, language_name):
    return db.get_seasons(series_key, language_name)

def delete_season(series_key, language_name, season_name):
    return db.delete_season(series_key, language_name, season_name)

def add_or_update_quality(series_key, language_name, season_name, quality_name, link_key, codec=None):
    return db.add_or_update_quality(series_key, language_name, season_name, quality_name, link_key, codec)

def get_qualities(series_key, language_name, season_name):
    return db.get_qualities(series_key, language_name, season_name)

def get_quality_link(series_key, language_name, season_name, quality_name):
    return db.get_quality_link(series_key, language_name, season_name, quality_name)

def delete_quality(series_key, language_name, season_name, quality_name):
    return db.delete_quality(series_key, language_name, season_name, quality_name)

def get_poster_file_id(series_key):
    return db.get_poster_file_id(series_key)

def update_poster_file_id(series_key, file_id):
    return db.update_poster_file_id(series_key, file_id)

def publish_series(series_key):
    return db.publish_series(series_key)

async def search_published_series(query, limit=10):
    return await db.search_published_series(query, limit)

def get_specific_poster(series_key, language_name=None, season_name=None):
    return db.get_specific_poster(series_key, language_name, season_name)
