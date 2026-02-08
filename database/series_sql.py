# database/series_sql.py
import aiosqlite
import os

DB_PATH = os.getenv("SERIES_SQLITE_DB", "series.db")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    year TEXT,
    quality TEXT,
    language TEXT,
    poster TEXT,
    file_id TEXT,
    chat_id INTEGER,
    message_id INTEGER,
    raw JSON
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_TABLE)
        await db.commit()

async def insert_series(data: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO series
            (title, year, quality, language, poster, file_id, chat_id, message_id, raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("title"),
                data.get("year"),
                data.get("quality"),
                data.get("language"),
                data.get("poster"),
                data.get("file_id"),
                data.get("chat_id"),
                data.get("message_id"),
                str(data),
            )
        )
        await db.commit()

async def search_series(query: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT * FROM series
            WHERE title LIKE ?
            ORDER BY year DESC
            LIMIT 20
            """,
            (f"%{query}%",)
        )
        rows = await cursor.fetchall()
        return rows
