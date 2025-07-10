import motor.motor_asyncio
from info import DATABASE_NAME, DATABASE_URI, REQ_CHANNEL_ONE, REQ_CHANNEL_TWO

class JoinReqs:
    def __init__(self):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URI)
        self.db = self.client[DATABASE_NAME]
        self.join_reqs_collection = self.db.join_requests
        self.col1 = self.db[str(REQ_CHANNEL_ONE)]
        self.col2 = self.db[str(REQ_CHANNEL_TWO)]
        self.chat_col1 = self.db["ChatId1"]
        self.chat_col2 = self.db["ChatId2"]

    async def add_join_request(self, chat_id, user_id):
        await self.join_reqs_collection.update_one(
            {"_id": chat_id},
            {"$addToSet": {"users": user_id}},
            upsert=True
        )

    async def get_join_requests(self, chat_id):
        data = await self.join_reqs_collection.find_one({"_id": chat_id})
        return data.get("users", []) if data else []

    async def add_fsub_chat1(self, chat_id):
        try:
            await self.chat_col1.delete_many({})
            await self.chat_col1.insert_one({"chat_id": chat_id})
        except:
            pass

    async def get_fsub_chat1(self):
        # Placeholder for getting force sub channel 1 from DB if not in env
        return {"chat_id": -1001234567890} # Example ID

    async def delete_fsub_chat1(self, chat_id):
        await self.chat_col1.delete_one({"chat_id": chat_id})

    async def add_fsub_chat2(self, chat_id):
        try:
            await self.chat_col2.delete_many({})
            await self.chat_col2.insert_one({"chat_id": chat_id})
        except:
            pass

    async def get_fsub_chat2(self):
        # Placeholder for getting force sub channel 2 from DB if not in env
        return {"chat_id": -1009876543210} # Example ID

    async def delete_fsub_chat2(self, chat_id):
        await self.chat_col2.delete_one({"chat_id": chat_id})

join_reqs_db = JoinReqs()
