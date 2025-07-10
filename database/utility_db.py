from pymongo import MongoClient
from info import DATABASE_URI

client = MongoClient(DATABASE_URI)
temp_data_collection = client['series_database']['temp_series_data']

class UtilityDB:
    def __init__(self):
        self.collection = temp_data_collection

    async def get_temp_series_data(self, user_id: int):
        return await self.collection.find_one({"_id": user_id})

    async def update_temp_series_data(self, user_id: int, series_data: dict):
        await self.collection.update_one(
            {"_id": user_id},
            {"$set": {"series_data": series_data}},
            upsert=True
        )

    async def delete_temp_language(self, user_id: int, language: str):
        await self.collection.update_one(
            {"_id": user_id},
            {"$pull": {"series_data.languages": language}}
        )
        # Also remove any seasons/qualities associated with this language
        # This requires iterating through seasons and qualities to remove keys dynamically
        # For simplicity, we'll just remove the language from the list.
        # A more robust solution might involve re-fetching and rebuilding the structure.
        
        # To remove seasons associated with the language, we need to unset specific fields
        # This is a more complex operation if the structure is deeply nested.
        # For now, we assume languages are top-level and seasons are nested under them.
        # If seasons are stored as `series_data.seasons.<language_key>.<season_name>`,
        # then we need to remove all keys starting with `series_data.seasons.<language_key>`.
        # This is not directly supported by $unset for dynamic keys.
        # A simpler approach for temporary data might be to rebuild the series_data.
        
        # Let's assume the structure is:
        # {
        #   "_id": user_id,
        #   "series_data": {
        #     "languages": ["English", "Hindi"],
        #     "seasons": {
        #       "English": { "Season 1": { "480p": "link", "720p": "link" } },
        #       "Hindi": { "Season 1": { "480p": "link" } }
        #     }
        #   }
        # }
        # If 'English' is deleted, we need to remove 'English' from 'languages' array
        # AND remove the 'English' key from 'seasons' object.
        
        # Fetch current data
        current_data = await self.collection.find_one({"_id": user_id})
        if current_data and "series_data" in current_data and "seasons" in current_data["series_data"]:
            seasons = current_data["series_data"]["seasons"]
            if language in seasons:
                del seasons[language]
                await self.collection.update_one(
                    {"_id": user_id},
                    {"$set": {"series_data.seasons": seasons}}
                )


    async def delete_temp_season(self, user_id: int, language: str, season_name: str):
        await self.collection.update_one(
            {"_id": user_id},
            {"$unset": {f"series_data.seasons.{language}.{season_name}": ""}}
        )

    async def delete_temp_quality(self, user_id: int, language: str, season_name: str, quality: str):
        # This requires fetching the document, modifying the array, and saving it back
        current_data = await self.collection.find_one({"_id": user_id})
        if current_data and "series_data" in current_data and \
           "seasons" in current_data["series_data"] and \
           language in current_data["series_data"]["seasons"] and \
           season_name in current_data["series_data"]["seasons"][language]:
            
            season_data = current_data["series_data"]["seasons"][language][season_name]
            if quality in season_data:
                del season_data[quality]
                await self.collection.update_one(
                    {"_id": user_id},
                    {"$set": {f"series_data.seasons.{language}.{season_name}": season_data}}
                )
