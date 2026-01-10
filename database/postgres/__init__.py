# database/postgres/__init__.py

import os
import json
import asyncpg
import logging
from typing import Optional, List, Tuple, Dict, Any

from info import pgHost, pgDbname, pgPassword, pgPort, pgUsername

from aiocache import cached, Cache
from aiocache.serializers import PickleSerializer
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# NOTE: In your working bot you used pgHost as redis host; keeping symmetry.
REDIS_CONFIG = {
    "endpoint": os.getenv("REDIS_HOST", pgHost),
    "port": int(os.getenv("REDIS_PORT", 6379)),
    "password": os.getenv("REDIS_PASSWORD", "root"),
    "namespace": os.getenv("REDIS_NAMESPACE", "seriesredis"),
}

def _kb(prefix: str):
    # aiocache key_builder signature: (func, *args, **kwargs), args[0] is self
    def builder(func, *args, **kwargs):
        tail = ":".join(str(a) for a in args[1:])  # skip self
        if kwargs:
            tail += ":" + ":".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return f"{prefix}:{tail}" if tail else prefix
    return builder


class PostgreSQLManager:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    async def connect(self):
        self.pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=50)
        await self.create_all_tables()
        logger.info("✅ PostgreSQL connected and tables initialized")

    async def create_all_tables(self):
        table_queries = [
            # ---- Series document storage (JSONB) ----
            """
            CREATE TABLE IF NOT EXISTS series (
                series_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                published BOOLEAN DEFAULT FALSE,
                doc JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_assignments (
                user_id BIGINT PRIMARY KEY,
                channel_id BIGINT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,

            # ---- Per-group gfilters (replaces "collection-per-group" in Mongo) ----
            """
            CREATE TABLE IF NOT EXISTS gfilters (
                group_id BIGINT NOT NULL,
                text TEXT NOT NULL,
                reply TEXT,
                btn TEXT,
                file TEXT,
                alert TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_id, text)
            )
            """,

            # ---- Users/Groups/Settings (matches your users_chats_db needs) ----
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                is_banned BOOLEAN DEFAULT FALSE,
                ban_reason TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS groups (
                id BIGINT PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                is_disabled BOOLEAN DEFAULT FALSE,
                reason TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS group_settings (
                group_id BIGINT PRIMARY KEY REFERENCES groups(id) ON DELETE CASCADE,
                button_enabled BOOLEAN DEFAULT TRUE,
                botpm_enabled BOOLEAN DEFAULT TRUE,
                file_secure BOOLEAN DEFAULT FALSE,
                imdb BOOLEAN DEFAULT TRUE,
                spell_check BOOLEAN DEFAULT TRUE,
                welcome_enabled BOOLEAN DEFAULT FALSE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,

            # ---- Forcesub request storage ----
            """
            CREATE TABLE IF NOT EXISTS req_one (
                user_id BIGINT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS req_two (
                user_id BIGINT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,

            # ---- JoinReqs "ChatId1/ChatId2" equivalent ----
            """
            CREATE TABLE IF NOT EXISTS fsub_chats (
                channel_no SMALLINT PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ]

        index_queries = [
            "CREATE EXTENSION IF NOT EXISTS pg_trgm",
            "CREATE INDEX IF NOT EXISTS idx_series_title_trgm ON series USING GIN (LOWER(title) gin_trgm_ops)",
            "CREATE INDEX IF NOT EXISTS idx_series_updated_at ON series (updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_gfilters_text_trgm ON gfilters USING GIN (LOWER(text) gin_trgm_ops)",
            "CREATE INDEX IF NOT EXISTS idx_users_is_banned ON users (is_banned)",
            "CREATE INDEX IF NOT EXISTS idx_groups_is_disabled ON groups (is_disabled)",
        ]

        async with self.pool.acquire() as conn:
            for q in table_queries + index_queries:
                await conn.execute(q)


class PgDb:
    def __init__(self):
        self.dsn = f"postgresql://{pgUsername}:{pgPassword}@{pgHost}:{pgPort}/{pgDbname}"
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        manager = PostgreSQLManager(self.dsn)
        await manager.connect()
        self.pool = manager.pool

    # ---------------- core helpers ----------------

    async def execute_fetchval(self, query: str, *args):
        try:
            async with self.pool.acquire() as conn:
                return await conn.fetchval(query, *args)
        except Exception as e:
            logger.error(f"❌ Error in fetchval: {e}")
            return None

    async def execute_fetchrow(self, query: str, *args):
        try:
            async with self.pool.acquire() as conn:
                return await conn.fetchrow(query, *args)
        except Exception as e:
            logger.error(f"❌ Error in fetchrow: {e}")
            return None

    async def execute_fetch(self, query: str, *args):
        try:
            async with self.pool.acquire() as conn:
                return await conn.fetch(query, *args)
        except Exception as e:
            logger.error(f"❌ Error in fetch: {e}")
            return []

    async def execute(self, query: str, *args):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, *args)
        except Exception as e:
            logger.error(f"❌ Error in execute: {e}")

    # ---------------- series (JSONB) ----------------

    async def upsert_series_doc(self, series_key: str, doc: Dict[str, Any]) -> bool:
        title = str(doc.get("title") or "")
        published = bool(doc.get("published", False))
        payload = json.dumps(doc, default=str)
        await self.execute(
            """
            INSERT INTO series (series_key, title, published, doc)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (series_key) DO UPDATE SET
                title = EXCLUDED.title,
                published = EXCLUDED.published,
                doc = EXCLUDED.doc,
                updated_at = CURRENT_TIMESTAMP
            """,
            series_key, title, published, payload
        )
        return True

    async def delete_series(self, series_key: str) -> bool:
        await self.execute("DELETE FROM series WHERE series_key = $1", series_key)
        return True

    @cached(ttl=180, cache=Cache.REDIS, **REDIS_CONFIG, serializer=PickleSerializer(), key_builder=_kb("series:get"))
    async def get_series_doc(self, series_key: str) -> Optional[Dict[str, Any]]:
        row = await self.execute_fetchrow("SELECT doc FROM series WHERE series_key = $1", series_key)
        return dict(row["doc"]) if row else None

    async def get_all_series(self, limit: int = 500, offset: int = 0) -> List[Dict[str, Any]]:
        rows = await self.execute_fetch(
            "SELECT doc FROM series ORDER BY updated_at DESC LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [dict(r["doc"]) for r in rows]

    async def search_series(self, query: str, limit: int = 25, offset: int = 0) -> List[Dict[str, Any]]:
        rows = await self.execute_fetch(
            """
            SELECT doc FROM series
            WHERE LOWER(title) ILIKE $1
            ORDER BY updated_at DESC
            LIMIT $2 OFFSET $3
            """,
            f"%{query.lower()}%", limit, offset
        )
        return [dict(r["doc"]) for r in rows]

    # ---------------- admin assignments ----------------

    async def upsert_admin_assignment(self, user_id: int, channel_id: int) -> bool:
        await self.execute(
            """
            INSERT INTO admin_assignments (user_id, channel_id)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET
                channel_id = EXCLUDED.channel_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            int(user_id), int(channel_id)
        )
        return True

    async def remove_admin_assignment(self, user_id: int) -> bool:
        await self.execute("DELETE FROM admin_assignments WHERE user_id = $1", int(user_id))
        return True

    @cached(ttl=120, cache=Cache.REDIS, **REDIS_CONFIG,seriesredis=PickleSerializer(), key_builder=_kb("admin:get"))
    async def get_admin_channel(self, user_id: int) -> Optional[int]:
        return await self.execute_fetchval(
            "SELECT channel_id FROM admin_assignments WHERE user_id = $1",
            int(user_id)
        )

    async def get_admin_assignments(self) -> Dict[int, int]:
        rows = await self.execute_fetch("SELECT user_id, channel_id FROM admin_assignments")
        return {int(r["user_id"]): int(r["channel_id"]) for r in rows}

    # ---------------- gfilters ----------------

    async def upsert_gfilter(self, group_id: int, text: str, reply: str, btn: str, file: str, alert: str) -> bool:
        await self.execute(
            """
            INSERT INTO gfilters (group_id, text, reply, btn, file, alert)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (group_id, text) DO UPDATE SET
                reply = EXCLUDED.reply,
                btn = EXCLUDED.btn,
                file = EXCLUDED.file,
                alert = EXCLUDED.alert,
                updated_at = CURRENT_TIMESTAMP
            """,
            int(group_id), str(text), str(reply), str(btn), str(file), str(alert)
        )
        return True

    async def delete_gfilter(self, group_id: int, text: str) -> bool:
        await self.execute("DELETE FROM gfilters WHERE group_id = $1 AND text = $2", int(group_id), str(text))
        return True

    async def delete_all_gfilters(self, group_id: int) -> bool:
        await self.execute("DELETE FROM gfilters WHERE group_id = $1", int(group_id))
        return True

    @cached(ttl=300, cache=Cache.REDIS, **REDIS_CONFIG, serializer=PickleSerializer(), key_builder=_kb("gfilters:list"))
    async def get_gfilters(self, group_id: int) -> List[str]:
        rows = await self.execute_fetch(
            "SELECT text FROM gfilters WHERE group_id = $1 ORDER BY created_at DESC",
            int(group_id)
        )
        return [r["text"] for r in rows]

    @cached(ttl=300, cache=Cache.REDIS, **REDIS_CONFIG, serializer=PickleSerializer(), key_builder=_kb("gfilters:find"))
    async def find_gfilter(self, group_id: int, name: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        row = await self.execute_fetchrow(
            "SELECT reply, btn, alert, file FROM gfilters WHERE group_id = $1 AND text = $2",
            int(group_id), str(name)
        )
        if row:
            return row["reply"], row["btn"], row["alert"], row["file"]
        return None, None, None, None

    async def count_gfilters(self, group_id: int) -> int:
        return int(await self.execute_fetchval("SELECT COUNT(*) FROM gfilters WHERE group_id = $1", int(group_id)) or 0)

    async def gfilter_stats(self) -> Tuple[int, int]:
        total_groups = int(await self.execute_fetchval("SELECT COUNT(DISTINCT group_id) FROM gfilters") or 0)
        total_filters = int(await self.execute_fetchval("SELECT COUNT(*) FROM gfilters") or 0)
        return total_groups, total_filters

    # ---------------- join req chats ----------------

    async def set_fsub_chat(self, channel_no: int, chat_id: int) -> bool:
        await self.execute(
            """
            INSERT INTO fsub_chats (channel_no, chat_id)
            VALUES ($1, $2)
            ON CONFLICT (channel_no) DO UPDATE SET
                chat_id = EXCLUDED.chat_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            int(channel_no), int(chat_id)
        )
        return True

    @cached(ttl=120, cache=Cache.REDIS, **REDIS_CONFIG, serializer=PickleSerializer(), key_builder=_kb("fsub:chat"))
    async def get_fsub_chat(self, channel_no: int) -> Optional[Dict[str, int]]:
        row = await self.execute_fetchrow("SELECT chat_id FROM fsub_chats WHERE channel_no = $1", int(channel_no))
        return {"chat_id": int(row["chat_id"])} if row else None

    async def delete_fsub_chat(self, channel_no: int, chat_id: int) -> bool:
        await self.execute("DELETE FROM fsub_chats WHERE channel_no = $1 AND chat_id = $2", int(channel_no), int(chat_id))
        return True

    # ---------------- request_forcesub ----------------

    async def add_req(self, which: int, user_id: int) -> bool:
        table = "req_one" if which == 1 else "req_two"
        await self.execute(f"INSERT INTO {table} (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", int(user_id))
        return True

    async def get_req(self, which: int, user_id: int) -> Optional[Dict[str, int]]:
        table = "req_one" if which == 1 else "req_two"
        exists = await self.execute_fetchval(f"SELECT EXISTS(SELECT 1 FROM {table} WHERE user_id = $1)", int(user_id))
        return {"user_id": int(user_id)} if exists else None

    async def delete_all_req(self, which: int) -> bool:
        table = "req_one" if which == 1 else "req_two"
        await self.execute(f"DELETE FROM {table}")
        return True

    # ---------------- users/chats ----------------

    async def upsert_user(self, user_id: int, name: str) -> bool:
        await self.execute(
            """
            INSERT INTO users (id, name)
            VALUES ($1, $2)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                updated_at = CURRENT_TIMESTAMP
            """,
            int(user_id), str(name)
        )
        return True

    @cached(ttl=180, cache=Cache.REDIS, **REDIS_CONFIG, serializer=PickleSerializer(), key_builder=_kb("users:exists"))
    async def is_user_exist(self, user_id: int) -> bool:
        return bool(await self.execute_fetchval("SELECT EXISTS(SELECT 1 FROM users WHERE id = $1)", int(user_id)) or False)

    async def total_users_count(self) -> int:
        return int(await self.execute_fetchval("SELECT COUNT(*) FROM users") or 0)

    async def set_ban(self, user_id: int, is_banned: bool, ban_reason: str = "") -> bool:
        await self.execute(
            """
            UPDATE users
            SET is_banned = $2, ban_reason = $3, updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            int(user_id), bool(is_banned), str(ban_reason or "")
        )
        return True

    @cached(ttl=180, cache=Cache.REDIS, **REDIS_CONFIG, serializer=PickleSerializer(), key_builder=_kb("users:ban"))
    async def get_ban_status(self, user_id: int) -> Dict[str, Any]:
        row = await self.execute_fetchrow("SELECT is_banned, ban_reason FROM users WHERE id = $1", int(user_id))
        if not row:
            return {"is_banned": False, "ban_reason": ""}
        return {"is_banned": bool(row["is_banned"]), "ban_reason": row["ban_reason"] or ""}

    async def delete_user(self, user_id: int) -> bool:
        await self.execute("DELETE FROM users WHERE id = $1", int(user_id))
        return True

    async def upsert_group(self, chat_id: int, title: str) -> bool:
        await self.execute(
            """
            INSERT INTO groups (id, title)
            VALUES ($1, $2)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                updated_at = CURRENT_TIMESTAMP
            """,
            int(chat_id), str(title)
        )
        # ensure settings row exists
        await self.execute("INSERT INTO group_settings (group_id) VALUES ($1) ON CONFLICT (group_id) DO NOTHING", int(chat_id))
        return True

    async def set_group_disabled(self, chat_id: int, is_disabled: bool, reason: str = "") -> bool:
        await self.execute(
            """
            UPDATE groups
            SET is_disabled = $2, reason = $3, updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            int(chat_id), bool(is_disabled), str(reason or "")
        )
        return True

    @cached(ttl=180, cache=Cache.REDIS, **REDIS_CONFIG, serializer=PickleSerializer(), key_builder=_kb("groups:status"))
    async def get_chat_status(self, chat_id: int) -> Optional[Dict[str, Any]]:
        row = await self.execute_fetchrow("SELECT is_disabled, reason FROM groups WHERE id = $1", int(chat_id))
        if not row:
            return None
        return {"is_disabled": bool(row["is_disabled"]), "reason": row["reason"] or ""}

    async def delete_chat(self, chat_id: int) -> bool:
        await self.execute("DELETE FROM groups WHERE id = $1", int(chat_id))
        return True

    async def update_settings(self, chat_id: int, settings: Dict[str, Any]) -> bool:
        # mapping from your users_chats_db keys
        await self.execute(
            """
            UPDATE group_settings
            SET button_enabled = $2,
                botpm_enabled = $3,
                file_secure = $4,
                imdb = $5,
                spell_check = $6,
                welcome_enabled = $7,
                updated_at = CURRENT_TIMESTAMP
            WHERE group_id = $1
            """,
            int(chat_id),
            bool(settings.get("button", True)),
            bool(settings.get("botpm", True)),
            bool(settings.get("file_secure", False)),
            bool(settings.get("imdb", True)),
            bool(settings.get("spell_check", True)),
            bool(settings.get("welcome", False)),
        )
        return True

    @cached(ttl=180, cache=Cache.REDIS, **REDIS_CONFIG, serializer=PickleSerializer(), key_builder=_kb("groups:settings"))
    async def get_settings(self, chat_id: int) -> Dict[str, Any]:
        default = {
            "button": True,
            "botpm": True,
            "file_secure": False,
            "imdb": True,
            "spell_check": True,
            "welcome": False,
        }
        row = await self.execute_fetchrow(
            """
            SELECT button_enabled, botpm_enabled, file_secure, imdb, spell_check, welcome_enabled
            FROM group_settings WHERE group_id = $1
            """,
            int(chat_id)
        )
        if not row:
            return default
        return {
            "button": bool(row["button_enabled"]),
            "botpm": bool(row["botpm_enabled"]),
            "file_secure": bool(row["file_secure"]),
            "imdb": bool(row["imdb"]),
            "spell_check": bool(row["spell_check"]),
            "welcome": bool(row["welcome_enabled"]),
        }

    async def get_banned(self) -> Tuple[List[int], List[int]]:
        users = await self.execute_fetch("SELECT id FROM users WHERE is_banned = TRUE")
        chats = await self.execute_fetch("SELECT id FROM groups WHERE is_disabled = TRUE")
        return [int(u["id"]) for u in users], [int(c["id"]) for c in chats]

    async def get_all_users(self, skip: int = 0, limit: int = 1000) -> List[Dict[str, Any]]:
        rows = await self.execute_fetch(
            """
            SELECT id, name, is_banned, ban_reason, created_at, updated_at
            FROM users
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            int(limit), int(skip)
        )
        return [dict(r) for r in rows]

    async def get_all_chats(self, skip: int = 0, limit: int = 1000) -> List[Dict[str, Any]]:
        rows = await self.execute_fetch(
            """
            SELECT id, title, is_disabled, reason, created_at, updated_at
            FROM groups
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            int(limit), int(skip)
        )
        return [dict(r) for r in rows]


pgDb = PgDb()
