# database/request_forcesub_db.py

import motor.motor_asyncio
from info import DATABASE_URI, DATABASE_NAME, ADMINS
from database.postgres import pgDb

mongo = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URI)
mydb = mongo[DATABASE_NAME]
req_one = mydb["req_one"]
req_two = mydb["req_two"]


async def get_req_one(user_id):
    # PG first
    row = await pgDb.get_req(1, int(user_id))
    if row:
        return row
    # fallback mongo + self-heal
    doc = await req_one.find_one({"user_id": int(user_id)})
    if doc:
        await pgDb.add_req(1, int(user_id))
    return doc


async def get_req_two(user_id):
    row = await pgDb.get_req(2, int(user_id))
    if row:
        return row
    doc = await req_two.find_one({"user_id": int(user_id)})
    if doc:
        await pgDb.add_req(2, int(user_id))
    return doc


async def delete_all_one():
    # Mongo first
    await req_one.delete_many({})
    # then PG
    await pgDb.delete_all_req(1)


async def delete_all_two():
    await req_two.delete_many({})
    await pgDb.delete_all_req(2)


async def is_requested_one(user_id):
    if user_id in ADMINS:
        return True
    return bool(await get_req_one(user_id))


async def is_requested_two(user_id):
    if user_id in ADMINS:
        return True
    return bool(await get_req_two(user_id))


async def add_req_one(user_id):
    if await get_req_one(user_id):
        return
    # Mongo first
    await req_one.insert_one({"user_id": int(user_id)})
    # then PG
    await pgDb.add_req(1, int(user_id))


async def add_req_two(user_id):
    if await get_req_two(user_id):
        return
    await req_two.insert_one({"user_id": int(user_id)})
    await pgDb.add_req(2, int(user_id))
