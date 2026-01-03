# plugins/commands/migrate.py
from pyrogram import Client, filters
from pyrogram.types import Message
from pymongo import MongoClient
from info import DATABASE_URI, ADMINS, POSTGRES_URI
from database.pg_db import PostgresDB
import json

# Simple stats class - NO REDIS NEEDED
class MigrationStats:
    def __init__(self):
        self.phase = "Starting..."
        self.total = {'series': 0, 'links': 0, 'posters': 0}
        self.migrated = {'series': 0, 'links': 0, 'posters': 0}
        self.errors = []

async def update_progress(msg: Message, stats: MigrationStats):
    text = f"""⏳ **Migration Progress**

**Phase:** {stats.phase}

📺 **Series:** {stats.migrated['series']}/{stats.total['series']}
🔗 **Links:** {stats.migrated['links']}/{stats.total['links']}
🖼 **Posters:** {stats.migrated['posters']}/{stats.total['posters']}

❌ **Errors:** {len(stats.errors)}"""
    
    try:
        await msg.edit_text(text)
    except:
        pass

@Client.on_message(filters.command("migrate") & filters.user(ADMINS))
async def migrate_command(client: Client, message: Message):
    progress_msg = await message.reply_text("🚀 Starting migration...")
    stats = MigrationStats()
    
    try:
        # Connect to PostgreSQL
        stats.phase = "Connecting to PostgreSQL..."
        await update_progress(progress_msg, stats)
        
        pg = PostgresDB(POSTGRES_URI)
        await pg.connect()
        
        # Run migration
        await migrate_data(pg, progress_msg, stats)
        
        # Optimize after bulk insert
        stats.phase = "Optimizing database..."
        await update_progress(progress_msg, stats)
        await pg.vacuum_analyze()
        
        # Final report
        error_text = ""
        if stats.errors:
            error_text = f"\n\n**First 5 errors:**\n" + "\n".join(stats.errors[:5])
        
        await progress_msg.edit_text(f"""✅ **Migration Complete!**

📺 **Series:** {stats.migrated['series']}/{stats.total['series']}
🔗 **Links:** {stats.migrated['links']}/{stats.total['links']}
🖼 **Posters:** {stats.migrated['posters']}/{stats.total['posters']}

❌ **Total Errors:** {len(stats.errors)}{error_text}""")
        
        await pg.close()
        
    except Exception as e:
        await progress_msg.edit_text(f"""❌ **Migration Failed**

**Phase:** {stats.phase}
**Error:** {str(e)[:300]}""")


async def migrate_data(pg: PostgresDB, progress_msg: Message, stats: MigrationStats):
    """Migrate data from MongoDB to PostgreSQL"""
    
    # Connect to MongoDB
    mongo = MongoClient(DATABASE_URI)
    db = mongo['series_database']  # Adjust database name if different
    series_col = db['series']       # Adjust collection name if different
    
    def normalize_key(text):
        if not text:
            return ""
        return str(text).lower().replace(" ", "").strip()
    
    def safe_str(val):
        if val is None:
            return ""
        return str(val).strip()
    
    # ========== COUNT TOTALS ==========
    stats.phase = "Counting data..."
    await update_progress(progress_msg, stats)
    
    stats.total['series'] = series_col.count_documents({})
    
    for doc in series_col.find({}):
        if doc.get('poster_file_id'):
            stats.total['posters'] += 1
        
        languages = doc.get('languages', [])
        if isinstance(languages, list):
            for lang in languages:
                if isinstance(lang, dict):
                    seasons = lang.get('seasons', [])
                    if isinstance(seasons, list):
                        for season in seasons:
                            if isinstance(season, dict):
                                qualities = season.get('qualities', [])
                                if isinstance(qualities, list):
                                    stats.total['links'] += len(qualities)
    
    await update_progress(progress_msg, stats)
    
    # ========== MIGRATE SERIES ==========
    stats.phase = "Migrating series..."
    await update_progress(progress_msg, stats)
    
    for doc in series_col.find({}):
        try:
            title = safe_str(doc.get('title', ''))
            if not title:
                continue
            
            series_key = normalize_key(title)
            
            # Extract language names
            lang_names = []
            languages = doc.get('languages', [])
            if isinstance(languages, list):
                for lang in languages:
                    if isinstance(lang, dict) and lang.get('name'):
                        lang_names.append(lang['name'])
            
            # Build seasons dict for JSONB
            # Format: {"season1": {"hindi": true, "english": true}, ...}
            seasons_dict = {}
            if isinstance(languages, list):
                for lang in languages:
                    if not isinstance(lang, dict):
                        continue
                    lang_name = safe_str(lang.get('name', 'Unknown')).lower()
                    seasons = lang.get('seasons', [])
                    if isinstance(seasons, list):
                        for season in seasons:
                            if isinstance(season, dict) and season.get('name'):
                                season_name = safe_str(season['name']).lower().replace(' ', '')
                                if season_name not in seasons_dict:
                                    seasons_dict[season_name] = {}
                                seasons_dict[season_name][lang_name] = True
            
            # Prepare series data for your upsert_series method
            series_data = {
                'key': series_key,
                'title': title,
                'released_on': safe_str(doc.get('released_on', '')),
                'genre': safe_str(doc.get('genre', '')),
                'rating': safe_str(doc.get('rating', '')),
                'languages': lang_names,
                'seasons': seasons_dict,
                'metadata': {
                    'media_type': safe_str(doc.get('media_type', 'tv series')),
                    'published': bool(doc.get('published', False)),
                    'migrated_from': 'mongodb'
                }
            }
            
            await pg.upsert_series(series_data)
            stats.migrated['series'] += 1
            
        except Exception as e:
            stats.errors.append(f"Series '{doc.get('title', 'unknown')}': {str(e)[:50]}")
        
        if stats.migrated['series'] % 50 == 0:
            await update_progress(progress_msg, stats)
    
    # ========== MIGRATE POSTERS ==========
    stats.phase = "Migrating posters..."
    await update_progress(progress_msg, stats)
    
    for doc in series_col.find({}):
        try:
            title = safe_str(doc.get('title', ''))
            if not title:
                continue
            
            series_key = normalize_key(title)
            poster_file_id = doc.get('poster_file_id')
            
            if poster_file_id:
                await pg.upsert_poster(series_key, safe_str(poster_file_id), source='mongodb')
                stats.migrated['posters'] += 1
                
        except Exception as e:
            stats.errors.append(f"Poster '{doc.get('title', 'unknown')}': {str(e)[:50]}")
        
        if stats.migrated['posters'] % 100 == 0:
            await update_progress(progress_msg, stats)
    
    # ========== MIGRATE LINKS ==========
    stats.phase = "Migrating links..."
    await update_progress(progress_msg, stats)
    
    for doc in series_col.find({}):
        try:
            title = safe_str(doc.get('title', ''))
            if not title:
                continue
            
            series_key = normalize_key(title)
            languages = doc.get('languages', [])
            
            if not isinstance(languages, list):
                continue
            
            for lang in languages:
                if not isinstance(lang, dict):
                    continue
                
                lang_name = safe_str(lang.get('name', 'Unknown')).lower()
                
                seasons = lang.get('seasons', [])
                if not isinstance(seasons, list):
                    continue
                
                for season in seasons:
                    if not isinstance(season, dict):
                        continue
                    
                    season_name = safe_str(season.get('name', 'Season 1')).lower().replace(' ', '')
                    
                    qualities = season.get('qualities', [])
                    if not isinstance(qualities, list):
                        continue
                    
                    for quality in qualities:
                        if not isinstance(quality, dict):
                            continue
                        
                        quality_name = safe_str(quality.get('name', ''))
                        link_key = safe_str(quality.get('link_key', ''))
                        
                        if quality_name and link_key:
                            await pg.upsert_link(
                                series_key=series_key,
                                language=lang_name,
                                season=season_name,
                                quality=quality_name,
                                link=link_key
                            )
                            stats.migrated['links'] += 1
                            
        except Exception as e:
            stats.errors.append(f"Link '{doc.get('title', 'unknown')}': {str(e)[:50]}")
        
        if stats.migrated['links'] % 200 == 0:
            await update_progress(progress_msg, stats)
    
    mongo.close()
    stats.phase = "Complete!"
    await update_progress(progress_msg, stats)
