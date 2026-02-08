import aiosqlite
import logging
import asyncio
from pathlib import Path
from typing import Optional, List, Tuple, Any

DB_PATH = Path("database/series.db")
db_lock = asyncio.Lock()
logger = logging.getLogger(__name__)

# Global connection
db: aiosqlite.Connection | None = None


# -------------------------
# internal helper: add columns safely
# -------------------------
async def _add_column_if_missing(table: str, col: str, coltype: str):
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    cur = await db.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in await cur.fetchall()]
    if col not in cols:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        logger.info(f"Added missing column '{col}' to table '{table}'")


async def init_db():
    """
    Initializes SQLite DB + tables + migrations.
    """
    global db
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    db = await aiosqlite.connect(DB_PATH, timeout=30)
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA synchronous=NORMAL;")
    await db.execute("PRAGMA temp_store=MEMORY;")
    await db.execute("PRAGMA foreign_keys=ON;")

    # -------------------------
    # base tables
    # -------------------------
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

    # IMPORTANT: files supports BOTH direct file_id and Telegram pointers
    await db.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,

        -- Direct cached media (optional)
        file_id TEXT,
        caption TEXT,
        msg_type TEXT,

        -- Telegram source pointer (recommended)
        src_chat_id INTEGER,
        src_msg_id INTEGER,

        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
    )
    """)

    # -------------------------
    # migrations (series meta)
    # -------------------------
    await _add_column_if_missing("series", "tmdb_id", "INTEGER")
    await _add_column_if_missing("series", "year", "TEXT")
    await _add_column_if_missing("series", "rating", "REAL")
    await _add_column_if_missing("series", "genres", "TEXT")
    await _add_column_if_missing("series", "overview", "TEXT")

    # -------------------------
    # migrations (files pointers)
    # -------------------------
    await _add_column_if_missing("files", "src_chat_id", "INTEGER")
    await _add_column_if_missing("files", "src_msg_id", "INTEGER")
    await _add_column_if_missing("files", "file_id", "TEXT")
    await _add_column_if_missing("files", "caption", "TEXT")
    await _add_column_if_missing("files", "msg_type", "TEXT")

    # -------------------------
    # indexes
    # -------------------------
    await db.execute("CREATE INDEX IF NOT EXISTS idx_series_title ON series(title)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_groups_series ON groups(series_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_files_group ON files(group_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_files_src ON files(src_chat_id, src_msg_id)")

    await db.commit()
    logger.info("✅ Database initialized")


# ---------- series ----------
async def upsert_series(title: str) -> int:
    """
    Insert series if missing and return series_id.
    """
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    t = (title or "").strip()
    if not t:
        return 0

    async with db_lock:
        await db.execute("INSERT OR IGNORE INTO series(title) VALUES(?)", (t,))
        await db.commit()

        cur = await db.execute("SELECT id FROM series WHERE title=?", (t,))
        row = await cur.fetchone()
        sid = int(row[0]) if row else 0

        logger.info(f"📌 Upserted series '{t}' (id={sid})")
        return sid


async def get_series_by_id(series_id: int):
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    cur = await db.execute(
        "SELECT id, title, poster_file_id, published, tmdb_id, year, rating, genres, overview "
        "FROM series WHERE id=?",
        (series_id,),
    )
    return await cur.fetchone()


async def find_series(query: str):
    """
    Find by title LIKE (returns 1 latest match).
    """
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    q = (query or "").strip()
    if not q:
        return None

    cur = await db.execute(
        "SELECT id, title, poster_file_id, published, tmdb_id, year, rating, genres, overview "
        "FROM series WHERE title LIKE ? ORDER BY id DESC LIMIT 1",
        (f"%{q}%",),
    )
    return await cur.fetchone()


async def set_series_poster(series_id: int, poster_file_id: str):
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    async with db_lock:
        await db.execute("UPDATE series SET poster_file_id=? WHERE id=?", (poster_file_id, series_id))
        await db.commit()


async def set_series_meta(series_id: int, tmdb_id: int, year: str, rating: float, genres: str, overview: str):
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    async with db_lock:
        await db.execute(
            "UPDATE series SET tmdb_id=?, year=?, rating=?, genres=?, overview=? WHERE id=?",
            (tmdb_id or 0, year or "", rating or 0, genres or "", overview or "", series_id),
        )
        await db.commit()


async def toggle_publish(series_id: int) -> int:
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

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
    """
    Ensure group exists and return group_id.
    """
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    l = (lang or "Unknown").strip() or "Unknown"
    s = (season or "S01").strip() or "S01"
    q = (quality or "Unknown").strip() or "Unknown"

    async with db_lock:
        await db.execute(
            "INSERT OR IGNORE INTO groups(series_id, lang, season, quality) VALUES(?,?,?,?)",
            (series_id, l, s, q),
        )
        await db.commit()

        cur = await db.execute(
            "SELECT id FROM groups WHERE series_id=? AND lang=? AND season=? AND quality=?",
            (series_id, l, s, q),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def get_group_id_value(series_id: int, lang: str, season: str, quality: str):
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    cur = await db.execute(
        "SELECT id FROM groups WHERE series_id=? AND lang=? AND season=? AND quality=?",
        (series_id, lang, season, quality),
    )
    return await cur.fetchone()


async def list_languages(series_id: int) -> List[str]:
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    cur = await db.execute(
        "SELECT DISTINCT lang FROM groups WHERE series_id=? ORDER BY lang COLLATE NOCASE",
        (series_id,),
    )
    return [r[0] for r in await cur.fetchall()]


async def list_seasons(series_id: int, lang: str) -> List[str]:
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    cur = await db.execute(
        "SELECT DISTINCT season FROM groups WHERE series_id=? AND lang=? ORDER BY season COLLATE NOCASE",
        (series_id, lang),
    )
    return [r[0] for r in await cur.fetchall()]


async def list_qualities(series_id: int, lang: str, season: str) -> List[str]:
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    cur = await db.execute(
        "SELECT DISTINCT quality FROM groups WHERE series_id=? AND lang=? AND season=? ORDER BY quality COLLATE NOCASE",
        (series_id, lang, season),
    )
    return [r[0] for r in await cur.fetchall()]


# ---------- delete ----------
async def delete_language(series_id: int, lang: str):
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    async with db_lock:
        await db.execute("DELETE FROM groups WHERE series_id=? AND lang=?", (series_id, lang))
        await db.commit()


async def delete_season(series_id: int, lang: str, season: str):
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    async with db_lock:
        await db.execute("DELETE FROM groups WHERE series_id=? AND lang=? AND season=?", (series_id, lang, season))
        await db.commit()


async def delete_quality(series_id: int, lang: str, season: str, quality: str):
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    async with db_lock:
        await db.execute(
            "DELETE FROM groups WHERE series_id=? AND lang=? AND season=? AND quality=?",
            (series_id, lang, season, quality),
        )
        await db.commit()


# ---------- files ----------
async def add_file(group_id: int, file_id: str, caption: str = "", msg_type: str = ""):
    """
    Optional fallback: store direct Telegram file_id (cached media).
    """
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    fid = (file_id or "").strip()
    if not fid:
        return

    async with db_lock:
        await db.execute(
            "INSERT INTO files(group_id, file_id, caption, msg_type) VALUES(?,?,?,?)",
            (group_id, fid, caption or "", msg_type or ""),
        )
        await db.commit()


async def add_message_pointer(group_id: int, src_chat_id: int, src_msg_id: int, caption: str = "", msg_type: str = ""):
    """
    Recommended: store where the real media exists (channel_id + message_id).
    Later, bot will copy_message() from that channel.
    """
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    async with db_lock:
        await db.execute(
            "INSERT INTO files(group_id, src_chat_id, src_msg_id, caption, msg_type) VALUES(?,?,?,?,?)",
            (group_id, int(src_chat_id), int(src_msg_id), caption or "", msg_type or ""),
        )
        await db.commit()


async def get_files(group_id: int):
    """
    Returns list of rows:
      (file_id, caption, msg_type, src_chat_id, src_msg_id)
    """
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    cur = await db.execute(
        "SELECT file_id, caption, msg_type, src_chat_id, src_msg_id "
        "FROM files WHERE group_id=? ORDER BY id ASC",
        (group_id,),
    )
    return await cur.fetchall()


async def count_files_in_group(group_id: int) -> int:
    global db
    if db is None:
        raise RuntimeError("DB is not initialized")

    if not group_id:
        return 0
    cur = await db.execute("SELECT COUNT(1) FROM files WHERE group_id=?", (group_id,))
    row = await cur.fetchone()
    return int(row[0] or 0)


# ---------- aliases ----------
find_series_by_name = find_series
get_group_id = get_group_id_value
