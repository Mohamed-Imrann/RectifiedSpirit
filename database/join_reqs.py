
# database/join_reqs.py

import motor.motor_asyncio
from info import REQ_CHANNEL_ONE, REQ_CHANNEL_TWO, DATABASE_URI
from database.postgres import pgDb


class JoinReqs:
    def __init__(self):
        if DATABASE_URI:
            self.client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URI)
            self.db = self.client["JoinReqs"]
            self.col1 = self.db[str(REQ_CHANNEL_ONE)]
            self.col2 = self.db[str(REQ_CHANNEL_TWO)]
            self.chat_col1 = self.db["ChatId1"]
            self.chat_col2 = self.db["ChatId2"]
        else:
            self.client = None
            self.db = None

    async def add_fsub_chat1(self, chat_id):
        try:
            # Mongo first
            await self.chat_col1.delete_many({})
            await self.chat_col1.insert_one({"chat_id": int(chat_id)})
            # then PG
            await pgDb.set_fsub_chat(1, int(chat_id))
        except:
            pass

    async def get_fsub_chat1(self):
        # PG first
        row = await pgDb.get_fsub_chat(1)
        if row:
            return row
        # fallback mongo + self-heal
        doc = await self.chat_col1.find_one({})
        if doc and "chat_id" in doc:
            await pgDb.set_fsub_chat(1, int(doc["chat_id"]))
        return doc

    async def delete_fsub_chat1(self, chat_id):
        # Mongo first
        await self.chat_col1.delete_one({"chat_id": int(chat_id)})
        # then PG
        await pgDb.delete_fsub_chat(1, int(chat_id))

    async def add_fsub_chat2(self, chat_id):
        try:
            # Mongo first
            await self.chat_col2.delete_many({})
            await self.chat_col2.insert_one({"chat_id": int(chat_id)})
            # then PG
            await pgDb.set_fsub_chat(2, int(chat_id))
        except:
            pass

    async def get_fsub_chat2(self):
        # PG first
        row = await pgDb.get_fsub_chat(2)
        if row:
            return row
        # fallback mongo + self-heal
        doc = await self.chat_col2.find_one({})
        if doc and "chat_id" in doc:
            await pgDb.set_fsub_chat(2, int(doc["chat_id"]))
        return doc

    async def delete_fsub_chat2(self, chat_id):
        # Mongo first
        await self.chat_col2.delete_one({"chat_id": int(chat_id)})
        # then PG
        await pgDb.delete_fsub_chat(2, int(chat_id))
