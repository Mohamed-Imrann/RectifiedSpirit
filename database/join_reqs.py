import motor.motor_asyncio
from info import REQ_CHANNEL_ONE, REQ_CHANNEL_TWO

class JoinReqs:
    def __init__(self):
        from info import DATABASE_URL
        if DATABASE_URL:
            self.client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URL)
            self.db = self.client["JoinReqs"]
            self.col1 = self.db[str(REQ_CHANNEL_ONE)]
            self.col2 = self.db[str(REQ_CHANNEL_TWO)]
            self.chat_col1 = self.db["ChatId1"]
            self.chat_col2 = self.db["ChatId2"]
        else:
            self.client = None
            self.db = None
            self.col = None
    ##############################################
    async def add_fsub_chat1(self, chat_id):
        try:
            await self.chat_col1.delete_many({})
            await self.chat_col1.insert_one({"chat_id": chat_id})
        except:
            pass
    async def get_fsub_chat1(self):
        return await self.chat_col1.find_one({})
    async def delete_fsub_chat1(self, chat_id):
        await self.chat_col1.delete_one({"chat_id": chat_id})
    ##############################################
    async def add_fsub_chat2(self, chat_id):
        try:
            await self.chat_col2.delete_many({})
            await self.chat_col2.insert_one({"chat_id": chat_id})
        except:
            pass
    async def get_fsub_chat2(self):
        return await self.chat_col2.find_one({})
    async def delete_fsub_chat2(self, chat_id):
        await self.chat_col2.delete_one({"chat_id": chat_id})
    ##############################################
from database.users_chats_db import db  # your existing db import

class JoinReqs:
    def __init__(self):
        self.col = db["join_reqs"]

    # chat1
    async def set_fsub_chat1(self, chat_id: int):
        await self.col.update_one({"_id": "fsub_chat1"}, {"$set": {"chat_id": chat_id}}, upsert=True)

    async def get_fsub_chat1(self):
        return await self.col.find_one({"_id": "fsub_chat1"})

    # chat2
    async def set_fsub_chat2(self, chat_id: int):
        await self.col.update_one({"_id": "fsub_chat2"}, {"$set": {"chat_id": chat_id}}, upsert=True)

    async def get_fsub_chat2(self):
        return await self.col.find_one({"_id": "fsub_chat2"})

    # chat3 ✅ NEW
    async def set_fsub_chat3(self, chat_id: int):
        await self.col.update_one({"_id": "fsub_chat3"}, {"$set": {"chat_id": chat_id}}, upsert=True)

    async def get_fsub_chat3(self):
        return await self.col.find_one({"_id": "fsub_chat3"})
