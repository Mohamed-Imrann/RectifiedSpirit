# database/join_reqs.py
# -*- coding: utf-8 -*-

from database.users_chats_db import db  # your existing motor db instance


class JoinReqs:
    """
    Stores:
    - required fsub chats (chat1/chat2/chat3)
    - per-user fsub step state
    """

    def __init__(self):
        # collections
        self.col = db["join_reqs"]          # stores fsub chats
        self.state = db["fsub_state"]       # stores user step

    # -------------------------
    # Generic helpers
    # -------------------------
    async def set_fsub_chat(self, idx: int, chat_id: int):
        await self.col.update_one(
            {"_id": f"fsub_chat{idx}"},
            {"$set": {"chat_id": int(chat_id)}},
            upsert=True
        )

    async def get_fsub_chat(self, idx: int):
        return await self.col.find_one({"_id": f"fsub_chat{idx}"})

    async def del_fsub_chat(self, idx: int):
        await self.col.delete_one({"_id": f"fsub_chat{idx}"})

    # -------------------------
    # chat1
    # -------------------------
    async def add_fsub_chat1(self, chat_id: int):
        return await self.set_fsub_chat(1, chat_id)

    async def get_fsub_chat1(self):
        return await self.get_fsub_chat(1)

    async def delete_fsub_chat1(self, chat_id: int = None):
        return await self.del_fsub_chat(1)

    # -------------------------
    # chat2
    # -------------------------
    async def add_fsub_chat2(self, chat_id: int):
        return await self.set_fsub_chat(2, chat_id)

    async def get_fsub_chat2(self):
        return await self.get_fsub_chat(2)

    async def delete_fsub_chat2(self, chat_id: int = None):
        return await self.del_fsub_chat(2)

    # -------------------------
    # chat3
    # -------------------------
    async def add_fsub_chat3(self, chat_id: int):
        return await self.set_fsub_chat(3, chat_id)

    async def get_fsub_chat3(self):
        return await self.get_fsub_chat(3)

    async def delete_fsub_chat3(self, chat_id: int = None):
        return await self.del_fsub_chat(3)

    # -------------------------
    # User step state
    # step = 1 / 2 / 3 ...
    # -------------------------
    async def get_user_step(self, user_id: int) -> int:
        doc = await self.state.find_one({"_id": int(user_id)})
        if not doc:
            return 1
        return int(doc.get("step", 1))

    async def set_user_step(self, user_id: int, step: int):
        await self.state.update_one(
            {"_id": int(user_id)},
            {"$set": {"step": int(step)}},
            upsert=True
        )

    async def reset_user_step(self, user_id: int):
        await self.state.delete_one({"_id": int(user_id)})
