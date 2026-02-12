# database/join_reqs.py
# -*- coding: utf-8 -*-

import motor.motor_asyncio
from info import DATABASE_URI, DATABASE_URL  # whichever exists


def _get_mongo_uri() -> str:
    # some repos use DATABASE_URL, some use DATABASE_URI
    uri = (DATABASE_URL or "").strip() if "DATABASE_URL" in globals() else ""
    if not uri:
        uri = (DATABASE_URI or "").strip()
    return uri


class JoinReqs:
    """
    Stores:
    - fsub chats: fsub_chat1/2/3
    - per-user step state
    """

    def __init__(self):
        uri = _get_mongo_uri()
        if not uri:
            raise RuntimeError("DATABASE_URL / DATABASE_URI not set")

        self.client = motor.motor_asyncio.AsyncIOMotorClient(uri)

        # Use separate DB name to avoid conflict
        self.db = self.client["JoinReqsDB"]

        # collections
        self.col = self.db["join_reqs"]      # stores fsub chats
        self.state = self.db["fsub_state"]   # stores user step

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
    # chat1/2/3 aliases (your bot expects these names)
    # -------------------------
    async def add_fsub_chat1(self, chat_id: int):
        return await self.set_fsub_chat(1, chat_id)

    async def get_fsub_chat1(self):
        return await self.get_fsub_chat(1)

    async def delete_fsub_chat1(self, chat_id: int = None):
        return await self.del_fsub_chat(1)

    async def add_fsub_chat2(self, chat_id: int):
        return await self.set_fsub_chat(2, chat_id)

    async def get_fsub_chat2(self):
        return await self.get_fsub_chat(2)

    async def delete_fsub_chat2(self, chat_id: int = None):
        return await self.del_fsub_chat(2)

    async def add_fsub_chat3(self, chat_id: int):
        return await self.set_fsub_chat(3, chat_id)

    async def get_fsub_chat3(self):
        return await self.get_fsub_chat(3)

    async def delete_fsub_chat3(self, chat_id: int = None):
        return await self.del_fsub_chat(3)

    # -------------------------
    # User step state
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
