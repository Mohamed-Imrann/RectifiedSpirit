# database/request_forcesub_db.py
import pymongo
import secrets
import time
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

# ✅ Temp token store (for button retry / secure callbacks)
temp_tokens = mydb["temp_tokens"]


# ---------------------------
# ✅ TEMP TOKEN SYSTEM
# ---------------------------
async def create_temp_token(user_id: int, ttl_seconds: int = 900) -> str:
    """
    Create a short-lived token for inline button callbacks.
    Default TTL = 15 minutes.
    """
    token = secrets.token_urlsafe(16)
    expires_at = int(time.time()) + int(ttl_seconds)

    temp_tokens.update_one(
        {"token": token},
        {"$set": {
            "token": token,
            "user_id": int(user_id),
            "expires_at": int(expires_at),
            "created_at": int(time.time()),
        }},
        upsert=True
    )
    return token


async def verify_temp_token(token: str, user_id: int, consume: bool = True) -> bool:
    """
    Validate token belongs to user and not expired.
    If consume=True => one-time use (deletes after success).
    """
    if not token:
        return False

    doc = temp_tokens.find_one({"token": str(token)})
    if not doc:
        return False

    if int(doc.get("user_id", 0)) != int(user_id):
        return False

    exp = int(doc.get("expires_at", 0))
    now = int(time.time())
    if now > exp:
        temp_tokens.delete_one({"token": str(token)})
        return False

    if consume:
        temp_tokens.delete_one({"token": str(token)})

    return True


async def cleanup_expired_tokens():
    """Optional: remove expired tokens to keep DB clean."""
    now = int(time.time())
    temp_tokens.delete_many({"expires_at": {"$lte": now}})


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
