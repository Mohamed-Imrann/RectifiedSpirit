
# database/request_forcesub_db.py
import pymongo
from info import DATABASE_URI, DATABASE_NAME

myclient = pymongo.MongoClient(DATABASE_URI)
mydb = myclient[DATABASE_NAME]

# Old collections (keep if needed)
req_one = mydb["req_one"]
req_two = mydb["req_two"]

# Step tracking
fsub_steps = mydb["fsub_steps"]

# ✅ Pending file send (so user no need to click again)
pending_fsub = mydb["pending_fsub"]


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

async def advance_user_step(user_id: int, total: int):
    # ✅ total MUST come from actual chat list length
    if total <= 0:
        await set_user_step(user_id, 1)
        return

    step = await get_user_step(user_id)
    step += 1
    if step > total:
        step = 1
    await set_user_step(user_id, step)


# ---------------------------
# ✅ PENDING (AUTO SEND)
# ---------------------------
async def set_pending(user_id: int, link_key: str, required_chat_id: int, step: int, total: int):
    pending_fsub.update_one(
        {"user_id": int(user_id)},
        {"$set": {
            "user_id": int(user_id),
            "link_key": str(link_key),
            "required_chat_id": int(required_chat_id),
            "step": int(step),
            "total": int(total),
        }},
        upsert=True
    )

async def get_pending(user_id: int):
    return pending_fsub.find_one({"user_id": int(user_id)})

async def clear_pending(user_id: int):
    pending_fsub.delete_one({"user_id": int(user_id)})


# ---------------------------
# OLD (optional keep)
# ---------------------------
async def get_req_one(user_id):
    return req_one.find_one({"user_id": int(user_id)})

async def get_req_two(user_id):
    return req_two.find_one({"user_id": int(user_id)})

async def get_req_one_count():
    return req_one.count_documents({})

async def get_req_two_count():
    return req_two.count_documents({})

async def delete_all_one():
    req_one.delete_many({})

async def delete_all_two():
    req_two.delete_many({})
