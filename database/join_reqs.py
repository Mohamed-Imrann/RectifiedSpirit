import motor.motor_asyncio
from info import REQ_CHANNEL_ONE, REQ_CHANNEL_TWO

class JoinReqs:
    def __init__(self):
        from info import DATABASE_URI
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