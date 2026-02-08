import os
import aiosqlite
import logging
import asyncio
from pathlib import Path

# ✅ ENV support
DB_PATH = Path(os.getenv("DB_PATH", "database/series.db"))

# optional: connection timeout (seconds)
SQLITE_TIMEOUT = int(os.getenv("SQLITE_TIMEOUT", "30"))

db_lock = asyncio.Lock()
logger = logging.getLogger(__name__)

# Global connection
db: aiosqlite.Connection | None = None


# -------------------------
# internal helper: add columns safely
# -------------------------
async def _add_column_if_missing(table: str, col: str, coltype: str):
    if db is None:
        raise RuntimeError("DB not initialized. Call init_db() first.")

    cur = await db.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in await cur.fetchall()]
    if col not in cols:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        logger.info(f"Added missing column '{col}' to table '{table}'")


async def init_db():
    """
    Initializes SQLite database and keeps a global aiosqlite connection in `db`.
    Safe to call multiple times (closes previous connection).
    """
    global db
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # if already open, close & reopen (helps on restarts)
    try:
        if db is not None:
            await db.close()
    except Exception:
        pass

    db = await aiosqlite.connect(DB_PATH, timeout=SQLITE_TIMEOUT)

    # performance / safety pragmas
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA synchronous=NORMAL;")
    await db.execute("PRAGMA temp_store=MEMORY;")
    await db.execute("PRAGMA foreign_keys=ON;")

    # base tables
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

    # migrations
    await _add_column_if_missing("series", "tmdb_id", "INTEGER")
    await _add_column_if_missing("series", "year", "TEXT")
    await _add_column_if_missing("series", "rating", "REAL")
    await _add_column_if_missing("series", "genres", "TEXT")
    await _add_column_if_missing("series", "overview", "TEXT")

    # indexes
    await db.execute("CREATE INDEX IF NOT EXISTS idx_series_title ON series(title)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_groups_series ON groups(series_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_files_group ON files(group_id)")

    # ✅ prevent duplicates if migration runs twice
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_files_group_file ON files(group_id, file_id)")

    await db.commit()
    logger.info(f"✅ Database initialized: {DB_PATH}")


def _ensure_db():
    if db is None:
        raise RuntimeError("DB not initialized. Call init_db() first.")


# ---------- series ----------
async def upsert_series(title: str) -> int:
    _ensure_db()
    title = title.strip()

    async with db_lock:
        await db.execute("INSERT OR IGNORE INTO series(title) VALUES(?)", (title,))
        await db.commit()
        cur = await db.execute("SELECT id FROM series WHERE title=?", (title,))
        row = await cur.fetchone()
        sid = int(row[0]) if row else 0
        logger.info(f"📌 Upserted series '{title}' (id={sid})")
        return sid


async def get_series_by_id(series_id: int):
    _ensure_db()
    cur = await db.execute(
        "SELECT id, title, poster_file_id, published, tmdb_id, year, rating, genres, overview "
        "FROM series WHERE id=?",
        (series_id,),
    )
    return await cur.fetchone()


async def find_series(query: str):
    _ensure_db()
    if not query.strip():
        return None
    cur = await db.execute(
        "SELECT id, title, poster_file_id, published, tmdb_id, year, rating, genres, overview "
        "FROM series WHERE title LIKE ? ORDER BY id DESC LIMIT 1",
        (f"%{query.strip()}%",),
    )
    return await cur.fetchone()


async def set_series_poster(series_id: int, poster_file_id: str):
    _ensure_db()
    async with db_lock:
        await db.execute("UPDATE series SET poster_file_id=? WHERE id=?", (poster_file_id, series_id))
        await db.commit()


async def set_series_meta(series_id: int, tmdb_id: int, year: str, rating: float, genres: str, overview: str):
    _ensure_db()
    async with db_lock:
        await db.execute(
            "UPDATE series SET tmdb_id=?, year=?, rating=?, genres=?, overview=? WHERE id=?",
            (tmdb_id or 0, year or "", rating or 0, genres or "", overview or "", series_id),
        )
        await db.commit()


async def toggle_publish(series_id: int) -> int:
    _ensure_db()
    async with db_lock:
        cur = await db.execute("SELECT published FROM series WHERE id=?", (series_id,))
        row = await cur.fetchone()
        if not row:
            return 0
        new_val = 0 if int(row[0]) == 1 else 1
        await db.execute("UPDATE series SET published=? WHERE id=?", (new_val, series_id))
        await db.commit()
        return new_val


# ---------- groups ----------
async def ensure_group(series_id: int, lang: str, season: str, quality: str) -> int:
    _ensure_db()
    async with db_lock:
        await db.execute(
            "INSERT OR IGNORE INTO groups(series_id, lang, season, quality) VALUES(?,?,?,?)",
            (series_id, lang.strip(), season.strip(), quality.strip()),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT id FROM groups WHERE series_id=? AND lang=? AND season=? AND quality=?",
            (series_id, lang.strip(), season.strip(), quality.strip()),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def get_group_id_value(series_id: int, lang: str, season: str, quality: str):
    _ensure_db()
    cur = await db.execute(
        "SELECT id FROM groups WHERE series_id=? AND lang=? AND season=? AND quality=?",
        (series_id, lang, season, quality),
    )
    return await cur.fetchone()


async def list_languages(series_id: int):
    _ensure_db()
    cur = await db.execute(
        "SELECT DISTINCT lang FROM groups WHERE series_id=? ORDER BY lang COLLATE NOCASE",
        (series_id,),
    )
    return [r[0] for r in await cur.fetchall()]


async def list_seasons(series_id: int, lang: str):
    _ensure_db()
    cur = await db.execute(
        "SELECT DISTINCT season FROM groups WHERE series_id=? AND lang=? ORDER BY season COLLATE NOCASE",
        (series_id, lang),
    )
    return [r[0] for r in await cur.fetchall()]


async def list_qualities(series_id: int, lang: str, season: str):
    _ensure_db()
    cur = await db.execute(
        "SELECT DISTINCT quality FROM groups WHERE series_id=? AND lang=? AND season=? ORDER BY quality COLLATE NOCASE",
        (series_id, lang, season),
    )
    return [r[0] for r in await cur.fetchall()]


# ---------- delete ----------
async def delete_language(series_id: int, lang: str):
    _ensure_db()
    async with db_lock:
        await db.execute("DELETE FROM groups WHERE series_id=? AND lang=?", (series_id, lang))
        await db.commit()


async def delete_season(series_id: int, lang: str, season: str):
    _ensure_db()
    async with db_lock:
        await db.execute("DELETE FROM groups WHERE series_id=? AND lang=? AND season=?", (series_id, lang, season))
        await db.commit()


async def delete_quality(series_id: int, lang: str, season: str, quality: str):
    _ensure_db()
    async with db_lock:
        await db.execute(
            "DELETE FROM groups WHERE series_id=? AND lang=? AND season=? AND quality=?",
            (series_id, lang, season, quality),
        )
        await db.commit()


# ---------- files ----------
async def add_file(group_id: int, file_id: str, caption: str = "", msg_type: str = ""):
    _ensure_db()
    async with db_lock:
        await db.execute(
            # ✅ INSERT OR IGNORE because we created uq_files_group_file index
            "INSERT OR IGNORE INTO files(group_id, file_id, caption, msg_type) VALUES(?,?,?,?)",
            (group_id, file_id, caption or "", msg_type or ""),
        )
        await db.commit()


async def get_files(group_id: int):
    _ensure_db()
    cur = await db.execute(
        "SELECT file_id, caption, msg_type FROM files WHERE group_id=? ORDER BY id ASC",
        (group_id,),
    )
    return await cur.fetchall()


async def count_files_in_group(group_id: int) -> int:
    _ensure_db()
    if not group_id:
        return 0
    cur = await db.execute("SELECT COUNT(1) FROM files WHERE group_id=?", (group_id,))
    row = await cur.fetchone()
    return int(row[0] or 0)


# ---------- aliases ----------
find_series_by_name = find_series
get_group_id = get_group_id_value
