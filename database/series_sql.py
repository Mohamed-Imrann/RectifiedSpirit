# database/series_sql.py
import aiosqlite
from pathlib import Path

DB_PATH = Path("database/series.db")


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA foreign_keys=ON;")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE,
            poster_file_id TEXT,
            published INTEGER DEFAULT 0
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER,
            lang TEXT,
            season TEXT,
            quality TEXT,
            UNIQUE(series_id, lang, season, quality)
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER,
            file_id TEXT,
            caption TEXT,
            msg_type TEXT
        )
        """)

        await db.commit()


# -------- SERIES --------
async def upsert_series(title: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO series(title) VALUES(?)", (title,))
        await db.commit()
        cur = await db.execute("SELECT id FROM series WHERE title=?", (title,))
        row = await cur.fetchone()
        return row[0]


async def get_series_by_id(series_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, title, poster_file_id, published FROM series WHERE id=?",
            (series_id,),
        )
        return await cur.fetchone()


async def set_series_poster(series_id: int, poster_file_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE series SET poster_file_id=? WHERE id=?",
            (poster_file_id, series_id),
        )
        await db.commit()


async def toggle_publish(series_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT published FROM series WHERE id=?", (series_id,))
        row = await cur.fetchone()
        new = 0 if row[0] else 1
        await db.execute(
            "UPDATE series SET published=? WHERE id=?", (new, series_id)
        )
        await db.commit()
        return new


# -------- GROUPS --------
async def ensure_group(series_id, lang, season, quality):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO groups(series_id, lang, season, quality) VALUES(?,?,?,?)",
            (series_id, lang, season, quality),
        )
        await db.commit()

        cur = await db.execute(
            "SELECT id FROM groups WHERE series_id=? AND lang=? AND season=? AND quality=?",
            (series_id, lang, season, quality),
        )
        row = await cur.fetchone()
        return row[0]


async def get_group_id_value(series_id, lang, season, quality):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM groups WHERE series_id=? AND lang=? AND season=? AND quality=?",
            (series_id, lang, season, quality),
        )
        return await cur.fetchone()


async def list_languages(series_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT lang FROM groups WHERE series_id=?",
            (series_id,),
        )
        return [r[0] for r in await cur.fetchall()]


async def list_seasons(series_id, lang):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT season FROM groups WHERE series_id=? AND lang=?",
            (series_id, lang),
        )
        return [r[0] for r in await cur.fetchall()]


async def list_qualities(series_id, lang, season):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT quality FROM groups WHERE series_id=? AND lang=? AND season=?",
            (series_id, lang, season),
        )
        return [r[0] for r in await cur.fetchall()]


async def delete_language(series_id, lang):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM groups WHERE series_id=? AND lang=?", (series_id, lang)
        )
        await db.commit()


async def delete_season(series_id, lang, season):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM groups WHERE series_id=? AND lang=? AND season=?",
            (series_id, lang, season),
        )
        await db.commit()


async def delete_quality(series_id, lang, season, quality):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM groups WHERE series_id=? AND lang=? AND season=? AND quality=?",
            (series_id, lang, season, quality),
        )
        await db.commit()


# -------- FILES --------
async def add_file(group_id, file_id, caption="", msg_type=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO files(group_id, file_id, caption, msg_type) VALUES(?,?,?,?)",
            (group_id, file_id, caption, msg_type),
        )
        await db.commit()


async def count_files_in_group(group_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM files WHERE group_id=?", (group_id,)
        )
        row = await cur.fetchone()
        return row[0]

# =========================
# BACKWARD COMPAT (OLD REPO FIX)
# =========================

# old code compatibility
find_series_by_name = find_series
get_group_id = get_group_id_value
