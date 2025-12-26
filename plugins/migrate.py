# plugins/migrate.py
import asyncio
import time
import logging
from datetime import datetime
from typing import Dict, List

from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pymongo import MongoClient

from info import ADMINS, DATABASE_URI, POSTGRES_URI, REDIS_URL
from database.pg_db import PostgresDB
from database.cache import Cache

logger = logging.getLogger(__name__)


class MigrationStats:
    """Track migration progress and statistics."""
    
    def __init__(self):
        self.start_time = time.time()
        self.phase = "Initializing"
        self.totals = {'series': 0, 'links': 0, 'posters': 0}
        self.migrated = {'series': 0, 'links': 0, 'posters': 0}
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    @property
    def elapsed(self) -> str:
        secs = int(time.time() - self.start_time)
        mins, secs = divmod(secs, 60)
        return f"{mins}m {secs}s"
    
    def progress_bar(self, done: int, total: int, width: int = 10) -> str:
        if total == 0:
            return "░" * width + " 0%"
        pct = done / total
        filled = int(pct * width)
        return f"{'█' * filled}{'░' * (width - filled)} {pct:.0%}"
    
    def format_progress(self) -> str:
        return f"""
<b>🔄 Migration Progress</b>

<b>Phase:</b> <code>{self.phase}</code>
<b>Elapsed:</b> <code>{self.elapsed}</code>

<b>📚 Series</b>
{self.progress_bar(self.migrated['series'], self.totals['series'])}
<code>{self.migrated['series']:,} / {self.totals['series']:,}</code>

<b>🔗 Links</b>
{self.progress_bar(self.migrated['links'], self.totals['links'])}
<code>{self.migrated['links']:,} / {self.totals['links']:,}</code>

<b>🖼 Posters</b>
{self.progress_bar(self.migrated['posters'], self.totals['posters'])}
<code>{self.migrated['posters']:,} / {self.totals['posters']:,}</code>

<b>⚠️ Errors:</b> <code>{len(self.errors)}</code>
<b>⚡ Warnings:</b> <code>{len(self.warnings)}</code>
"""
    
    def format_final(self, pg_stats: Dict) -> str:
        status = "✅ Completed" if not self.errors else "⚠️ Completed with errors"
        return f"""
<b>{status}</b>

<b>⏱ Total Time:</b> <code>{self.elapsed}</code>

<b>📊 Migration Summary:</b>
├ Series: <code>{self.migrated['series']:,} / {self.totals['series']:,}</code>
├ Links: <code>{self.migrated['links']:,} / {self.totals['links']:,}</code>
└ Posters: <code>{self.migrated['posters']:,} / {self.totals['posters']:,}</code>

<b>📈 PostgreSQL Stats:</b>
├ Series: <code>{pg_stats.get('series', 0):,}</code>
├ Links: <code>{pg_stats.get('links', 0):,}</code>
└ Posters: <code>{pg_stats.get('posters', 0):,}</code>

<b>⚠️ Errors:</b> <code>{len(self.errors)}</code>
<b>⚡ Warnings:</b> <code>{len(self.warnings)}</code>
"""


async def migrate_data(stats: MigrationStats, pg: PostgresDB, cache: Cache):
    """Perform the actual migration."""
    
    # Connect to MongoDB
    mongo = MongoClient(DATABASE_URI)
    mongo_db = mongo['series_database']
    
    # Collections (adjust names as per your schema)
    series_col = mongo_db['series']
    links_col = mongo_db['series_links']
    posters_col = mongo_db['posters']
    
    # Count documents
    stats.phase = "Counting documents..."
    stats.totals['series'] = series_col.count_documents({})
    stats.totals['links'] = links_col.count_documents({})
    stats.totals['posters'] = posters_col.count_documents({})
    
    # Clear PostgreSQL
    stats.phase = "Clearing PostgreSQL..."
    await pg.truncate_all()
    
    # Clear Redis cache
    stats.phase = "Clearing Redis cache..."
    await cache.clear_all()
    
    # ==================== MIGRATE SERIES ====================
    stats.phase = "Migrating series..."
    batch = []
    batch_size = 100
    
    for doc in series_col.find({}):
        try:
            # Handle _id if needed
            doc.pop('_id', None)
            
            # Ensure key exists
            key = doc.get('key', '')
            if not key and doc.get('title'):
                key = doc['title'].lower().replace(' ', '')
            
            if not key:
                stats.warnings.append(f"Series without key: {doc.get('title', 'unknown')}")
                continue
            
            batch.append({
                'key': key.lower().replace(' ', ''),
                'title': doc.get('title', ''),
                'released_on': doc.get('released_on', ''),
                'genre': doc.get('genre', ''),
                'rating': str(doc.get('rating', '')),
                'languages': doc.get('languages', []),
                'seasons': doc.get('seasons', {})
            })
            
            if len(batch) >= batch_size:
                await pg.bulk_upsert_series(batch)
                stats.migrated['series'] += len(batch)
                batch = []
                
        except Exception as e:
            stats.errors.append(f"Series error: {str(e)[:50]}")
    
    # Final batch
    if batch:
        await pg.bulk_upsert_series(batch)
        stats.migrated['series'] += len(batch)
    
    # ==================== MIGRATE LINKS ====================
    stats.phase = "Migrating links..."
    
    for doc in links_col.find({}):
        try:
            doc.pop('_id', None)
            
            # Handle different link storage formats
            series_key = doc.get('series_key', '')
            links_data = doc.get('links', {})
            
            if not series_key or not links_data:
                continue
            
            # Parse composite key if needed: serieskey-language-season
            parts = series_key.split('-')
            if len(parts) >= 3:
                season = parts[-1]
                language = parts[-2]
                base_key = '-'.join(parts[:-2])
                
                # Insert each quality/link pair
                for quality, link in links_data.items():
                    await pg.upsert_link(base_key, language, season, quality, link)
                    stats.migrated['links'] += 1
            else:
                # Alternative format handling
                stats.warnings.append(f"Unknown link format: {series_key}")
                
        except Exception as e:
            stats.errors.append(f"Links error: {str(e)[:50]}")
    
    # ==================== MIGRATE POSTERS ====================
    stats.phase = "Migrating posters..."
    batch = []
    
    for doc in posters_col.find({}):
        try:
            doc.pop('_id', None)
            
            series_key = doc.get('series_key', '')
            poster_url = doc.get('poster_url', '')
            
            if series_key and poster_url:
                batch.append({
                    'series_key': series_key.lower().replace(' ', ''),
                    'poster_url': poster_url
                })
                
            if len(batch) >= batch_size:
                await pg.bulk_upsert_posters(batch)
                stats.migrated['posters'] += len(batch)
                batch = []
                
        except Exception as e:
            stats.errors.append(f"Poster error: {str(e)[:50]}")
    
    # Final batch
    if batch:
        await pg.bulk_upsert_posters(batch)
        stats.migrated['posters'] += len(batch)
    
    # Optimize database
    stats.phase = "Optimizing database..."
    await pg.vacuum_analyze()
    
    # Close MongoDB
    mongo.close()
    
    stats.phase = "Complete"


@Client.on_message(filters.command("migrate") & filters.user(ADMINS))
async def migrate_command(client: Client, message: Message):
    """Migrate data from MongoDB to PostgreSQL."""
    
    if not POSTGRES_URI or not REDIS_URL:
        return await message.reply(
            "❌ <b>Configuration Error</b>\n\n"
            "<code>POSTGRES_URI</code> or <code>REDIS_URL</code> not set!",
            parse_mode=enums.ParseMode.HTML
        )
    
    # Initialize tracker
    stats = MigrationStats()
    msg = await message.reply(stats.format_progress(), parse_mode=enums.ParseMode.HTML)
    
    # Progress updater
    stop_event = asyncio.Event()
    
    async def update_progress():
        while not stop_event.is_set():
            try:
                await msg.edit_text(stats.format_progress(), parse_mode=enums.ParseMode.HTML)
            except:
                pass
            await asyncio.sleep(3)
    
    progress_task = asyncio.create_task(update_progress())
    
    try:
        # Connect to PostgreSQL
        stats.phase = "Connecting to PostgreSQL..."
        pg = PostgresDB(POSTGRES_URI)
        await pg.connect()
        
        # Connect to Redis
        stats.phase = "Connecting to Redis..."
        cache = Cache(REDIS_URL)
        await cache.connect()
        
        # Run migration
        await migrate_data(stats, pg, cache)
        
        # Get final stats
        pg_stats = await pg.get_stats()
        
        # Cleanup
        await pg.close()
        await cache.close()
        
        # Stop progress updater
        stop_event.set()
        progress_task.cancel()
        
        # Show final results
        final_text = stats.format_final(pg_stats)
        
        # Add error details if any
        if stats.errors:
            final_text += "\n<b>Recent Errors:</b>\n"
            for err in stats.errors[-5:]:
                final_text += f"<code>• {err}</code>\n"
        
        await msg.edit_text(final_text, parse_mode=enums.ParseMode.HTML)
        
    except Exception as e:
        stop_event.set()
        progress_task.cancel()
        logger.exception("Migration failed")
        await msg.edit_text(
            f"❌ <b>Migration Failed</b>\n\n"
            f"<b>Phase:</b> <code>{stats.phase}</code>\n"
            f"<b>Error:</b> <code>{str(e)}</code>",
            parse_mode=enums.ParseMode.HTML
        )


@Client.on_message(filters.command("dbstats") & filters.user(ADMINS))
async def db_stats_command(client: Client, message: Message):
    """Show database statistics."""
    
    try:
        # PostgreSQL stats
        pg = PostgresDB(POSTGRES_URI)
        await pg.connect()
        pg_stats = await pg.get_stats()
        await pg.close()
        
        # Redis stats
        cache = Cache(REDIS_URL)
        await cache.connect()
        cache_stats = await cache.get_stats()
        await cache.close()
        
        await message.reply(f"""
<b>📊 Database Statistics</b>

<b>🐘 PostgreSQL</b>
├ Series: <code>{pg_stats.get('series', 0):,}</code>
├ Links: <code>{pg_stats.get('links', 0):,}</code>
└ Posters: <code>{pg_stats.get('posters', 0):,}</code>

<b>🔴 Redis Cache</b>
├ Keys: <code>{cache_stats.get('keys', 0):,}</code>
├ Memory: <code>{cache_stats.get('memory_used', 'N/A')}</code>
└ Peak: <code>{cache_stats.get('memory_peak', 'N/A')}</code>
""", parse_mode=enums.ParseMode.HTML)
        
    except Exception as e:
        await message.reply(
            f"❌ <b>Error:</b> <code>{e}</code>",
            parse_mode=enums.ParseMode.HTML
        )


@Client.on_message(filters.command("clearcache") & filters.user(ADMINS))
async def clear_cache_command(client: Client, message: Message):
    """Clear Redis cache."""
    
    try:
        cache = Cache(REDIS_URL)
        await cache.connect()
        
        stats_before = await cache.get_stats()
        await cache.clear_all()
        
        await cache.close()
        
        await message.reply(
            f"✅ <b>Cache Cleared</b>\n\n"
            f"<b>Keys removed:</b> <code>{stats_before.get('keys', 0):,}</code>\n"
            f"<b>Memory freed:</b> <code>{stats_before.get('memory_used', 'N/A')}</code>",
            parse_mode=enums.ParseMode.HTML
        )
        
    except Exception as e:
        await message.reply(
            f"❌ <b>Error:</b> <code>{e}</code>",
            parse_mode=enums.ParseMode.HTML
        )


@Client.on_message(filters.command("invalidate") & filters.user(ADMINS))
async def invalidate_command(client: Client, message: Message):
    """Invalidate cache for a specific series."""
    
    if len(message.command) < 2:
        return await message.reply(
            "❌ <b>Usage:</b> <code>/invalidate series_key</code>",
            parse_mode=enums.ParseMode.HTML
        )
    
    key = message.command[1].lower().replace(' ', '')
    
    try:
        cache = Cache(REDIS_URL)
        await cache.connect()
        await cache.invalidate_series(key)
        await cache.close()
        
        await message.reply(
            f"✅ Cache invalidated for: <code>{key}</code>",
            parse_mode=enums.ParseMode.HTML
        )
        
    except Exception as e:
        await message.reply(
            f"❌ <b>Error:</b> <code>{e}</code>",
            parse_mode=enums.ParseMode.HTML
        )
