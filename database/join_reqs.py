import motor.motor_asyncio
from info import REQ_CHANNEL_ONE, REQ_CHANNEL_TWO, REQ_CHANNEL_THREE

class JoinReqs:
    def __init__(self):
        from info import DATABASE_URL
        if DATABASE_URL:
            self.client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URL)
            self.db = self.client["JoinReqs"]

            # These are your join request collections (if you use them)
            self.col1 = self.db[str(REQ_CHANNEL_ONE)]
            self.col2 = self.db[str(REQ_CHANNEL_TWO)]
            self.col3 = self.db[str(REQ_CHANNEL_THREE)] if REQ_CHANNEL_THREE else None

            # Stores channel IDs for /setchat commands
            self.chat_col1 = self.db["ChatId1"]
            self.chat_col2 = self.db["ChatId2"]
            self.chat_col3 = self.db["ChatId3"]   # ✅ NEW
        else:
            self.client = None
            self.db = None
            self.col1 = None
            self.col2 = None
            self.col3 = None
            self.chat_col1 = None
            self.chat_col2 = None
            self.chat_col3 = None

    ##############################################
    # CHAT 1
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
    # CHAT 2
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
    # CHAT 3 ✅ NEW
    ##############################################
    async def add_fsub_chat3(self, chat_id):
        try:
            await self.chat_col3.delete_many({})
            await self.chat_col3.insert_one({"chat_id": chat_id})
        except:
            pass

    async def get_fsub_chat3(self):
        return await self.chat_col3.find_one({})

    async def delete_fsub_chat3(self, chat_id):
        await self.chat_col3.delete_one({"chat_id": chat_id})
