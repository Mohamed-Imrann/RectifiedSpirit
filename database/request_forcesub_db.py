# database/request_forcesub_db.py

import os
import pymongo

# ✅ NO "from info import ..." here (to avoid circular import)

DATABASE_URI = os.getenv("DATABASE_URI", "").strip()
DATABASE_NAME = os.getenv("DATABASE_NAME", "series_database").strip()

# ADMINS from env like: "123,456"
ADMINS = []
for x in os.getenv("ADMINS", "").replace(" ", ",").split(","):
    if x.strip().isdigit():
        ADMINS.append(int(x.strip()))

# Optional env channels (if you use)
REQ_CHANNEL_ONE = os.getenv("REQ_CHANNEL_ONE")
REQ_CHANNEL_TWO = os.getenv("REQ_CHANNEL_TWO")

myclient = pymongo.MongoClient(DATABASE_URI)
mydb = myclient[DATABASE_NAME]

# Old collections (keep)
req_one = mydb["req_one"]
req_two = mydb["req_two"]

# New collection for step system
fsub_steps = mydb["fsub_steps"]


# ---------------------------
# CHANNEL LIST (for step system)
# ---------------------------
async def get_all_fsub_chats():
    chats = []
    if REQ_CHANNEL_ONE:
        chats.append(int(REQ_CHANNEL_ONE))
    if REQ_CHANNEL_TWO:
        chats.append(int(REQ_CHANNEL_TWO))
    return chats


# ---------------------------
# STEP SYSTEM ✅
# ---------------------------
async def get_user_step(user_id: int) -> int:
    doc = fsub_steps.find_one({"user_id": int(user_id)})
    if not doc:
        return 1
    return int(doc.get("step", 1))


async def set_user_step(user_id: int, step: int):
    fsub_steps.update_one(
        {"user_id": int(user_id)},
        {"$set": {"step": int(step)}},
        upsert=True
    )


async def advance_user_step(user_id: int, total: int = 2):
    step = await get_user_step(user_id)
    step += 1
    if step > int(total):
        step = 1
    await set_user_step(user_id, step)


# ---------------------------
# GET (old)
# ---------------------------
async def get_req_one(user_id):
    return req_one.find_one({"user_id": int(user_id)})


async def get_req_two(user_id):
    return req_two.find_one({"user_id": int(user_id)})


# ---------------------------
# COUNT ✅ (these names MUST match utils import)
# ---------------------------
async def get_req_one_count():
    return req_one.count_documents({})


async def get_req_two_count():
    return req_two.count_documents({})


# ---------------------------
# DELETE ALL ✅
# ---------------------------
async def delete_all_one():
    req_one.delete_many({})


async def delete_all_two():
    req_two.delete_many({})


# ---------------------------
# CHECK (old)
# ---------------------------
async def is_requested_one(user_id):
    if await get_req_one(user_id):
        return True
    if int(user_id) in ADMINS:
        return True
    return False


async def is_requested_two(user_id):
    if await get_req_two(user_id):
        return True
    if int(user_id) in ADMINS:
        return True
    return False


# ---------------------------
# ADD (old)
# ---------------------------
async def add_req_one(user_id):
    if not await get_req_one(user_id):
        req_one.insert_one({"user_id": int(user_id)})


async def add_req_two(user_id):
    if not await get_req_two(user_id):
        req_two.insert_one({"user_id": int(user_id)})
