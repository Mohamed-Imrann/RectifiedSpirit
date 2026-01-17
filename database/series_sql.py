# database/series_sql.py
import aiosqlite
from pathlib import Path

DB_PATH = Path("database/series.db")


# ======================
# INIT DB
# ======================
async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA temp_store=MEMORY;")
        await db.execute("PRAGMA foreign_keys=ON;")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL UNIQUE,
            poster_file_id TEXT,
            published INTEGER NOT NULL DEFAULT 0
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER NOT NULL,
            lang TEXT NOT NULL,
            season TEXT NOT NULL,
            quality TEXT NOT NULL,
            UNIQUE(series_id, lang, season, quality),
            FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            caption TEXT,
            msg_type TEXT,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
        """)

        await db.execute("CREATE INDEX IF NOT EXISTS idx_series_title ON series(title)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_groups_series ON groups(series_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_files_group ON files(group_id)")
        await db.commit()


# ======================
# SERIES
# ======================
async def upsert_series(title: str) -> int:
    title = title.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO series(title) VALUES(?)",
            (title,)
        )
        await db.commit()

        cur = await db.execute(
            "SELECT id FROM series WHERE title=?",
            (title,)
        )
        row = await cur.fetchone()
        return int(row[0])


async def get_series_by_id(series_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, title, poster_file_id, published FROM series WHERE id=?",
            (series_id,)
        )
        return await cur.fetchone()


async def find_series(query: str):
    if not query:
        return None

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, title, poster_file_id FROM series "
            "WHERE title LIKE ? ORDER BY id DESC LIMIT 1",
            (f"%{query.strip()}%",)
        )
        return await cur.fetchone()


async def set_series_poster(series_id: int, poster_file_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE series SET poster_file_id=? WHERE id=?",
            (poster_file_id, series_id)
        )
        await db.commit()


async def toggle_publish(series_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT published FROM series WHERE id=?",
            (series_id,)
        )
        row = await cur.fetchone()
        if not row:
            return 0

        new_val = 0 if int(row[0]) == 1 else 1
        await db.execute(
            "UPDATE series SET published=? WHERE id=?",
            (new_val, series_id)
        )
        await db.commit()
        return new_val


# ======================
# GROUPS
# ======================
async def ensure_group(series_id: int, lang: str, season: str, quality: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO groups(series_id, lang, season, quality) "
            "VALUES(?,?,?,?)",
            (series_id, lang.strip(), season.strip(), quality.strip())
        )
        await db.commit()

        cur = await db.execute(
            "SELECT id FROM groups "
            "WHERE series_id=? AND lang=? AND season=? AND quality=?",
            (series_id, lang.strip(), season.strip(), quality.strip())
        )
        row = await cur.fetchone()
        return int(row[0])


# 🔥 THIS IS THE IMPORTANT FUNCTION
async def get_group_id_value(series_id: int, lang: str, season: str, quality: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM groups "
            "WHERE series_id=? AND lang=? AND season=? AND quality=?",
            (series_id, lang, season, quality)
        )
        return await cur.fetchone()


async def list_languages(series_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT lang FROM groups WHERE series_id=? ORDER BY lang",
            (series_id,)
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def list_seasons(series_id: int, lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT season FROM groups "
            "WHERE series_id=? AND lang=? ORDER BY season",
            (series_id, lang)
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def list_qualities(series_id: int, lang: str, season: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT quality FROM groups "
            "WHERE series_id=? AND lang=? AND season=? ORDER BY quality",
            (series_id, lang, season)
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def delete_language(series_id: int, lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM groups WHERE series_id=? AND lang=?",
            (series_id, lang)
        )
        await db.commit()


async def delete_season(series_id: int, lang: str, season: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM groups WHERE series_id=? AND lang=? AND season=?",
            (series_id, lang, season)
        )
        await db.commit()


async def delete_quality(series_id: int, lang: str, season: str, quality: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM groups "
            "WHERE series_id=? AND lang=? AND season=? AND quality=?",
            (series_id, lang, season, quality)
        )
        await db.commit()


# ======================
# FILES
# ======================
async def add_file(group_id: int, file_id: str, caption: str = "", msg_type: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO files(group_id, file_id, caption, msg_type) "
            "VALUES(?,?,?,?)",
            (group_id, file_id, caption or "", msg_type or "")
        )
        await db.commit()


async def get_files(group_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT file_id, caption, msg_type FROM files "
            "WHERE group_id=? ORDER BY id ASC",
            (group_id,)
        )
        return await cur.fetchall()


async def count_files_in_group(group_id: int) -> int:
    if not group_id:
        return 0

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(1) FROM files WHERE group_id=?",
            (group_id,)
        )
        row = await cur.fetchone()
        return int(row[0] or 0)
