import pymongo
from info import DATABASE_URI, DATABASE_NAME, ADMINS

myclient = pymongo.MongoClient(DATABASE_URI)
mydb = myclient[DATABASE_NAME]

req_one = mydb['req_one']
req_two = mydb['req_two']


# ---------------------------
# GET
# ---------------------------

async def get_req_one(user_id):
    return req_one.find_one({"user_id": int(user_id)})

async def get_req_two(user_id):
    return req_two.find_one({"user_id": int(user_id)})


# ---------------------------
# COUNT  ✅
# ---------------------------

async def get_req_one_count():
    return req_one.count_documents({})

async def get_req_two_count():
    return req_two.count_documents({})


# ---------------------------
# DELETE ALL  ✅
# ---------------------------

async def delete_all_one():
    req_one.delete_many({})

async def delete_all_two():
    req_two.delete_many({})


# ---------------------------
# CHECK
# ---------------------------

async def is_requested_one(user_id):
    if await get_req_one(user_id):
        return True
    if user_id in ADMINS:
        return True
    return False

async def is_requested_two(user_id):
    if await get_req_two(user_id):
        return True
    if user_id in ADMINS:
        return True
    return False


# ---------------------------
# ADD
# ---------------------------

async def add_req_one(user_id):
    if not await get_req_one(user_id):
        req_one.insert_one({"user_id": int(user_id)})

async def add_req_two(user_id):
    if not await get_req_two(user_id):
        req_two.insert_one({"user_id": int(user_id)})
