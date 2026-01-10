# database/users_chats_db.py

import motor.motor_asyncio
from info import DATABASE_NAME, DATABASE_URI
from database.postgres import pgDb


class Database:
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users
        self.grp = self.db.groups

    def new_user(self, id, name):
        return dict(
            id=id,
            name=name,
            ban_status=dict(is_banned=False, ban_reason=""),
        )

    def new_group(self, id, title):
        return dict(
            id=id,
            title=title,
            chat_status=dict(is_disabled=False, reason=""),
        )

    async def add_user(self, id, name):
        user = self.new_user(id, name)
        # Mongo first
        await self.col.insert_one(user)
        # then PG
        await pgDb.upsert_user(int(id), str(name))

    async def is_user_exist(self, id):
        # PG first (cached)
        if await pgDb.is_user_exist(int(id)):
            return True
        # fallback mongo + self-heal
        user = await self.col.find_one({"id": int(id)})
        if user:
            await pgDb.upsert_user(int(id), str(user.get("name", "")))
        return bool(user)

    async def total_users_count(self):
        # PG first
        return await pgDb.total_users_count()

    async def remove_ban(self, id):
        ban_status = dict(is_banned=False, ban_reason="")
        # Mongo first
        await self.col.update_one({"id": int(id)}, {"$set": {"ban_status": ban_status}})
        # then PG
        await pgDb.set_ban(int(id), False, "")

    async def ban_user(self, user_id, ban_reason="No Reason"):
        ban_status = dict(is_banned=True, ban_reason=ban_reason)
        # Mongo first
        await self.col.update_one({"id": int(user_id)}, {"$set": {"ban_status": ban_status}})
        # then PG
        await pgDb.set_ban(int(user_id), True, str(ban_reason or ""))

    async def get_ban_status(self, id):
        # PG first (cached)
        status = await pgDb.get_ban_status(int(id))
        if status is not None:
            return status
        # fallback mongo
        default = dict(is_banned=False, ban_reason="")
        user = await self.col.find_one({"id": int(id)})
        if not user:
            return default
        bs = user.get("ban_status", default)
        await pgDb.upsert_user(int(id), str(user.get("name", "")))
        await pgDb.set_ban(int(id), bool(bs.get("is_banned", False)), str(bs.get("ban_reason", "")))
        return bs

    async def get_all_users(self):
        # PG first: yield like a cursor
        skip = 0
        batch = 500
        while True:
            rows = await pgDb.get_all_users(skip=skip, limit=batch)
            if not rows:
                break
            for r in rows:
                yield r
            skip += len(rows)
            if len(rows) < batch:
                break

    async def delete_user(self, user_id):
        # Mongo first
        await self.col.delete_many({"id": int(user_id)})
        # then PG
        await pgDb.delete_user(int(user_id))

    async def delete_chat(self, chat_id):
        await self.grp.delete_many({"id": int(chat_id)})
        await pgDb.delete_chat(int(chat_id))

    async def get_banned(self):
        # PG first
        return await pgDb.get_banned()

    async def add_chat(self, chat, title):
        doc = self.new_group(chat, title)
        # Mongo first
        await self.grp.insert_one(doc)
        # then PG
        await pgDb.upsert_group(int(chat), str(title))

    async def get_chat(self, chat):
        # PG first (cached)
        status = await pgDb.get_chat_status(int(chat))
        if status is not None:
            return status

        # fallback mongo + self-heal
        doc = await self.grp.find_one({"id": int(chat)})
        if not doc:
            return False
        cs = doc.get("chat_status")
        await pgDb.upsert_group(int(chat), str(doc.get("title", "")))
        await pgDb.set_group_disabled(int(chat), bool(cs.get("is_disabled", False)), str(cs.get("reason", "")))
        return cs

    async def re_enable_chat(self, id):
        chat_status = dict(is_disabled=False, reason="")
        # Mongo first
        await self.grp.update_one({"id": int(id)}, {"$set": {"chat_status": chat_status}})
        # then PG
        await pgDb.set_group_disabled(int(id), False, "")

    async def update_settings(self, id, settings):
        # Mongo first (keep existing behavior)
        await self.grp.update_one({"id": int(id)}, {"$set": {"settings": settings}})
        # then PG
        await pgDb.update_settings(int(id), settings)

    async def get_settings(self, id):
        # PG first (cached)
        return await pgDb.get_settings(int(id))

    async def disable_chat(self, chat, reason="No Reason"):
        chat_status = dict(is_disabled=True, reason=reason)
        # Mongo first
        await self.grp.update_one({"id": int(chat)}, {"$set": {"chat_status": chat_status}})
        # then PG
        await pgDb.set_group_disabled(int(chat), True, str(reason or ""))

    async def total_chat_count(self):
        # quickest: PG count
        val = await pgDb.execute_fetchval("SELECT COUNT(*) FROM groups")
        return int(val or 0)

    async def get_all_chats(self):
        skip = 0
        batch = 500
        while True:
            rows = await pgDb.get_all_chats(skip=skip, limit=batch)
            if not rows:
                break
            for r in rows:
                yield r
            skip += len(rows)
            if len(rows) < batch:
                break

    async def get_db_size(self):
        # Mongo dbstats is fine; PG size is a separate thing
        return (await self.db.command("dbstats"))["dataSize"]


db = Database(DATABASE_URI, DATABASE_NAME)
