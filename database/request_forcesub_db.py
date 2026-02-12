#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pymongo
from info import DATABASE_URI, DATABASE_NAME, ADMINS

myclient = pymongo.MongoClient(DATABASE_URI)
mydb     = myclient[DATABASE_NAME]

req_one    = mydb["req_one"]
req_two    = mydb["req_two"]
req_three  = mydb["req_three"]   # ✅ NEW


async def get_req_one(user_id):
    return req_one.find_one({"user_id": int(user_id)})

async def get_req_two(user_id):
    return req_two.find_one({"user_id": int(user_id)})

async def get_req_three(user_id):
    return req_three.find_one({"user_id": int(user_id)})  # ✅ NEW


async def delete_all_one():
    req_one.delete_many({})

async def delete_all_two():
    req_two.delete_many({})

async def delete_all_three():
    req_three.delete_many({})  # ✅ NEW


async def get_all_req_one():
    return list(req_one.find({}))

async def get_all_req_two():
    return list(req_two.find({}))

async def get_all_req_three():
    return list(req_three.find({}))  # ✅ NEW


async def get_req_one_count():
    return req_one.count_documents({})

async def get_req_two_count():
    return req_two.count_documents({})

async def get_req_three_count():
    return req_three.count_documents({})  # ✅ NEW


async def is_requested_one(user_id):
    if user_id in ADMINS: return True
    return bool(await get_req_one(user_id))

async def is_requested_two(user_id):
    if user_id in ADMINS: return True
    return bool(await get_req_two(user_id))

async def is_requested_three(user_id):
    if user_id in ADMINS: return True
    return bool(await get_req_three(user_id))  # ✅ NEW


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
