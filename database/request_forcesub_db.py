#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pymongo
from info import DATABASE_URI, DATABASE_NAME, ADMINS

# Mongo
myclient = pymongo.MongoClient(DATABASE_URI)
mydb = myclient[DATABASE_NAME]

# ✅ single state collection (sequential)
fsub_state = mydb["fsub_state"]  # { _id: user_id, step: 1/2/3 }

# ----------------------------
# Helpers
# ----------------------------
def _is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in ADMINS
    except Exception:
        return False

# ----------------------------
# Step logic (1 -> 2 -> 3 -> 1)
# ----------------------------
async def get_user_step(user_id: int) -> int:
    if _is_admin(user_id):
        return 0  # admin no fsub

    doc = fsub_state.find_one({"_id": int(user_id)})
    if not doc:
        return 1
    step = int(doc.get("step", 1))
    if step not in (1, 2, 3):
        step = 1
    return step

async def set_user_step(user_id: int, step: int):
    if _is_admin(user_id):
        return

    step = int(step)
    if step not in (1, 2, 3):
        step = 1
    fsub_state.update_one(
        {"_id": int(user_id)},
        {"$set": {"step": step}},
        upsert=True
    )

async def advance_user_step(user_id: int) -> int:
    """
    Called only AFTER user joined required channel successfully.
    """
    if _is_admin(user_id):
        return 0

    step = await get_user_step(user_id)
    next_step = 1 if step == 3 else step + 1
    await set_user_step(user_id, next_step)
    return next_step

async def reset_user_step(user_id: int):
    if _is_admin(user_id):
        return
    fsub_state.delete_one({"_id": int(user_id)})

# ----------------------------
# Admin utilities (optional)
# ----------------------------
async def delete_all_states():
    fsub_state.delete_many({})

async def get_all_states():
    return list(fsub_state.find({}))

async def get_states_count():
    return fsub_state.count_documents({})
