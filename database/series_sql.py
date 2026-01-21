import aiosqlite
import logging
from pathlib import Path

DB_PATH = Path("database/series.db")

logger = logging.getLogger(__name__)


# -------------------------
# internal helper: add columns safely
# -------------------------
async def _add_column_if_missing(db: aiosqlite.Connection, table: str, col: str, coltype: str):
    cur = await db.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in await cur.fetchall()]  # r[1] = name
    if col not in cols:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        logger.info(f"Added missing column '{col}' to table '{table}'")


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
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

        # ---- MIGRATION: TMDB meta columns (add if missing) ----
        await _add_column_if_missing(db, "series", "tmdb_id", "INTEGER")
        await _add_column_if_missing(db, "series", "year", "TEXT")
        await _add_column_if_missing(db, "series", "rating", "REAL")
        await _add_column_if_missing(db, "series", "genres", "TEXT")
        await _add_column_if_missing(db, "series", "overview", "TEXT")

        # indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_series_title ON series(title)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_groups_series ON groups(series_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_files_group ON files(group_id)")

        await db.commit()
        logger.info("✅ Database initialized")


# ---------- series ----------
async def upsert_series(title: str) -> int:
    title = (title or "").strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO series(title) VALUES(?)", (title,))
        await db.commit()
        cur = await db.execute("SELECT id FROM series WHERE title=?", (title,))
        row = await cur.fetchone()
        sid = int(row[0]) if row else 0
        logger.info(f"📌 Upserted series '{title}' (id={sid})")
        return sid


async def get_series_by_id(series_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, title, poster_file_id, published, tmdb_id, year, rating, genres, overview "
            "FROM series WHERE id=?",
            (series_id,),
        )
        row = await cur.fetchone()
        logger.debug(f"Fetched series id={series_id}: {row}")
        return row


async def find_series(query: str):
    q = (query or "").strip()
    if not q:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, title, poster_file_id, published, tmdb_id, year, rating, genres, overview "
            "FROM series WHERE title LIKE ? ORDER BY id DESC LIMIT 1",
            (f"%{q}%",),
        )
        row = await cur.fetchone()
        logger.debug(f"Search for '{q}' returned: {row}")
        return row


async def set_series_poster(series_id: int, poster_file_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE series SET poster_file_id=? WHERE id=?",
            (poster_file_id, series_id),
        )
        await db.commit()
        logger.info(f"🖼 Poster updated for series id={series_id}")


async def set_series_meta(series_id: int, tmdb_id: int, year: str, rating: float, genres: str, overview: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE series SET tmdb_id=?, year=?, rating=?, genres=?, overview=? WHERE id=?",
            (int(tmdb_id or 0), (year or ""), float(rating or 0), (genres or ""), (overview or ""), series_id),
        )
        await db.commit()
        logger.info(f"🎬 Meta updated for series id={series_id}")


async def toggle_publish(series_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT published FROM series WHERE id=?", (series_id,))
        row = await cur.fetchone()
        if not row:
            return 0
        new_val = 0 if int(row[0]) == 1 else 1
        await db.execute("UPDATE series SET published=? WHERE id=?", (new_val, series_id))
        await db.commit()
        logger.info(f"🔄 Publish toggled for series id={series_id} -> {new_val}")
        return new_val


# ---------- groups ----------
async def ensure_group(series_id: int, lang: str, season: str, quality: str) -> int:
    lang, season, quality = (lang or "").strip(), (season or "").strip(), (quality or "").strip()

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
        gid = int(row[0]) if row else 0
        logger.info(f"✅ Ensured group sid={series_id}, lang={lang}, season={season}, quality={quality}, id={gid}")
        return gid


async def get_group_id_value(series_id: int, lang: str, season: str, quality: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM groups WHERE series_id=? AND lang=? AND season=? AND quality=?",
            (series_id, lang, season, quality),
        )
        row = await cur.fetchone()
        logger.debug(f"Group lookup sid={series_id}, lang={lang}, season={season}, quality={quality} -> {row}")
        return row


async def list_languages(series_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT lang FROM groups WHERE series_id=? ORDER BY lang COLLATE NOCASE",
            (series_id,),
        )
        rows = await cur.fetchall()
        langs = [r[0] for r in rows]
        logger.debug(f"Languages for series id={series_id}: {langs}")
        return langs


async def list_seasons(series_id: int, lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT season FROM groups WHERE series_id=? AND lang=? ORDER BY season COLLATE NOCASE",
            (series_id, lang),
        )
        rows = await cur.fetchall()
        seasons = [r[0] for r in rows]
        logger.debug(f"Seasons for sid={series_id}, lang={lang}: {seasons}")
        return seasons


async def list_qualities(series_id: int, lang: str, season: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT quality FROM groups WHERE series_id=? AND lang=? AND season=? ORDER BY quality COLLATE NOCASE",
            (series_id, lang, season),
        )
        rows = await cur.fetchall()
        qualities = [r[0] for r in rows]
        logger.debug(f"Qualities for sid={series_id}, lang={lang}, season={season}: {qualities}")
        return qualities
