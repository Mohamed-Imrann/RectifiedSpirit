import aiosqlite

DB_PATH = "database/series.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS series(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            title_lc TEXT NOT NULL UNIQUE
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS episodes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            caption TEXT,
            message_type TEXT,
            FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE
        );
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_series_title_lc ON series(title_lc);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ep_series_id ON episodes(series_id);")
        await db.commit()

async def upsert_series(title: str) -> int:
    title = title.strip()
    title_lc = title.lower().strip()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO series(title, title_lc) VALUES (?,?)",
            (title, title_lc)
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM series WHERE title_lc=?", (title_lc,))
        row = await cur.fetchone()
        return row[0]

async def find_series(query: str):
    q = query.lower().strip()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, title FROM series WHERE title_lc=?", (q,))
        return await cur.fetchone()

async def add_episode(series_id: int, file_id: str, caption: str | None, message_type: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO episodes(series_id, file_id, caption, message_type) VALUES (?,?,?,?)",
            (series_id, file_id, caption or "", message_type or "")
        )
        await db.commit()

async def get_episodes(series_id: int, limit: int = 50):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT file_id, caption, message_type FROM episodes WHERE series_id=? ORDER BY id ASC LIMIT ?",
            (series_id, limit)
        )
        return await cur.fetchall()

async def list_series(limit: int = 200):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT title FROM series ORDER BY title_lc LIMIT ?", (limit,))
        return await cur.fetchall()

async def delete_series(title: str) -> int:
    title_lc = title.lower().strip()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM series WHERE title_lc=?", (title_lc,))
        await db.commit()
        return cur.rowcount
