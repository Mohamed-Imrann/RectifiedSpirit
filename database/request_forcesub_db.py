#!/usr/bin/env python3
# 8:52PM 2024-05-29
# ebiza.t.me
import pymongo
from info import DATABASE_URI, DATABASE_NAME, ADMINS


myclient = pymongo.MongoClient(DATABASE_URI)
mydb     = myclient[DATABASE_NAME]
req_one  = mydb['req_one']  
req_two  = mydb['req_two']


async def get_req_one(user_id):
    return req_one.find_one({"user_id": int(user_id)})
    
async def get_req_two(user_id):
    return req_two.find_one({"user_id": int(user_id)})

async def delete_all_one():
    req_one.delete_many({})
    
async def delete_all_two():
    req_two.delete_many({})


async def is_requested_one(user_id):
    if await get_req_one(user_id): return True
    if user_id in ADMINS: return True
    return False

async def is_requested_two(user_id):
    if await get_req_two(user_id): return True
    if user_id in ADMINS: return True
    return False


async def add_req_one(user_id):
    try:
        if not await get_req_one(user_id):
            return await req_one.insert_one({"user_id": int(user_id)})
    except: pass

async def add_req_two(user_id):
    try:
        if not await get_req_two(user_id):
            return await req_two.insert_one({"user_id": int(user_id)})
    except: pass