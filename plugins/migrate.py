# plugins/migrate.py
import asyncio
import time
import logging
from datetime import datetime
from typing import Dict, List, Any

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


def safe_str(value: Any, default: str = '') -> str:
    """Safely convert any value to string."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        return str(value)
    return str(value) if value else default


def safe_list(value: Any, default: List = None) -> List:
    """Safely convert value to list."""
    if default is None:
        default = []
    if value is None:
        return default
    if isinstance(value, list):
        return [safe_str(item) for item in value]
    if isinstance(value, str):
        return [value] if value else default
    return default


def safe_dict(value: Any, default: Dict = None) -> Dict:
    """Safely convert value to dict."""
    if default is None:
        default = {}
    if value is None:
        return default
    if isinstance(value, dict):
        return value
    return default


def normalize_key(value: Any) -> str:
    """Normalize a key value."""
    if value is None:
        return ''
    s = safe_str(value)
    return s.lower().replace(' ', '').strip()


def clean_series_doc(doc: Dict) -> Dict:
    """Clean and normalize a MongoDB series document for PostgreSQL."""
    # Remove MongoDB _id
    doc.pop('_id', None)
    
    # Get or generate key
    key = doc.get('key', '')
    if not key and doc.get('title'):
        key = doc['title']
    key = normalize_key(key)
    
    # Clean all fields with proper type conversion
    return {
        'key': key,
        'title': safe_str(doc.get('title', '')),
        'released_on': safe_str(doc.get('released_on', '')),  # Convert int/float to str
        'genre': safe_str(doc.get('genre', '')),
        'rating': safe_str(doc.get('rating', '')),  # Convert int/float to str
        'languages': safe_list(doc.get('languages', [])),
        'seasons': safe_dict(doc.get('seasons', {})),
        'metadata': safe_dict(doc.get('metadata', {}))
    }


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
            # Clean and normalize the document
            cleaned = clean_series_doc(doc)
            
            if not cleaned['key']:
                stats.warnings.append(f"Series without key: {cleaned.get('title', 'unknown')[:30]}")
                continue
            
            batch.append(cleaned)
            
            if len(batch) >= batch_size:
                await pg.bulk_upsert_series(batch)
                stats.migrated['series'] += len(batch)
                batch = []
                
        except Exception as e:
            stats.errors.append(f"Series: {str(e)[:50]}")
            logger.error(f"Series migration error: {e}", exc_info=True)
    
    # Final batch
    if batch:
        try:
            await pg.bulk_upsert_series(batch)
            stats.migrated['series'] += len(batch)
        except Exception as e:
            stats.errors.append(f"Series final batch: {str(e)[:50]}")
    
    # ==================== MIGRATE LINKS ====================
    stats.phase = "Migrating links..."
    
    for doc in links_col.find({}):
        try:
            doc.pop('_id', None)
            
            # Handle different link storage formats
            series_key = safe_str(doc.get('series_key', ''))
            links_data = safe_dict(doc.get('links', {}))
            
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
                    try:
                        await pg.upsert_link(
                            normalize_key(base_key),
                            normalize_key(language),
                            normalize_key(season),
                            safe_str(quality),
                            safe_str(link)
                        )
                        stats.migrated['links'] += 1
                    except Exception as e:
                        stats.errors.append(f"Link insert: {str(e)[:40]}")
            else:
                # Try alternative formats
                # Format could be: {series_key: key, language: lang, season: s, links: {...}}
                language = safe_str(doc.get('language', ''))
                season = safe_str(doc.get('season', ''))
                
                if language and season:
                    for quality, link in links_data.items():
                        try:
                            await pg.upsert_link(
                                normalize_key(series_key),
                                normalize_key(language),
                                normalize_key(season),
                                safe_str(quality),
                                safe_str(link)
                            )
                            stats.migrated['links'] += 1
                        except Exception as e:
                            stats.errors.append(f"Link insert: {str(e)[:40]}")
                else:
                    stats.warnings.append(f"Unknown link format: {series_key[:30]}")
                
        except Exception as e:
            stats.errors.append(f"Links: {str(e)[:50]}")
    
    # ==================== MIGRATE POSTERS ====================
    stats.phase = "Migrating posters..."
    batch = []
    
    for doc in posters_col.find({}):
        try:
            doc.pop('_id', None)
            
            series_key = normalize_key(doc.get('series_key', ''))
            poster_url = safe_str(doc.get('poster_url', '') or doc.get('poster', ''))
            
            if series_key and poster_url:
                batch.append({
                    'series_key': series_key,
                    'poster_url': poster_url
                })
                
            if len(batch) >= batch_size:
                await pg.bulk_upsert_posters(batch)
                stats.migrated['posters'] += len(batch)
                batch = []
                
        except Exception as e:
            stats.errors.append(f"Poster: {str(e)[:50]}")
    
    # Final batch
    if batch:
        try:
            await pg.bulk_upsert_posters(batch)
            stats.migrated['posters'] += len(batch)
        except Exception as e:
            stats.errors.append(f"Poster final batch: {str(e)[:50]}")
    
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
        
        if stats.warnings:
            final_text += f"\n<b>Warnings:</b> <code>{len(stats.warnings)}</code>\n"
        
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


@Client.on_message(filters.command("inspect") & filters.user(ADMINS))
async def inspect_mongo_command(client: Client, message: Message):
    """Inspect MongoDB schema to help debug migration issues."""
    
    try:
        mongo = MongoClient(DATABASE_URI)
        mongo_db = mongo['series_database']
        
        # Get sample documents
        series_sample = mongo_db['series'].find_one()
        links_sample = mongo_db['series_links'].find_one()
        posters_sample = mongo_db['posters'].find_one()
        
        def format_doc(doc: Dict, name: str) -> str:
            if not doc:
                return f"<b>{name}:</b> No documents found\n"
            
            # Remove _id for display
            doc.pop('_id', None)
            
            fields = []
            for k, v in list(doc.items())[:10]:  # Limit fields shown
                type_name = type(v).__name__
                value_preview = str(v)[:50] + "..." if len(str(v)) > 50 else str(v)
                fields.append(f"  • <code>{k}</code> ({type_name}): <code>{value_preview}</code>")
            
            return f"<b>{name}:</b>\n" + "\n".join(fields) + "\n"
        
        report = "<b>📋 MongoDB Schema Inspection</b>\n\n"
        report += format_doc(series_sample, "📚 Series")
        report += "\n"
        report += format_doc(links_sample, "🔗 Links")
        report += "\n"
        report += format_doc(posters_sample, "🖼 Posters")
        
        # Collection counts
        report += "\n<b>📊 Counts:</b>\n"
        report += f"  • Series: <code>{mongo_db['series'].count_documents({})}</code>\n"
        report += f"  • Links: <code>{mongo_db['series_links'].count_documents({})}</code>\n"
        report += f"  • Posters: <code>{mongo_db['posters'].count_documents({})}</code>\n"
        
        mongo.close()
        
        await message.reply(report, parse_mode=enums.ParseMode.HTML)
        
    except Exception as e:
        await message.reply(
            f"❌ <b>Error:</b> <code>{e}</code>",
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

@Client.on_message(filters.command("inspectdb") & filters.user(ADMINS))
async def inspect_db_command(client: Client, message: Message):
    """Deep inspect MongoDB to find all collections and their structure."""
    
    try:
        mongo = MongoClient(DATABASE_URI)
        
        # Get database name from URI or use default
        db_name = DATABASE_URI.split('/')[-1].split('?')[0]
        if not db_name:
            db_name = 'series_database'
        
        report = f"<b>🔍 MongoDB Deep Inspection</b>\n\n"
        report += f"<b>Database:</b> <code>{db_name}</code>\n\n"
        
        # List all databases
        report += "<b>📁 All Databases:</b>\n"
        for db in mongo.list_database_names():
            report += f"  • <code>{db}</code>\n"
        report += "\n"
        
        # Try common database names
        possible_dbs = [db_name, 'series_database', 'Cluster0', 'test', 'admin']
        
        for try_db in possible_dbs:
            try:
                db = mongo[try_db]
                collections = db.list_collection_names()
                if collections:
                    report += f"<b>📂 Collections in '{try_db}':</b>\n"
                    for col in collections:
                        count = db[col].count_documents({})
                        sample = db[col].find_one()
                        fields = list(sample.keys()) if sample else []
                        # Remove _id from display
                        if '_id' in fields:
                            fields.remove('_id')
                        report += f"  • <code>{col}</code> ({count:,} docs)\n"
                        report += f"    Fields: <code>{', '.join(fields[:8])}</code>\n"
                    report += "\n"
            except:
                pass
        
        mongo.close()
        
        # Split if too long
        if len(report) > 4000:
            await message.reply(report[:4000] + "...", parse_mode=enums.ParseMode.HTML)
        else:
            await message.reply(report, parse_mode=enums.ParseMode.HTML)
        
    except Exception as e:
        await message.reply(
            f"❌ <b>Error:</b> <code>{e}</code>",
            parse_mode=enums.ParseMode.HTML
        )


@Client.on_message(filters.command("sampledata") & filters.user(ADMINS))
async def sample_data_command(client: Client, message: Message):
    """Show sample documents from each collection."""
    
    args = message.text.split(maxsplit=2)
    
    try:
        mongo = MongoClient(DATABASE_URI)
        db_name = DATABASE_URI.split('/')[-1].split('?')[0] or 'series_database'
        
        # Try to find the right database
        for try_db in [db_name, 'Cluster0', 'test']:
            db = mongo[try_db]
            if db.list_collection_names():
                break
        
        if len(args) >= 2:
            # Show specific collection
            col_name = args[1]
            col = db[col_name]
            sample = col.find_one()
            
            if sample:
                sample.pop('_id', None)
                import json
                formatted = json.dumps(sample, indent=2, default=str)[:3500]
                await message.reply(
                    f"<b>📄 Sample from '{col_name}':</b>\n\n<code>{formatted}</code>",
                    parse_mode=enums.ParseMode.HTML
                )
            else:
                await message.reply(f"No documents in '{col_name}'")
        else:
            # List all collections
            cols = db.list_collection_names()
            await message.reply(
                f"<b>Usage:</b> <code>/sampledata collection_name</code>\n\n"
                f"<b>Available collections:</b>\n" + 
                "\n".join(f"• <code>{c}</code>" for c in cols),
                parse_mode=enums.ParseMode.HTML
            )
        
        mongo.close()
        
    except Exception as e:
        await message.reply(f"❌ <b>Error:</b> <code>{e}</code>", parse_mode=enums.ParseMode.HTML)
        
