#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# database/request_forcesub_db.py

import pymongo
import secrets
from datetime import datetime, timedelta
from info import DATABASE_URI, DATABASE_NAME

myclient = pymongo.MongoClient(DATABASE_URI)
mydb = myclient[DATABASE_NAME]

# Old collections (keep if needed)
req_one = mydb["req_one"]
req_two = mydb["req_two"]

# Step tracking (per user)
fsub_steps = mydb["fsub_steps"]

# ✅ Pending file send (so user no need to click again)
pending_fsub = mydb["pending_fsub"]

# ✅ short-lived deep-link token cache
temp_tokens = mydb["fsub_temp_tokens"]
temp_tokens.create_index("expires_at", expireAfterSeconds=0)


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
    """
    ✅ 1 -> 2 -> 3 -> (STOP at 3)
    total = actual fsub chats count
    """
    if not total or int(total) <= 0:
        await set_user_step(user_id, 1)
        return

    total = int(total)
    step = await get_user_step(user_id)
    step = int(step) + 1

    # ✅ do NOT loop back to 1
    if step > total:
        step = total

    await set_user_step(user_id, step)


# ---------------------------
# ✅ PENDING (AUTO SEND)
# ---------------------------
async def set_pending(user_id: int, link_key: str, required_chat_id: int, step: int, total: int):
    # ✅ normalize chat id (store plain too)
    rcid = int(required_chat_id)
    rcid_plain = int(str(rcid).replace("-100", "")) if str(rcid).startswith("-100") else rcid

    pending_fsub.update_one(
        {"user_id": int(user_id)},
        {"$set": {
            "user_id": int(user_id),
            "link_key": str(link_key),

            # ✅ store BOTH
            "required_chat_id": int(rcid),
            "required_chat_id_plain": int(rcid_plain),

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
# ✅ TEMP TOKEN (10 min cache)
# ---------------------------
async def create_temp_token(user_id: int, link_key: str, ttl_seconds: int = 600) -> str:
    token = secrets.token_urlsafe(16)
    expires_at = datetime.utcnow() + timedelta(seconds=int(ttl_seconds))
    temp_tokens.update_one(
        {"user_id": int(user_id), "token": token},
        {"$set": {
            "user_id": int(user_id),
            "token": token,
            "link_key": str(link_key),
            "expires_at": expires_at,
        }},
        upsert=True
    )
    return token


async def get_link_key_by_token(user_id: int, token: str):
    doc = temp_tokens.find_one({
        "user_id": int(user_id),
        "token": str(token),
        "expires_at": {"$gt": datetime.utcnow()},
    })
    if not doc:
        return None
    return doc.get("link_key")


async def delete_temp_token(user_id: int, token: str):
    temp_tokens.delete_one({"user_id": int(user_id), "token": str(token)})


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
