# database/request_forcesub_db.py
import pymongo
from info import DATABASE_URI, DATABASE_NAME

myclient = pymongo.MongoClient(DATABASE_URI)
mydb = myclient[DATABASE_NAME]

# stores user step: 1..N
fsub_steps = mydb["fsub_steps"]


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
    total = how many fsub channels configured (1..3)
    """
    step = await get_user_step(user_id)
    step += 1
    if step > int(total):
        step = 1
    await set_user_step(user_id, step)
