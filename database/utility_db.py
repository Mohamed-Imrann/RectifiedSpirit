import motor.motor_asyncio
from info import DATABASE_NAME, DATABASE_URL

class UtilityDB:
    def __init__(self):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URL)
        self.db = self.client[DATABASE_NAME]
        self.temp_series_collection = self.db.temp_series

    async def get_temp_series(self, user_id):
        return await self.temp_series_collection.find_one({"_id": user_id})

    async def update_temp_series(self, user_id, data):
        await self.temp_series_collection.update_one(
            {"_id": user_id},
            {"$set": data},
            upsert=True
        )

    async def delete_temp_language(self, user_id, language_to_delete):
        await self.temp_series_collection.update_one(
            {"_id": user_id},
            {"$pull": {"languages": language_to_delete}}
        )

    async def delete_temp_season(self, user_id, season_to_delete):
        await self.temp_series_collection.update_one(
            {"_id": user_id},
            {"$pull": {"seasons": season_to_delete}}
        )

    async def delete_temp_quality(self, user_id, quality_to_delete):
        await self.temp_series_collection.update_one(
            {"_id": user_id},
            {"$pull": {"qualities": quality_to_delete}}
        )

    async def clear_temp_series(self, user_id):
        await self.temp_series_collection.delete_one({"_id": user_id})

utility_db = UtilityDB()
