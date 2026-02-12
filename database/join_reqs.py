# database/join_reqs.py
# -*- coding: utf-8 -*-

from database.users_chats_db import db as main_db  # <- your Database() instance


class JoinReqs:
    """
    Stores:
      1) fsub chats: fsub_chat1/2/3
      2) user step state: 1 -> channel1, 2 -> channel2, 3 -> channel3, then cycles again
    """

    def __init__(self):
        # ✅ important: main_db.db is the real Motor Database object
        self.db = main_db.db

        # collections
        self.col = self.db["join_reqs"]        # stores fsub chat ids
        self.state = self.db["fsub_state"]     # stores user step

    # -------------------------
    # Fsub chat setters/getters
    # -------------------------
    async def add_fsub_chat1(self, chat_id: int):
        await self.col.update_one({"_id": "fsub_chat1"}, {"$set": {"chat_id": int(chat_id)}}, upsert=True)

    async def get_fsub_chat1(self):
        return await self.col.find_one({"_id": "fsub_chat1"})

    async def delete_fsub_chat1(self, chat_id=None):
        await self.col.delete_one({"_id": "fsub_chat1"})

    async def add_fsub_chat2(self, chat_id: int):
        await self.col.update_one({"_id": "fsub_chat2"}, {"$set": {"chat_id": int(chat_id)}}, upsert=True)

    async def get_fsub_chat2(self):
        return await self.col.find_one({"_id": "fsub_chat2"})

    async def delete_fsub_chat2(self, chat_id=None):
        await self.col.delete_one({"_id": "fsub_chat2"})

    async def add_fsub_chat3(self, chat_id: int):
        await self.col.update_one({"_id": "fsub_chat3"}, {"$set": {"chat_id": int(chat_id)}}, upsert=True)

    async def get_fsub_chat3(self):
        return await self.col.find_one({"_id": "fsub_chat3"})

    async def delete_fsub_chat3(self, chat_id=None):
        await self.col.delete_one({"_id": "fsub_chat3"})

    # -------------------------
    # User step (sequential fsub)
    # -------------------------
    async def get_user_step(self, user_id: int) -> int:
        doc = await self.state.find_one({"_id": int(user_id)})
        if not doc:
            return 1
        step = int(doc.get("step", 1))
        if step not in (1, 2, 3):
            step = 1
        return step

    async def set_user_step(self, user_id: int, step: int):
        step = int(step)
        if step not in (1, 2, 3):
            step = 1
        await self.state.update_one({"_id": int(user_id)}, {"$set": {"step": step}}, upsert=True)

    async def advance_user_step(self, user_id: int) -> int:
        step = await self.get_user_step(user_id)
        # 1 -> 2 -> 3 -> 1
        next_step = 1 if step == 3 else step + 1
        await self.set_user_step(user_id, next_step)
        return next_step

    async def reset_user_step(self, user_id: int):
        await self.state.delete_one({"_id": int(user_id)})
