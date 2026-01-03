# database/manager.py
import logging
import asyncio
from typing import Optional
from database.pg_db import PostgresDB
from database.cache import Cache

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Singleton database manager for PostgreSQL and Redis."""
    
    _instance: Optional['DatabaseManager'] = None
    _lock = asyncio.Lock()  # Thread-safe initialization
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if getattr(self, '_init_done', False):
            return
        self.pg: Optional[PostgresDB] = None
        self.cache: Optional[Cache] = None
        self._initialized = False
        self._init_done = True
    
    async def init(
        self, 
        postgres_uri: str, 
        redis_url: str,
        max_retries: int = 5,
        retry_delay: float = 2.0
    ):
        """
        Initialize database connections with retry logic.
        
        Important for EasyPanel: Services may start before databases are ready.
        """
        async with self._lock:
            if self._initialized:
                logger.debug("Database manager already initialized")
                return
            
            # Initialize PostgreSQL with retries
            self.pg = PostgresDB(postgres_uri)
            for attempt in range(1, max_retries + 1):
                try:
                    await self.pg.connect()
                    logger.info(f"PostgreSQL connected (attempt {attempt})")
                    break
                except Exception as e:
                    if attempt == max_retries:
                        logger.error(f"PostgreSQL connection failed after {max_retries} attempts: {e}")
                        raise
                    logger.warning(f"PostgreSQL connection attempt {attempt} failed: {e}. Retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
            
            # Initialize Redis with retries
            self.cache = Cache(redis_url)
            for attempt in range(1, max_retries + 1):
                try:
                    await self.cache.connect()
                    logger.info(f"Redis connected (attempt {attempt})")
                    break
                except Exception as e:
                    if attempt == max_retries:
                        logger.error(f"Redis connection failed after {max_retries} attempts: {e}")
                        raise
                    logger.warning(f"Redis connection attempt {attempt} failed: {e}. Retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
            
            self._initialized = True
            logger.info("✅ Database manager fully initialized")
    
    async def close(self):
        """Close all connections gracefully."""
        async with self._lock:
            errors = []
            
            if self.pg:
                try:
                    await self.pg.close()
                    logger.info("PostgreSQL connection closed")
                except Exception as e:
                    errors.append(f"PostgreSQL: {e}")
                    logger.error(f"Error closing PostgreSQL: {e}")
            
            if self.cache:
                try:
                    await self.cache.close()
                    logger.info("Redis connection closed")
                except Exception as e:
                    errors.append(f"Redis: {e}")
                    logger.error(f"Error closing Redis: {e}")
            
            self._initialized = False
            self.pg = None
            self.cache = None
            
            if errors:
                logger.warning(f"Closed with errors: {errors}")
            else:
                logger.info("✅ All database connections closed cleanly")
    
    async def health_check(self) -> dict:
        """Check health of all database connections."""
        status = {
            "postgres": False,
            "redis": False,
            "overall": False
        }
        
        # Check PostgreSQL
        if self.pg:
            try:
                await self.pg.execute("SELECT 1")
                status["postgres"] = True
            except Exception as e:
                logger.warning(f"PostgreSQL health check failed: {e}")
        
        # Check Redis
        if self.cache:
            try:
                await self.cache.ping()
                status["redis"] = True
            except Exception as e:
                logger.warning(f"Redis health check failed: {e}")
        
        status["overall"] = status["postgres"] and status["redis"]
        return status
    
    @property
    def is_ready(self) -> bool:
        return self._initialized and self.pg is not None and self.cache is not None


# ============ Global Instance ============
db = DatabaseManager()


# ============ Helper Functions ============
async def init_databases(postgres_uri: str, redis_url: str, **kwargs):
    """Initialize databases with connection URIs."""
    await db.init(postgres_uri, redis_url, **kwargs)


async def close_databases():
    """Close all database connections."""
    await db.close()


async def check_databases() -> dict:
    """Health check for all databases."""
    return await db.health_check()


def get_pg() -> PostgresDB:
    """Get PostgreSQL instance."""
    if not db.pg:
        raise RuntimeError("PostgreSQL not initialized. Call init_databases() first.")
    return db.pg


def get_cache() -> Cache:
    """Get Redis cache instance."""
    if not db.cache:
        raise RuntimeError("Redis cache not initialized. Call init_databases() first.")
    return db.cache


def get_db() -> DatabaseManager:
    """Get the database manager instance."""
    return db
