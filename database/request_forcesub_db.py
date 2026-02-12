# database/request_forcesub_db.py

import pymongo
from info import DATABASE_URI, DATABASE_NAME, ADMINS, REQ_CHANNEL_ONE, REQ_CHANNEL_TWO

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

    # remove duplicates (preserve order)
    uniq = []
    for x in chats:
        if x not in uniq:
            uniq.append(x)

    return uniq


# ---------------------------
# STEP SYSTEM ✅ (NEW)
# ---------------------------
async def get_user_step(user_id: int) -> int:
    doc = fsub_steps.find_one({"user_id": int(user_id)})
    if not doc:
        return 1
    step = int(doc.get("step", 1))
    return step if step >= 1 else 1


async def set_user_step(user_id: int, step: int):
    fsub_steps.update_one(
        {"user_id": int(user_id)},
        {"$set": {"step": int(step)}},
        upsert=True
    )


async def advance_user_step(user_id: int, total: int = None):
    """
    ✅ Compatible function:
    - advance_user_step(user_id)             -> auto total from get_all_fsub_chats()
    - advance_user_step(user_id, total=2)    -> uses provided total
    """
    if total is None:
        chats = await get_all_fsub_chats()
        total = len(chats)

    # if no channels set, keep step as 1
    if not total or total < 1:
        await set_user_step(int(user_id), 1)
        return

    step = await get_user_step(int(user_id))
    step += 1
    if step > total:
        step = 1
    await set_user_step(int(user_id), step)


# ---------------------------
# GET (old)
# ---------------------------
async def get_req_one(user_id):
    return req_one.find_one({"user_id": int(user_id)})


async def get_req_two(user_id):
    return req_two.find_one({"user_id": int(user_id)})


# ---------------------------
# COUNT ✅
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
