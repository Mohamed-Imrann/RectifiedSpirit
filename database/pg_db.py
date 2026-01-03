# database/pg_db.py
import os
import asyncpg
import logging
import asyncio
import json
from typing import Optional, List, Tuple, Dict, Any
from contextlib import asynccontextmanager
from info import pgHost, pgDbname, pgPassword, pgPort, pgUsername, REDIS_HOST, REDIS_PORT, REDIS_PASSWORD

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Redis config for aiocache
REDIS_CONFIG = {
    'endpoint': REDIS_HOST,  # Use Redis host, not PostgreSQL host!
    'port': REDIS_PORT,
    'password': REDIS_PASSWORD,
    'namespace': 'spidybot'
}


class PostgresDB:
    """PostgreSQL database handler with connection pooling."""
    
    def __init__(self, dsn: str = None):
        if dsn:
            self.dsn = dsn
        else:
            # Build DSN from individual parameters
            self.dsn = f"postgres://{pgUsername}:{pgPassword}@{pgHost}:{pgPort}/{pgDbname}?sslmode=disable"
        self.pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        """Initialize connection pool."""
        if self.pool:
            return
        
        try:
            self.pool = await asyncpg.create_pool(
                self.dsn,
                min_size=5,
                max_size=20,
                command_timeout=60,
                statement_cache_size=100
            )
            await self._init_schema()
            logger.info("✅ PostgreSQL pool initialized successfully")
        except Exception as e:
            logger.error(f"❌ PostgreSQL connection failed: {e}")
            raise
    
    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None
            logger.info("PostgreSQL pool closed")
    
    @asynccontextmanager
    async def acquire(self):
        """Acquire connection from pool."""
        if not self.pool:
            raise RuntimeError("Database pool not initialized. Call connect() first.")
        async with self.pool.acquire() as conn:
            yield conn
    
    async def _init_schema(self):
        """Create tables and indexes for series bot."""
        async with self.acquire() as conn:
            await conn.execute('''
                -- Enable extensions
                CREATE EXTENSION IF NOT EXISTS pg_trgm;
                CREATE EXTENSION IF NOT EXISTS btree_gin;
                
                -- ==================== SERIES TABLES ====================
                
                -- Series table (main entity)
                CREATE TABLE IF NOT EXISTS series (
                    id SERIAL PRIMARY KEY,
                    key VARCHAR(255) NOT NULL UNIQUE,
                    title VARCHAR(500) NOT NULL,
                    released_on VARCHAR(100) DEFAULT '',
                    genre VARCHAR(255) DEFAULT '',
                    rating VARCHAR(50) DEFAULT '',
                    languages TEXT[] DEFAULT '{}',
                    seasons JSONB DEFAULT '{}',
                    metadata JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                
                -- Series indexes
                CREATE INDEX IF NOT EXISTS idx_series_key ON series(key);
                CREATE INDEX IF NOT EXISTS idx_series_title_lower ON series(LOWER(title));
                CREATE INDEX IF NOT EXISTS idx_series_title_trgm ON series USING gin(title gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_series_languages ON series USING gin(languages);
                CREATE INDEX IF NOT EXISTS idx_series_seasons ON series USING gin(seasons jsonb_path_ops);
                
                -- Links table (normalized from series)
                CREATE TABLE IF NOT EXISTS series_links (
                    id SERIAL PRIMARY KEY,
                    series_key VARCHAR(255) NOT NULL,
                    language VARCHAR(50) NOT NULL,
                    season VARCHAR(50) NOT NULL,
                    quality VARCHAR(50) NOT NULL,
                    link TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(series_key, language, season, quality)
                );
                
                -- Links indexes
                CREATE INDEX IF NOT EXISTS idx_links_series ON series_links(series_key);
                CREATE INDEX IF NOT EXISTS idx_links_composite ON series_links(series_key, language, season);
                
                -- Posters table
                CREATE TABLE IF NOT EXISTS posters (
                    id SERIAL PRIMARY KEY,
                    series_key VARCHAR(255) NOT NULL UNIQUE,
                    poster_url TEXT NOT NULL,
                    source VARCHAR(50) DEFAULT 'manual',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                
                CREATE INDEX IF NOT EXISTS idx_posters_key ON posters(series_key);
                
                -- ==================== FILES BACKUP TABLE ====================
                
                CREATE TABLE IF NOT EXISTS files_backup (
                    id SERIAL PRIMARY KEY,
                    filename VARCHAR(500) NOT NULL,
                    filesize BIGINT DEFAULT 0,
                    fileid VARCHAR(200) UNIQUE NOT NULL,
                    caption TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_files_filename_trgm 
                    ON files_backup USING GIN (LOWER(filename) gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_files_caption_trgm 
                    ON files_backup USING GIN (LOWER(caption) gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_files_created_at 
                    ON files_backup (created_at DESC);
                
                -- ==================== USERS TABLE ====================
                
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    is_banned BOOLEAN DEFAULT FALSE,
                    ban_reason TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_users_is_banned ON users (is_banned);
                
                -- ==================== GROUPS TABLE ====================
                
                CREATE TABLE IF NOT EXISTS groups (
                    id BIGINT PRIMARY KEY,
                    title VARCHAR(200) NOT NULL,
                    is_disabled BOOLEAN DEFAULT FALSE,
                    reason TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_groups_is_disabled ON groups (is_disabled);
                
                -- Group settings
                CREATE TABLE IF NOT EXISTS group_settings (
                    group_id BIGINT PRIMARY KEY REFERENCES groups(id) ON DELETE CASCADE,
                    button_enabled BOOLEAN DEFAULT TRUE,
                    botpm_enabled BOOLEAN DEFAULT TRUE,
                    file_secure BOOLEAN DEFAULT FALSE,
                    spell_check BOOLEAN DEFAULT TRUE,
                    welcome_enabled BOOLEAN DEFAULT TRUE,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                -- ==================== FSUB TABLES ====================
                
                CREATE TABLE IF NOT EXISTS fsub_first (
                    id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS fsub_second (
                    id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                -- ==================== FILTERS TABLE ====================
                
                CREATE TABLE IF NOT EXISTS filters (
                    id SERIAL PRIMARY KEY,
                    text VARCHAR(500) UNIQUE NOT NULL,
                    reply TEXT,
                    btn TEXT,
                    file TEXT,
                    alert TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_filters_text_trgm 
                    ON filters USING GIN (LOWER(text) gin_trgm_ops);
                
                -- ==================== SUBSCRIPTION SETTINGS ====================
                
                CREATE TABLE IF NOT EXISTS subscription_settings (
                    key VARCHAR(50) PRIMARY KEY,
                    channel_id BIGINT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                -- ==================== UPDATE TRIGGER ====================
                
                CREATE OR REPLACE FUNCTION update_updated_at()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = NOW();
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                
                DROP TRIGGER IF EXISTS series_updated_at ON series;
                CREATE TRIGGER series_updated_at
                    BEFORE UPDATE ON series
                    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
                    
                DROP TRIGGER IF EXISTS users_updated_at ON users;
                CREATE TRIGGER users_updated_at
                    BEFORE UPDATE ON users
                    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
            ''')
        logger.info("✅ Schema initialized successfully")
    
    # ==================== SERIES OPERATIONS ====================
    
    async def upsert_series(self, data: Dict) -> int:
        """Insert or update a series."""
        async with self.acquire() as conn:
            return await conn.fetchval('''
                INSERT INTO series (key, title, released_on, genre, rating, languages, seasons, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (key) DO UPDATE SET
                    title = EXCLUDED.title,
                    released_on = EXCLUDED.released_on,
                    genre = EXCLUDED.genre,
                    rating = EXCLUDED.rating,
                    languages = EXCLUDED.languages,
                    seasons = EXCLUDED.seasons,
                    metadata = COALESCE(series.metadata, '{}') || EXCLUDED.metadata
                RETURNING id
            ''',
                data.get('key', '').lower().replace(' ', ''),
                data.get('title', ''),
                data.get('released_on', ''),
                data.get('genre', ''),
                data.get('rating', ''),
                data.get('languages', []),
                json.dumps(data.get('seasons', {})),
                json.dumps(data.get('metadata', {}))
            )
    
    async def get_series(self, key: str) -> Optional[Dict]:
        """Get series by key."""
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM series WHERE key = $1',
                key.lower().replace(' ', '')
            )
            return self._row_to_dict(row) if row else None
    
    async def delete_series(self, key: str) -> bool:
        """Delete series and related data."""
        key = key.lower().replace(' ', '')
        async with self.acquire() as conn:
            async with conn.transaction():
                await conn.execute('DELETE FROM series_links WHERE series_key = $1', key)
                await conn.execute('DELETE FROM posters WHERE series_key = $1', key)
                result = await conn.execute('DELETE FROM series WHERE key = $1', key)
                return result == 'DELETE 1'
    
    async def search_series(
        self, 
        query: str, 
        limit: int = 10, 
        offset: int = 0
    ) -> Tuple[List[Dict], int, int]:
        """Search series with fuzzy matching."""
        q = query.lower().strip()
        async with self.acquire() as conn:
            total = await conn.fetchval('''
                SELECT COUNT(*) FROM series
                WHERE LOWER(title) LIKE $1 
                   OR LOWER(key) LIKE $1
                   OR similarity(LOWER(title), $2) > 0.25
            ''', f'%{q}%', q)
            
            rows = await conn.fetch('''
                SELECT *,
                    CASE
                        WHEN LOWER(key) = $1 THEN 1.0
                        WHEN LOWER(title) = $1 THEN 0.98
                        WHEN LOWER(title) LIKE $2 THEN 0.8 + (1.0 - LENGTH($1)::float / LENGTH(title))
                        WHEN LOWER(key) LIKE $2 THEN 0.75
                        ELSE similarity(LOWER(title), $1)
                    END AS relevance
                FROM series
                WHERE LOWER(title) LIKE $2 
                   OR LOWER(key) LIKE $2
                   OR similarity(LOWER(title), $1) > 0.25
                ORDER BY relevance DESC, title ASC
                LIMIT $3 OFFSET $4
            ''', q, f'%{q}%', limit, offset)
            
            results = [self._row_to_dict(r) for r in rows]
            next_offset = offset + len(results) if len(results) == limit else 0
            
            return results, next_offset, total or 0
    
    async def get_all_series(self, limit: int = 1000, offset: int = 0) -> List[Dict]:
        """Get all series with pagination."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                'SELECT * FROM series ORDER BY title LIMIT $1 OFFSET $2',
                limit, offset
            )
            return [self._row_to_dict(r) for r in rows]
    
    async def get_series_count(self) -> int:
        """Get total series count."""
        async with self.acquire() as conn:
            return await conn.fetchval('SELECT COUNT(*) FROM series')
    
    # ==================== LINKS OPERATIONS ====================
    
    async def upsert_link(
        self, 
        series_key: str, 
        language: str, 
        season: str, 
        quality: str, 
        link: str
    ):
        """Insert or update a single link."""
        async with self.acquire() as conn:
            await conn.execute('''
                INSERT INTO series_links (series_key, language, season, quality, link)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (series_key, language, season, quality) 
                DO UPDATE SET link = EXCLUDED.link
            ''', series_key.lower(), language.lower(), season.lower(), quality, link)
    
    async def get_links(self, series_key: str, language: str, season: str) -> Dict[str, str]:
        """Get links for a specific series/language/season."""
        async with self.acquire() as conn:
            rows = await conn.fetch('''
                SELECT quality, link FROM series_links
                WHERE series_key = $1 AND language = $2 AND season = $3
            ''', series_key.lower(), language.lower(), season.lower())
            return {r['quality']: r['link'] for r in rows}
    
    # ==================== POSTERS OPERATIONS ====================
    
    async def upsert_poster(self, series_key: str, url: str, source: str = 'manual'):
        """Insert or update poster URL."""
        async with self.acquire() as conn:
            await conn.execute('''
                INSERT INTO posters (series_key, poster_url, source)
                VALUES ($1, $2, $3)
                ON CONFLICT (series_key) DO UPDATE SET 
                    poster_url = EXCLUDED.poster_url,
                    source = EXCLUDED.source
            ''', series_key.lower(), url, source)
    
    async def get_poster(self, series_key: str) -> Optional[str]:
        """Get poster URL for a series."""
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT poster_url FROM posters WHERE series_key = $1',
                series_key.lower()
            )
            return row['poster_url'] if row else None
    
    # ==================== STATS ====================
    
    async def get_stats(self) -> Dict[str, int]:
        """Get table statistics."""
        async with self.acquire() as conn:
            return {
                'series': await conn.fetchval('SELECT COUNT(*) FROM series'),
                'links': await conn.fetchval('SELECT COUNT(*) FROM series_links'),
                'posters': await conn.fetchval('SELECT COUNT(*) FROM posters'),
                'files': await conn.fetchval('SELECT COUNT(*) FROM files_backup'),
                'users': await conn.fetchval('SELECT COUNT(*) FROM users'),
                'groups': await conn.fetchval('SELECT COUNT(*) FROM groups')
            }
    
    async def vacuum_analyze(self):
        """Optimize database after bulk operations."""
        async with self.acquire() as conn:
            await conn.execute('VACUUM ANALYZE series')
            await conn.execute('VACUUM ANALYZE series_links')
            await conn.execute('VACUUM ANALYZE posters')
    
    # ==================== HELPERS ====================
    
    def _row_to_dict(self, row: asyncpg.Record) -> Dict:
        """Convert database row to dictionary."""
        if not row:
            return {}
        result = dict(row)
        if 'seasons' in result and isinstance(result['seasons'], str):
            result['seasons'] = json.loads(result['seasons'])
        if 'metadata' in result and isinstance(result['metadata'], str):
            result['metadata'] = json.loads(result['metadata'])
        result.pop('relevance', None)
        return result


# ==================== GLOBAL INSTANCE ====================

# Create global instance
pgDb = PostgresDB()


async def init_database():
    """Initialize the database connection."""
    await pgDb.connect()
    logger.info("✅ Database initialized")


async def close_database():
    """Close database connection."""
    await pgDb.close()
    logger.info("Database connection closed")
