import motor.motor_asyncio
from info import REQ_CHANNEL_ONE, REQ_CHANNEL_TWO, REQ_CHANNEL_THREE

class JoinReqs:
    def __init__(self):
        from info import DATABASE_URL
        if DATABASE_URL:
            self.client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URL)
            self.db = self.client["JoinReqs"]

            # (optional) old collections
            self.col1 = self.db[str(REQ_CHANNEL_ONE)] if REQ_CHANNEL_ONE else self.db["req_col1"]
            self.col2 = self.db[str(REQ_CHANNEL_TWO)] if REQ_CHANNEL_TWO else self.db["req_col2"]
            self.col3 = self.db[str(REQ_CHANNEL_THREE)] if REQ_CHANNEL_THREE else self.db["req_col3"]

            # ✅ chat id storage
            self.chat_col1 = self.db["ChatId1"]
            self.chat_col2 = self.db["ChatId2"]
            self.chat_col3 = self.db["ChatId3"]
        else:
            self.client = None
            self.db = None

    # ---------------- chat1 ----------------
    async def add_fsub_chat1(self, chat_id: int):
        await self.chat_col1.delete_many({})
        await self.chat_col1.insert_one({"chat_id": int(chat_id)})

    async def get_fsub_chat1(self):
        return await self.chat_col1.find_one({})

    async def delete_fsub_chat1(self, chat_id: int):
        await self.chat_col1.delete_one({"chat_id": int(chat_id)})

    # ---------------- chat2 ----------------
    async def add_fsub_chat2(self, chat_id: int):
        await self.chat_col2.delete_many({})
        await self.chat_col2.insert_one({"chat_id": int(chat_id)})

    async def get_fsub_chat2(self):
        return await self.chat_col2.find_one({})

    async def delete_fsub_chat2(self, chat_id: int):
        await self.chat_col2.delete_one({"chat_id": int(chat_id)})

    # ---------------- chat3 ✅ ----------------
    async def add_fsub_chat3(self, chat_id: int):
        await self.chat_col3.delete_many({})
        await self.chat_col3.insert_one({"chat_id": int(chat_id)})

    async def get_fsub_chat3(self):
        return await self.chat_col3.find_one({})

    async def delete_fsub_chat3(self, chat_id: int):
        await self.chat_col3.delete_one({"chat_id": int(chat_id)})
