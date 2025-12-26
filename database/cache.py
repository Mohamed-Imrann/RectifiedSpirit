# database/cache.py
import json
import logging
import hashlib
from typing import Any, Optional, List, Dict, Tuple, Union
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class Cache:
    """Redis cache with automatic serialization and TTL management."""
    
    # Default TTLs (in seconds)
    TTL_SEARCH = 60          # Search results
    TTL_SERIES = 300         # Series data
    TTL_SUGGESTIONS = 60     # Fuzzy suggestions
    TTL_LINKS = 300          # Episode links
    TTL_POSTER = 86400       # Poster URLs (24h)
    TTL_SEASONS = 300        # Season lists
    
    # Key prefixes
    PREFIX_SEARCH = "search"
    PREFIX_SERIES = "series"
    PREFIX_SUGGEST = "suggest"
    PREFIX_LINKS = "links"
    PREFIX_POSTER = "poster"
    PREFIX_SEASONS = "seasons"
    
    def __init__(self, url: str):
        self.url = url
        self.client: Optional[redis.Redis] = None
    
    async def connect(self):
        """Initialize Redis connection."""
        if self.client:
            return
        
        self.client = redis.from_url(
            self.url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True
        )
        await self.client.ping()
        logger.info("Redis connected")
    
    async def close(self):
        """Close Redis connection."""
        if self.client:
            await self.client.close()
            self.client = None
    
    async def ping(self) -> bool:
        """Check connection health."""
        try:
            return await self.client.ping()
        except:
            return False
    
    # ==================== CORE OPERATIONS ====================
    
    async def get(self, key: str) -> Optional[Any]:
        """Get and deserialize value."""
        try:
            data = await self.client.get(key)
            return json.loads(data) if data else None
        except json.JSONDecodeError:
            return data
        except Exception as e:
            logger.error(f"Cache GET error [{key}]: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = 60) -> bool:
        """Serialize and set value with TTL."""
        try:
            serialized = json.dumps(value, default=str, ensure_ascii=False)
            await self.client.setex(key, ttl, serialized)
            return True
        except Exception as e:
            logger.error(f"Cache SET error [{key}]: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete a key."""
        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache DELETE error [{key}]: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        try:
            return await self.client.exists(key) > 0
        except:
            return False
    
    async def clear_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern."""
        try:
            deleted = 0
            cursor = 0
            while True:
                cursor, keys = await self.client.scan(cursor, match=pattern, count=100)
                if keys:
                    deleted += await self.client.delete(*keys)
                if cursor == 0:
                    break
            return deleted
        except Exception as e:
            logger.error(f"Cache CLEAR pattern error [{pattern}]: {e}")
            return 0
    
    async def clear_all(self) -> bool:
        """Flush entire database."""
        try:
            await self.client.flushdb()
            return True
        except Exception as e:
            logger.error(f"Cache FLUSH error: {e}")
            return False
    
    # ==================== SEARCH CACHE ====================
    
    def _search_key(self, query: str, offset: int = 0) -> str:
        """Generate search cache key."""
        q_hash = hashlib.md5(query.lower().strip().encode()).hexdigest()[:8]
        return f"{self.PREFIX_SEARCH}:{q_hash}:{offset}"
    
    async def get_search(self, query: str, offset: int = 0) -> Optional[Tuple[List, int, int]]:
        """Get cached search results."""
        data = await self.get(self._search_key(query, offset))
        if data and isinstance(data, list) and len(data) == 3:
            return data[0], data[1], data[2]
        return None
    
    async def set_search(
        self, 
        query: str, 
        results: List, 
        next_offset: int, 
        total: int,
        offset: int = 0,
        ttl: int = None
    ):
        """Cache search results."""
        await self.set(
            self._search_key(query, offset),
            [results, next_offset, total],
            ttl or self.TTL_SEARCH
        )
    
    # ==================== SERIES CACHE ====================
    
    def _series_key(self, key: str) -> str:
        """Generate series cache key."""
        return f"{self.PREFIX_SERIES}:{key.lower().replace(' ', '')}"
    
    async def get_series(self, key: str) -> Optional[Dict]:
        """Get cached series data."""
        return await self.get(self._series_key(key))
    
    async def set_series(self, key: str, data: Dict, ttl: int = None):
        """Cache series data."""
        await self.set(self._series_key(key), data, ttl or self.TTL_SERIES)
    
    async def invalidate_series(self, key: str):
        """Invalidate all cache for a series."""
        k = key.lower().replace(' ', '')
        await self.delete(self._series_key(k))
        await self.delete(f"{self.PREFIX_POSTER}:{k}")
        await self.delete(f"{self.PREFIX_SEASONS}:{k}")
        await self.clear_pattern(f"{self.PREFIX_LINKS}:{k}:*")
        await self.clear_pattern(f"{self.PREFIX_SEARCH}:*")
        await self.clear_pattern(f"{self.PREFIX_SUGGEST}:*")
    
    # ==================== SUGGESTIONS CACHE ====================
    
    def _suggest_key(self, query: str) -> str:
        """Generate suggestions cache key."""
        q_hash = hashlib.md5(query.lower().strip().encode()).hexdigest()[:8]
        return f"{self.PREFIX_SUGGEST}:{q_hash}"
    
    async def get_suggestions(self, query: str) -> Optional[List]:
        """Get cached suggestions."""
        return await self.get(self._suggest_key(query))
    
    async def set_suggestions(self, query: str, matches: List, ttl: int = None):
        """Cache suggestions."""
        await self.set(self._suggest_key(query), matches, ttl or self.TTL_SUGGESTIONS)
    
    # ==================== LINKS CACHE ====================
    
    def _links_key(self, series_key: str, language: str, season: str) -> str:
        """Generate links cache key."""
        return f"{self.PREFIX_LINKS}:{series_key.lower()}:{language.lower()}:{season.lower()}"
    
    async def get_links(self, series_key: str, language: str, season: str) -> Optional[Dict]:
        """Get cached links."""
        return await self.get(self._links_key(series_key, language, season))
    
    async def set_links(self, series_key: str, language: str, season: str, links: Dict, ttl: int = None):
        """Cache links."""
        await self.set(self._links_key(series_key, language, season), links, ttl or self.TTL_LINKS)
    
    # ==================== POSTER CACHE ====================
    
    def _poster_key(self, key: str) -> str:
        """Generate poster cache key."""
        return f"{self.PREFIX_POSTER}:{key.lower().replace(' ', '')}"
    
    async def get_poster(self, key: str) -> Optional[str]:
        """Get cached poster URL."""
        return await self.get(self._poster_key(key))
    
    async def set_poster(self, key: str, url: str, ttl: int = None):
        """Cache poster URL."""
        await self.set(self._poster_key(key), url, ttl or self.TTL_POSTER)
    
    # ==================== SEASONS CACHE ====================
    
    def _seasons_key(self, key: str) -> str:
        """Generate seasons cache key."""
        return f"{self.PREFIX_SEASONS}:{key.lower().replace(' ', '')}"
    
    async def get_seasons(self, key: str) -> Optional[List]:
        """Get cached seasons list."""
        return await self.get(self._seasons_key(key))
    
    async def set_seasons(self, key: str, seasons: List, ttl: int = None):
        """Cache seasons list."""
        await self.set(self._seasons_key(key), seasons, ttl or self.TTL_SEASONS)
    
    # ==================== STATS ====================
    
    async def get_stats(self) -> Dict:
        """Get cache statistics."""
        try:
            info = await self.client.info('memory')
            keys = await self.client.dbsize()
            return {
                'keys': keys,
                'memory_used': info.get('used_memory_human', 'N/A'),
                'memory_peak': info.get('used_memory_peak_human', 'N/A')
            }
        except:
            return {'keys': 0, 'memory_used': 'N/A', 'memory_peak': 'N/A'}
