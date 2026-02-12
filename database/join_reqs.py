# database/join_reqs.py
import motor.motor_asyncio
from info import DATABASE_URL

class JoinReqs:
    def __init__(self):
        if not DATABASE_URL:
            self.client = None
            self.db = None
            return

        self.client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URL)
        self.db = self.client["JoinReqs"]

        # store fsub chat ids
        self.fsub_col = self.db["fsub_chats"]

        # store per-user step
        self.user_col = self.db["user_fsub_state"]

    # ---------------------------
    # FSUB CHAT SET/GET (1/2/3)
    # ---------------------------
    async def set_fsub_chat(self, index: int, chat_id: int):
        await self.fsub_col.update_one(
            {"_id": f"fsub_chat{index}"},
            {"$set": {"chat_id": int(chat_id)}},
            upsert=True
        )

    async def get_fsub_chat(self, index: int):
        return await self.fsub_col.find_one({"_id": f"fsub_chat{index}"})

    async def get_all_fsub_chats(self):
        chats = []
        for i in (1, 2, 3):
            doc = await self.get_fsub_chat(i)
            if doc and doc.get("chat_id"):
                chats.append(int(doc["chat_id"]))
        return chats

    # ---------------------------
    # USER STEP SET/GET/ADVANCE
    # ---------------------------
    async def get_user_step(self, user_id: int) -> int:
        doc = await self.user_col.find_one({"_id": int(user_id)})
        if not doc:
            return 1
        step = int(doc.get("step", 1))
        if step < 1:
            step = 1
        return step

    async def set_user_step(self, user_id: int, step: int):
        await self.user_col.update_one(
            {"_id": int(user_id)},
            {"$set": {"step": int(step)}},
            upsert=True
        )

    async def advance_user_step(self, user_id: int, total_steps: int):
        # if total_steps=2 => 1->2->1
        cur = await self.get_user_step(user_id)
        nxt = cur + 1
        if nxt > total_steps:
            nxt = 1
        await self.set_user_step(user_id, nxt)
