# database/series_sql.py
import aiosqlite
import os

DB_PATH = os.getenv("DB_PATH", "series.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL UNIQUE,
            poster TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER NOT NULL,
            language TEXT NOT NULL,
            season TEXT NOT NULL,
            quality TEXT NOT NULL,
            UNIQUE(series_id, language, season, quality),
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
            created_at INTEGER DEFAULT (strftime('%s','now')),
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
        """)
        await db.commit()


# --------- Series ----------
async def upsert_series(title: str) -> int:
    title = title.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("INSERT OR IGNORE INTO series(title) VALUES(?)", (title,))
        cur = await db.execute("SELECT id FROM series WHERE title=?", (title,))
        row = await cur.fetchone()
        return int(row[0])


async def get_series_by_id(series_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, title, poster FROM series WHERE id=?", (series_id,))
        return await cur.fetchone()


async def set_series_poster(series_id: int, poster_file_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE series SET poster=? WHERE id=?", (poster_file_id, series_id))
        await db.commit()


async def find_series(query: str):
    q = f"%{query.strip()}%"
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, title, poster FROM series WHERE title LIKE ? ORDER BY id DESC LIMIT 1",
            (q,)
        )
        return await cur.fetchone()


# --------- Group helpers ----------
async def ensure_group(series_id: int, language: str, season: str, quality: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute(
            "INSERT OR IGNORE INTO groups(series_id, language, season, quality) VALUES(?,?,?,?)",
            (series_id, language, season, quality)
        )
        cur = await db.execute(
            "SELECT id FROM groups WHERE series_id=? AND language=? AND season=? AND quality=?",
            (series_id, language, season, quality)
        )
        row = await cur.fetchone()
        await db.commit()
        return int(row[0])


async def get_group_id_value(series_id: int, language: str, season: str, quality: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM groups WHERE series_id=? AND language=? AND season=? AND quality=?",
            (series_id, language, season, quality)
        )
        row = await cur.fetchone()
        return int(row[0]) if row else None


async def list_languages(series_id: int) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT language FROM groups WHERE series_id=? ORDER BY language COLLATE NOCASE",
            (series_id,)
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def list_seasons(series_id: int, language: str) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT season FROM groups WHERE series_id=? AND language=? ORDER BY season COLLATE NOCASE",
            (series_id, language)
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def list_qualities(series_id: int, language: str, season: str) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT quality FROM groups WHERE series_id=? AND language=? AND season=? ORDER BY quality COLLATE NOCASE",
            (series_id, language, season)
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


# --------- Files ----------
async def add_file(group_id: int, file_id: str, caption: str = "", msg_type: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute(
            "INSERT INTO files(group_id, file_id, caption, msg_type) VALUES(?,?,?,?)",
            (group_id, file_id, caption, msg_type)
        )
        await db.commit()


async def get_files(group_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT file_id, caption, msg_type FROM files WHERE group_id=? ORDER BY id ASC",
            (group_id,)
        )
        return await cur.fetchall()


async def count_files_in_group(group_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM files WHERE group_id=?", (group_id,))
        row = await cur.fetchone()
        return int(row[0] or 0)


# ================== DELETE (GROUP LEVEL) ==================
async def delete_language(series_id: int, language: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        cur = await db.execute(
            "DELETE FROM groups WHERE series_id=? AND language=?",
            (series_id, language)
        )
        await db.commit()
        return cur.rowcount


async def delete_season(series_id: int, language: str, season: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        cur = await db.execute(
            "DELETE FROM groups WHERE series_id=? AND language=? AND season=?",
            (series_id, language, season)
        )
        await db.commit()
        return cur.rowcount


async def delete_quality(series_id: int, language: str, season: str, quality: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        cur = await db.execute(
            "DELETE FROM groups WHERE series_id=? AND language=? AND season=? AND quality=?",
            (series_id, language, season, quality)
        )
        await db.commit()
        return cur.rowcount
