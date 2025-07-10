import motor.motor_asyncio
from info import DATABASE_NAME, DATABASE_URI

class UsersChatsDB:
    def __init__(self):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URI)
        self.db = self.client[DATABASE_NAME]
        self.users_collection = self.db.users
        self.chats_collection = self.db.chats

    async def add_user(self, user_id, username, first_name):
        await self.users_collection.update_one(
            {"_id": user_id},
            {"$set": {"username": username, "first_name": first_name}},
            upsert=True
        )

    async def get_user(self, user_id):
        return await self.users_collection.find_one({"_id": user_id})

    async def add_chat(self, chat_id, chat_name):
        await self.chats_collection.update_one(
            {"_id": chat_id},
            {"$set": {"chat_name": chat_name}},
            upsert=True
        )

    async def get_chat(self, chat_id):
        return await self.chats_collection.find_one({"_id": chat_id})

    async def remove_ban(self, user_id):
        ban_status = dict(
            is_banned=False,
            ban_reason=''
        )
        await self.users_collection.update_one({'_id': user_id}, {'$set': {'ban_status': ban_status}})
    
    async def ban_user(self, user_id, ban_reason="No Reason"):
        ban_status = dict(
            is_banned=True,
            ban_reason=ban_reason
        )
        await self.users_collection.update_one({'_id': user_id}, {'$set': {'ban_status': ban_status}})

    async def get_ban_status(self, user_id):
        default = dict(
            is_banned=False,
            ban_reason=''
        )
        user = await self.users_collection.find_one({'_id': user_id})
        if not user:
            return default
        return user.get('ban_status', default)

    async def get_all_users(self):
        return self.users_collection.find({})
    
    async def delete_user(self, user_id):
        await self.users_collection.delete_many({'_id': user_id})

    async def delete_chat(self, chat_id):
        await self.chats_collection.delete_many({'_id': chat_id})

    async def get_banned(self):
        users = self.users_collection.find({'ban_status.is_banned': True})
        chats = self.chats_collection.find({'chat_status.is_disabled': True})
        b_chats = [chat['_id'] async for chat in chats]
        b_users = [user['_id'] async for user in users]
        return b_users, b_chats

    async def re_enable_chat(self, chat_id):
        chat_status=dict(
            is_disabled=False,
            reason="",
            )
        await self.chats_collection.update_one({'_id': chat_id}, {'$set': {'chat_status': chat_status}})
        
    async def update_settings(self, chat_id, settings):
        await self.chats_collection.update_one({'_id': chat_id}, {'$set': {'settings': settings}})

    async def get_settings(self, chat_id):
        default = {
            'button': True,
            'botpm': True,
            'file_secure': False,
            'imdb': True,
            'spell_check': True,
            'welcome': False,
        }
        chat = await self.chats_collection.find_one({'_id': chat_id})
        if chat:
            return chat.get('settings', default)
        return default    

    async def disable_chat(self, chat_id, reason="No Reason"):
        chat_status=dict(
            is_disabled=True,
            reason=reason,
            )
        await self.chats_collection.update_one({'_id': chat_id}, {'$set': {'chat_status': chat_status}})    

    async def total_chat_count(self):
        count = await self.chats_collection.count_documents({})
        return count

    async def get_all_chats(self):
        return self.chats_collection.find({})

    async def get_db_size(self):
        return (await self.db.command("dbstats"))['dataSize']

db = UsersChatsDB()
