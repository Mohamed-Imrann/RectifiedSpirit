# database/request_forcesub_db.py

import pymongo
import secrets
import time
from typing import Optional, Dict, Any

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
# ✅ TEMP TOKEN SYSTEM (for PM redirect)
# ---------------------------
# NOTE:
# - This is in-memory (fast)
# - Container restart aana tokens clear aagum (OK)
# - TTL default 10 min
_TEMP_TOKENS: Dict[str, Dict[str, Any]] = {}


async def create_temp_token(user_id: int, payload: dict, ttl: int = 600) -> str:
    token = secrets.token_urlsafe(10)
    _TEMP_TOKENS[token] = {
        "user_id": int(user_id),
        "payload": payload,
        "exp": time.time() + int(ttl),
    }
    return token


async def get_temp_token(token: str, user_id: Optional[int] = None) -> Optional[dict]:
    data = _TEMP_TOKENS.get(token)
    if not data:
        return None

    if data.get("exp", 0) < time.time():
        _TEMP_TOKENS.pop(token, None)
        return None

    if user_id is not None and int(data.get("user_id", 0)) != int(user_id):
        return None

    return data.get("payload")


async def consume_temp_token(token: str, user_id: Optional[int] = None) -> Optional[dict]:
    payload = await get_temp_token(token, user_id=user_id)
    if payload is None:
        return None
    _TEMP_TOKENS.pop(token, None)
    return payload


async def cleanup_temp_tokens() -> int:
    now = time.time()
    dead = [t for t, v in _TEMP_TOKENS.items() if v.get("exp", 0) < now]
    for t in dead:
        _TEMP_TOKENS.pop(t, None)
    return len(dead)


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
