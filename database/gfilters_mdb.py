import motor.motor_asyncio
from info import DATABASE_NAME, DATABASE_URL
from pyrogram import enums
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

class GFiltersDB:
    def __init__(self):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URL)
        self.db = self.client[DATABASE_NAME]
        self.gfilters_collection = self.db.global_filters

    async def add_gfilter(self, chat_id, keyword):
        await self.gfilters_collection.update_one(
            {"_id": chat_id},
            {"$addToSet": {"keywords": keyword}},
            upsert=True
        )

    async def get_gfilters(self, chat_id):
        data = await self.gfilters_collection.find_one({"_id": chat_id})
        return data.get("keywords", []) if data else []

    async def find_gfilter(self, chat_id, keyword):
        data = await self.gfilters_collection.find_one({"_id": chat_id})
        keywords = data.get("keywords", []) if data else []
        if keyword in keywords:
            return True
        return False

    async def delete_gfilter(self, chat_id, keyword):
        await self.gfilters_collection.update_one(
            {"_id": chat_id},
            {"$pull": {"keywords": keyword}}
        )

    async def del_allg(self, chat_id):
        await self.gfilters_collection.delete_one({"_id": chat_id})

    async def count_gfilters(self, chat_id):
        data = await self.gfilters_collection.find_one({"_id": chat_id})
        return len(data.get("keywords", [])) if data else 0

    async def gfilter_stats(self):
        totalcollections = 0
        totalcount = 0
        async for document in self.gfilters_collection.find():
            totalcollections += 1
            totalcount += len(document.get("keywords", []))
        return totalcollections, totalcount

gfilters_db = GFiltersDB()
