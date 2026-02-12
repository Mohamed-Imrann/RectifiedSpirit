#!/usr/bin/env python3
# 8:52PM 2024-05-29
# ebiza.t.me

import pymongo
from info import DATABASE_URI, DATABASE_NAME, ADMINS

myclient = pymongo.MongoClient(DATABASE_URI)
mydb     = myclient[DATABASE_NAME]

# ✅ 3 collections
req_one   = mydb["req_one"]
req_two   = mydb["req_two"]
req_three = mydb["req_three"]


# ---------------------------
# GET
# ---------------------------
async def get_req_one(user_id):
    return req_one.find_one({"user_id": int(user_id)})

async def get_req_two(user_id):
    return req_two.find_one({"user_id": int(user_id)})

async def get_req_three(user_id):
    return req_three.find_one({"user_id": int(user_id)})


# ---------------------------
# DELETE ALL
# ---------------------------
async def delete_all_one():
    req_one.delete_many({})

async def delete_all_two():
    req_two.delete_many({})

async def delete_all_three():
    req_three.delete_many({})


# ---------------------------
# LIST + COUNT
# ---------------------------
async def get_all_req_one():
    return list(req_one.find({}))

async def get_req_one_count():
    return req_one.count_documents({})

async def get_all_req_two():
    return list(req_two.find({}))

async def get_req_two_count():
    return req_two.count_documents({})

async def get_all_req_three():
    return list(req_three.find({}))

async def get_req_three_count():
    return req_three.count_documents({})


# ---------------------------
# CHECK
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

async def is_requested_three(user_id):
    if await get_req_three(user_id):
        return True
    if int(user_id) in ADMINS:
        return True
    return False


# ---------------------------
# ADD
# ---------------------------
async def add_req_one(user_id):
    try:
        if not await get_req_one(user_id):
            return req_one.insert_one({"user_id": int(user_id)})
    except:
        pass

async def add_req_two(user_id):
    try:
        if not await get_req_two(user_id):
            return req_two.insert_one({"user_id": int(user_id)})
    except:
        pass

async def add_req_three(user_id):
    try:
        if not await get_req_three(user_id):
            return req_three.insert_one({"user_id": int(user_id)})
    except:
        pass
