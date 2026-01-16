import aiosqlite

DB_PATH = "database/series.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS series(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            title_lc TEXT NOT NULL UNIQUE,
            poster_file_id TEXT
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS groups(
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
        CREATE TABLE IF NOT EXISTS files(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            caption TEXT,
            message_type TEXT,
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        );
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_series_title_lc ON series(title_lc);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_groups_series ON groups(series_id);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_files_group ON files(group_id);")
        await db.commit()

# ---------- series ----------
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
        cur = await db.execute("SELECT id, title, poster_file_id FROM series WHERE title_lc=?", (q,))
        return await cur.fetchone()

async def set_series_poster(series_id: int, poster_file_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE series SET poster_file_id=? WHERE id=?", (poster_file_id, series_id))
        await db.commit()

async def get_series_by_id(series_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, title, poster_file_id FROM series WHERE id=?", (series_id,))
        return await cur.fetchone()

# ---------- groups ----------
async def ensure_group(series_id: int, language: str, season: str, quality: str) -> int:
    language = language.strip()
    season = season.strip()
    quality = quality.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO groups(series_id,language,season,quality) VALUES (?,?,?,?)",
            (series_id, language, season, quality)
        )
        await db.commit()
        cur = await db.execute(
            "SELECT id FROM groups WHERE series_id=? AND language=? AND season=? AND quality=?",
            (series_id, language, season, quality)
        )
        row = await cur.fetchone()
        return row[0]

async def list_languages(series_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT language FROM groups WHERE series_id=? ORDER BY language",
            (series_id,)
        )
        return [r[0] for r in await cur.fetchall()]

async def list_seasons(series_id: int, language: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT season FROM groups WHERE series_id=? AND language=? ORDER BY season",
            (series_id, language)
        )
        return [r[0] for r in await cur.fetchall()]

async def list_qualities(series_id: int, language: str, season: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT quality FROM groups WHERE series_id=? AND language=? AND season=? ORDER BY quality",
            (series_id, language, season)
        )
        return [r[0] for r in await cur.fetchall()]

async def get_group_id(series_id: int, language: str, season: str, quality: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM groups WHERE series_id=? AND language=? AND season=? AND quality=?",
            (series_id, language, season, quality)
        )
        return await cur.fetchone()

# ---------- files ----------
async def add_file(group_id: int, file_id: str, caption: str, message_type: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO files(group_id,file_id,caption,message_type) VALUES (?,?,?,?)",
            (group_id, file_id, caption or "", message_type or "")
        )
        await db.commit()

async def get_files(group_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT file_id, caption, message_type FROM files WHERE group_id=? ORDER BY id ASC",
            (group_id,)
        )
        return await cur.fetchall()
