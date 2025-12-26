# database/manager.py
import logging
from typing import Optional
from database.pg_db import PostgresDB
from database.cache import Cache

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Singleton database manager for PostgreSQL and Redis."""
    
    _instance: Optional['DatabaseManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self.pg: Optional[PostgresDB] = None
        self.cache: Optional[Cache] = None
    
    async def init(self, postgres_uri: str, redis_url: str):
        """Initialize database connections."""
        if self._initialized:
            return
        
        # PostgreSQL
        self.pg = PostgresDB(postgres_uri)
        await self.pg.connect()
        
        # Redis
        self.cache = Cache(redis_url)
        await self.cache.connect()
        
        self._initialized = True
        logger.info("Database manager initialized")
    
    async def close(self):
        """Close all connections."""
        if self.pg:
            await self.pg.close()
        if self.cache:
            await self.cache.close()
        self._initialized = False
    
    @property
    def is_ready(self) -> bool:
        return self._initialized and self.pg is not None and self.cache is not None


# Global instance
db = DatabaseManager()


async def init_databases(postgres_uri: str, redis_url: str):
    """Initialize databases."""
    await db.init(postgres_uri, redis_url)


async def close_databases():
    """Close databases."""
    await db.close()


def get_pg() -> PostgresDB:
    """Get PostgreSQL instance."""
    if not db.pg:
        raise RuntimeError("Database not initialized")
    return db.pg


def get_cache() -> Cache:
    """Get Redis cache instance."""
    if not db.cache:
        raise RuntimeError("Cache not initialized")
    return db.cache
