import aiosqlite
import os
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DB_PATH = os.getenv("SERIES_DB", "series.db")

# ---------------------------
# INIT DB & SCHEMA
# ---------------------------

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE NOT NULL,
            poster_file_id TEXT,
            published INTEGER DEFAULT 0
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS languages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER,
            name TEXT,
            poster_file_id TEXT,
            UNIQUE(series_id, name),
            FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            language_id INTEGER,
            name TEXT,
            poster_file_id TEXT,
            UNIQUE(language_id, name),
            FOREIGN KEY(language_id) REFERENCES languages(id) ON DELETE CASCADE
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS qualities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id INTEGER,
            name TEXT,
            UNIQUE(season_id, name),
            FOREIGN KEY(season_id) REFERENCES seasons(id) ON DELETE CASCADE
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quality_id INTEGER,
            file_id TEXT,
            file_name TEXT,
            file_size INTEGER,
            FOREIGN KEY(quality_id) REFERENCES qualities(id) ON DELETE CASCADE
        );
        """)

        await db.commit()

        logger.info("✅ SQL DB initialized")

# ---------------------------
# SERIES
# ---------------------------

async def add_series(title: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO series (title) VALUES (?)",
                (title,)
            )
            await db.commit()
            return True
        except:
            return False

async def get_series():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM series")
        return await cur.fetchall()

async def get_series_id(title: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM series WHERE title = ?",
            (title,)
        )
        row = await cur.fetchone()
        return row[0] if row else None

# ---------------------------
# LANGUAGE
# ---------------------------

async def add_language(series_id: int, name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO languages (series_id, name) VALUES (?, ?)",
                (series_id, name)
            )
            await db.commit()
            return True
        except:
            return False

async def get_languages(series_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, name FROM languages WHERE series_id = ?",
            (series_id,)
        )
        return await cur.fetchall()

# ---------------------------
# SEASON
# ---------------------------

async def add_season(language_id: int, name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO seasons (language_id, name) VALUES (?, ?)",
                (language_id, name)
            )
            await db.commit()
            return True
        except:
            return False

async def get_seasons(language_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, name FROM seasons WHERE language_id = ?",
            (language_id,)
        )
        return await cur.fetchall()

# ---------------------------
# QUALITY
# ---------------------------

async def add_quality(season_id: int, name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO qualities (season_id, name) VALUES (?, ?)",
                (season_id, name)
            )
            await db.commit()
            return True
        except:
            return False

async def get_qualities(season_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, name FROM qualities WHERE season_id = ?",
            (season_id,)
        )
        return await cur.fetchall()

# ---------------------------
# FILES (Episodes)
# ---------------------------

async def add_file(quality_id: int, file_id: str, file_name: str, file_size: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO files (quality_id, file_id, file_name, file_size)
            VALUES (?, ?, ?, ?)
            """,
            (quality_id, file_id, file_name, file_size)
        )
        await db.commit()

async def get_files(quality_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT file_id, file_name, file_size FROM files WHERE quality_id = ?",
            (quality_id,)
        )
        return await cur.fetchall()
