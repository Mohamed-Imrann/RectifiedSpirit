#!/usr/bin/env python3
# 8:52PM 2024-05-29
# ebiza.t.me
import motor.motor_asyncio
from info import DATABASE_NAME, DATABASE_URL, ADMINS

class RequestForceSubDB:
    def __init__(self):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URL)
        self.db = self.client[DATABASE_NAME]
        self.req_one_collection = self.db['req_one']
        self.req_two_collection = self.db['req_two']
        self.fsub_requests_collection = self.db.fsub_requests

    async def get_req_one(self, user_id):
        return await self.req_one_collection.find_one({"user_id": int(user_id)})
    
    async def get_req_two(self, user_id):
        return await self.req_two_collection.find_one({"user_id": int(user_id)})

    async def delete_all_one(self):
        await self.req_one_collection.delete_many({})
    
    async def delete_all_two(self):
        await self.req_two_collection.delete_many({})

    async def is_requested_one(self, user_id):
        if await self.get_req_one(user_id): return True
        if user_id in ADMINS: return True
        return False

    async def is_requested_two(self, user_id):
        if await self.get_req_two(user_id): return True
        if user_id in ADMINS: return True
        return False

    async def add_req_one(self, user_id):
        try:
            if not await self.get_req_one(user_id):
                return await self.req_one_collection.insert_one({"user_id": int(user_id)})
        except: pass

    async def add_req_two(self, user_id):
        try:
            if not await self.get_req_two(user_id):
                return await self.req_two_collection.insert_one({"user_id": int(user_id)})
        except: pass

    async def add_fsub_request(self, user_id, message_id):
        await self.fsub_requests_collection.update_one(
            {"_id": user_id},
            {"$set": {"message_id": message_id}},
            upsert=True
        )

    async def get_fsub_request(self, user_id):
        return await self.fsub_requests_collection.find_one({"_id": user_id})

request_forcesub_db = RequestForceSubDB()
