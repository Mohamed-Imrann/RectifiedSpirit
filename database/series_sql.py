# database/series_sql.py
import os
import aiosqlite
from typing import List, Optional, Tuple

DB_PATH = os.getenv("DB_PATH", "series.db")


async def _column_exists(db: aiosqlite.Connection, table: str, col: str) -> bool:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return any(r[1] == col for r in rows)


# ----------------- DB INIT -----------------

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            poster TEXT
        );
        """)

        # ✅ add published column if missing (migration)
        if not await _column_exists(db, "series", "published"):
            await db.execute("ALTER TABLE series ADD COLUMN published INTEGER NOT NULL DEFAULT 0;")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER NOT NULL,
            language TEXT NOT NULL,
            season TEXT NOT NULL,
            quality TEXT NOT NULL,
            UNIQUE(series_id, language, season, quality),
            FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            caption TEXT,
            msg_type TEXT,
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        );
        """)

        # Speed indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_series_title ON series(title);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_series_pub ON series(published);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_groups_sid_lang ON groups(series_id, language);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_groups_sid_lang_season ON groups(series_id, language, season);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_files_group ON files(group_id);")

        await db.commit()


# ----------------- SERIES -----------------

async def upsert_series(title: str) -> int:
    title = (title or "").strip()
    if not title:
        raise ValueError("Empty title")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        cur = await db.execute(
            "SELECT id FROM series WHERE lower(title)=lower(?)",
            (title,)
        )
        row = await cur.fetchone()
        if row:
            return int(row[0])

        cur = await db.execute(
            "INSERT INTO series (title, published) VALUES (?, 0)",
            (title,)
        )
        await db.commit()
        return int(cur.lastrowid)


async def set_series_poster(series_id: int, poster_file_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(
            "UPDATE series SET poster=? WHERE id=?",
            (poster_file_id, series_id)
        )
        await db.commit()


async def get_series_by_id(series_id: int) -> Optional[Tuple[int, str, Optional[str], int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, title, poster, published FROM series WHERE id=?", (series_id,))
        row = await cur.fetchone()
        return (int(row[0]), row[1], row[2], int(row[3])) if row else None


async def find_series(query: str, published_only: bool = True) -> Optional[Tuple[int, str, Optional[str]]]:
    q = (query or "").strip()
    if not q:
        return None

    async with aiosqlite.connect(DB_PATH) as db:
        if published_only:
            cur = await db.execute(
                "SELECT id, title, poster FROM series "
                "WHERE published=1 AND lower(title) LIKE lower(?) "
                "ORDER BY id DESC LIMIT 1",
                (f"%{q}%",)
            )
        else:
            cur = await db.execute(
                "SELECT id, title, poster FROM series "
                "WHERE lower(title) LIKE lower(?) "
                "ORDER BY id DESC LIMIT 1",
                (f"%{q}%",)
            )
        row = await cur.fetchone()
        return (int(row[0]), row[1], row[2]) if row else None


async def toggle_publish(series_id: int) -> int:
    """returns new published value (0/1)"""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT published FROM series WHERE id=?", (series_id,))
        row = await cur.fetchone()
        if not row:
            return 0
        new_val = 0 if int(row[0]) == 1 else 1
        await db.execute("UPDATE series SET published=? WHERE id=?", (new_val, series_id))
        await db.commit()
        return new_val


# ----------------- LISTING -----------------

async def list_languages(series_id: int) -> List[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT language FROM groups WHERE series_id=? ORDER BY language COLLATE NOCASE",
            (series_id,)
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def list_seasons(series_id: int, language: str) -> List[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT season FROM groups WHERE series_id=? AND language=? ORDER BY season COLLATE NOCASE",
            (series_id, language)
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def list_qualities(series_id: int, language: str, season: str) -> List[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT quality FROM groups WHERE series_id=? AND language=? AND season=? ORDER BY quality COLLATE NOCASE",
            (series_id, language, season)
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


# ----------------- GROUP / FILES -----------------

async def ensure_group(series_id: int, language: str, season: str, quality: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        cur = await db.execute(
            "SELECT id FROM groups WHERE series_id=? AND language=? AND season=? AND quality=?",
            (series_id, language, season, quality)
        )
        row = await cur.fetchone()
        if row:
            return int(row[0])

        cur = await db.execute(
            "INSERT INTO groups(series_id, language, season, quality) VALUES(?,?,?,?)",
            (series_id, language, season, quality)
        )
        await db.commit()
        return int(cur.lastrowid)


async def get_group_id_value(series_id: int, language: str, season: str, quality: str) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM groups WHERE series_id=? AND language=? AND season=? AND quality=?",
            (series_id, language, season, quality)
        )
        row = await cur.fetchone()
        return int(row[0]) if row else None


async def add_file(group_id: int, file_id: str, caption: str = "", msg_type: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(
            "INSERT INTO files(group_id, file_id, caption, msg_type) VALUES(?,?,?,?)",
            (group_id, file_id, caption or "", msg_type or "")
        )
        await db.commit()


async def get_files(group_id: int) -> List[Tuple[str, str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT file_id, caption, msg_type FROM files WHERE group_id=? ORDER BY id ASC",
            (group_id,)
        )
        rows = await cur.fetchall()
        return [(r[0], r[1], r[2]) for r in rows]


async def count_files_in_group(group_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM files WHERE group_id=?", (group_id,))
        row = await cur.fetchone()
        return int(row[0] or 0)


# ----------------- DELETE GROUPS -----------------

async def delete_language(series_id: int, language: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        cur = await db.execute(
            "DELETE FROM groups WHERE series_id=? AND language=?",
            (series_id, language)
        )
        await db.commit()
        return cur.rowcount


async def delete_season(series_id: int, language: str, season: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        cur = await db.execute(
            "DELETE FROM groups WHERE series_id=? AND language=? AND season=?",
            (series_id, language, season)
        )
        await db.commit()
        return cur.rowcount


async def delete_quality(series_id: int, language: str, season: str, quality: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        cur = await db.execute(
            "DELETE FROM groups WHERE series_id=? AND language=? AND season=? AND quality=?",
            (series_id, language, season, quality)
        )
        await db.commit()
        return cur.rowcount
