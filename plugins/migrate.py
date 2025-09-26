#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import asyncio
import logging
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import BulkWriteError
from info import ADMINS, DATABASE_URI, NEW_DATABASE_URI, MIGRATION_MODE
from pyrogram import Client, filters
from pyrogram.types import Message

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MongoToMongoMigration:
    def __init__(self):
        self.old_mongo_uri = DATABASE_URI
        self.new_mongo_uri = NEW_DATABASE_URI
        self.batch_size = 100
        
    async def connect_databases(self):
        """Connect to both old and new MongoDB databases"""
        try:
            # Connect to old MongoDB
            self.old_client = MongoClient(self.old_mongo_uri)
            self.old_db = self.old_client['series_database']
            self.old_series_collection = self.old_db['series']
            self.old_links_collection = self.old_db['series_links']
            self.old_posters_collection = self.old_db['posters']
            self.old_episodes_collection = self.old_db.get('episodes', None)
            logger.info("Connected to old MongoDB successfully")
            
            # Connect to new MongoDB
            self.new_client = MongoClient(self.new_mongo_uri)
            self.new_db = self.new_client['series_database']
            self.new_series_collection = self.new_db['series']
            self.new_episodes_collection = self.new_db['episodes']
            self.new_posters_collection = self.new_db['posters']
            self.new_admin_assignments_collection = self.new_db['admin_assignments']
            logger.info("Connected to new MongoDB successfully")
            
            return True
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            return False
    
    async def migrate_series(self, progress_callback=None):
        """Migrate series data from old MongoDB to new MongoDB"""
        try:
            # Get all series from old MongoDB
            series_list = list(self.old_series_collection.find())
            total_series = len(series_list)
            logger.info(f"Found {total_series} series to migrate")
            
            migrated_series = 0
            skipped_series = 0
            
            # Prepare batch operations
            series_batch = []
            episodes_batch = []
            posters_batch = []
            
            for series_data in series_list:
                try:
                    # Transform series data to new structure
                    new_series_data = {
                        "_id": series_data.get('key', series_data.get('_id')),
                        "title": series_data.get('title', 'Unknown'),
                        "released_on": series_data.get('released_on', 'N/A'),
                        "genre": series_data.get('genre', 'N/A'),
                        "rating": series_data.get('rating', 'N/A'),
                        "media_type": series_data.get('media_type', 'tv'),
                        "published": True,  # Mark all migrated series as published
                        "languages": [],
                        "language_layout": [1] * len(series_data.get('languages', [])),
                        "poster_file_id": None
                    }
                    
                    # Get poster for this series
                    poster_doc = self.old_posters_collection.find_one({"series_key": series_data.get('key')})
                    if poster_doc:
                        new_series_data["poster_file_id"] = poster_doc.get('poster_url')
                    
                    # Process languages
                    languages = series_data.get('languages', [])
                    for language in languages:
                        language_name = language if isinstance(language, str) else language.get('name', 'Unknown')
                        
                        # Create language object
                        language_obj = {
                            "name": language_name,
                            "seasons": [],
                            "season_layout":import os
import asyncio
import logging
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import BulkWriteError
from info import ADMINS, DATABASE_URI, NEW_DATABASE_URI, MIGRATION_MODE
from pyrogram import Client, filters
from pyrogram.types import Message

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MongoToMongoMigration:
    def __init__(self):
        self.old_mongo_uri = DATABASE_URI
        self.new_mongo_uri = NEW_DATABASE_URI
        self.batch_size = 100
        
    async def connect_databases(self):
        """Connect to both old and new MongoDB databases"""
        try:
            # Connect to old MongoDB
            self.old_client = MongoClient(self.old_mongo_uri)
            self.old_db = self.old_client['series_database']
            self.old_series_collection = self.old_db['series']
            self.old_links_collection = self.old_db['series_links']
            self.old_posters_collection = self.old_db['posters']
            self.old_episodes_collection = self.old_db.get('episodes', None)
            logger.info("Connected to old MongoDB successfully")
            
            # Connect to new MongoDB
            self.new_client = MongoClient(self.new_mongo_uri)
            self.new_db = self.new_client['series_database']
            self.new_series_collection = self.new_db['series']
            self.new_episodes_collection = self.new_db['episodes']
            self.new_posters_collection = self.new_db['posters']
            self.new_admin_assignments_collection = self.new_db['admin_assignments']
            logger.info("Connected to new MongoDB successfully")
            
            return True
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            return False
    
    async def migrate_series(self, progress_callback=None):
        """Migrate series data from old MongoDB to new MongoDB"""
        try:
            # Get all series from old MongoDB
            series_list = list(self.old_series_collection.find())
            total_series = len(series_list)
            logger.info(f"Found {total_series} series to migrate")
            
            migrated_series = 0
            skipped_series = 0
            
            # Prepare batch operations
            series_batch = []
            episodes_batch = []
            posters_batch = []
            
            for series_data in series_list:
                try:
                    # Transform series data to new structure
                    new_series_data = {
                        "_id": series_data.get('key', series_data.get('_id')),
                        "title": series_data.get('title', 'Unknown'),
                        "released_on": series_data.get('released_on', 'N/A'),
                        "genre": series_data.get('genre', 'N/A'),
                        "rating": series_data.get('rating', 'N/A'),
                        "media_type": series_data.get('media_type', 'tv'),
                        "published": True,  # Mark all migrated series as published
                        "languages": [],
                        "language_layout": [1] * len(series_data.get('languages', [])),
                        "poster_file_id": None
                    }
                    
                    # Get poster for this series
                    poster_doc = self.old_posters_collection.find_one({"series_key": series_data.get('key')})
                    if poster_doc:
                        new_series_data["poster_file_id"] = poster_doc.get('poster_url')
                    
                    # Process languages
                    languages = series_data.get('languages', [])
                    for language in languages:
                        language_name = language if isinstance(language, str) else language.get('name', 'Unknown')
                        
                        # Create language object
                        language_obj = {
                            "name": language_name,
                            "seasons": [],
                            "season_layout": [],
                            "poster_file_id": None
                        }
                        
                        # Get seasons for this language
                        seasons = series_data.get('seasons', {})
                        if isinstance(seasons, dict):
                            season_names = list(seasons.keys())
                        elif isinstance(seasons, list):
                            season_names = [s.get('name', 'Unknown') for s in seasons]
                        else:
                            season_names = []
                        
                        # Set season layout (1 button per row by default)
                        language_obj["season_layout"] = [1] * len(season_names)
                        
                        for season_name in season_names:
                            # Create season object
                            season_obj = {
                                "name": season_name,
                                "qualities": [],
                                "quality_layout": [],
                                "poster_file_id": None
                            }
                            
                            # Get links for this season
                            link_key = f"{series_data.get('key')}-{language_name.lower().replace(' ', '')}-{season_name.lower().replace(' ', '')}"
                            links_doc = self.old_links_collection.find_one({"series_key": link_key})
                            
                            if links_doc:
                                links = links_doc.get("links", {})
                                quality_names = list(links.keys())
                                
                                # Set quality layout (1 button per row by default)
                                season_obj["quality_layout"] = [1] * len(quality_names)
                                
                                for quality_name, link_value in links.items():
                                    # Create quality object
                                    quality_obj = {
                                        "name": quality_name,
                                        "link_key": link_value
                                    }
                                    
                                    # Add to episodes collection if needed
                                    if link_value and not link_value.startswith("get_"):
                                        episodes_batch.append({
                                            "file_link_key": link_value,
                                            "files": [{"file_id": link_value, "caption": ""}],
                                            "channel_id": 0,
                                            "first_msg_id": 0,
                                            "last_msg_id": 0
                                        })
                                    
                                    season_obj["qualities"].append(quality_obj)
                            
                            language_obj["seasons"].append(season_obj)
                        
                        new_series_data["languages"].append(language_obj)
                    
                    # Add to batch
                    series_batch.append(new_series_data)
                    
                    # Add poster to batch if exists
                    if poster_doc:
                        posters_batch.append({
                            "series_key": series_data.get('key'),
                            "poster_url": poster_doc.get('poster_url')
                        })
                    
                    # Process batch if it reaches batch size
                    if len(series_batch) >= self.batch_size:
                        await self.process_batches(series_batch, episodes_batch, posters_batch)
                        series_batch = []
                        episodes_batch = []
                        posters_batch = []
                    
                    migrated_series += 1
                    if progress_callback and migrated_series % 10 == 0:
                        await progress_callback(migrated_series, total_series)
                        
                except Exception as e:
                    logger.error(f"Error migrating series {series_data.get('key')}: {e}")
                    skipped_series += 1
            
            # Process remaining items in batches
            if series_batch:
                await self.process_batches(series_batch, episodes_batch, posters_batch)
            
            # Migrate episodes collection if it exists in old database
            if self.old_episodes_collection:
                await self.migrate_episodes_collection()
            
            logger.info(f"Migration completed: {migrated_series} series migrated, {skipped_series} skipped")
            return {"migrated": migrated_series, "skipped": skipped_series}
            
        except Exception as e:
            logger.error(f"Error during migration: {e}")
            return {"migrated": 0, "skipped": len(series_list) if 'series_list' in locals() else 0}
    
    async def process_batches(self, series_batch, episodes_batch, posters_batch):
        """Process and insert batches into new database"""
        try:
            # Insert series batch
            if series_batch:
                self.new_series_collection.insert_many(series_batch, ordered=False)
            
            # Insert episodes batch
            if episodes_batch:
                # Remove duplicates based on file_link_key
                unique_episodes = {}
                for episode in episodes_batch:
                    key = episode["file_link_key"]
                    if key not in unique_episodes:
                        unique_episodes[key] = episode
                    else:
                        # Merge files if duplicate key
                        unique_episodes[key]["files"].extend(episode["files"])
                
                self.new_episodes_collection.insert_many(list(unique_episodes.values()), ordered=False)
            
            # Insert posters batch
            if posters_batch:
                self.new_posters_collection.insert_many(posters_batch, ordered=False)
                
        except BulkWriteError as bwe:
            logger.warning(f"Bulk write error: {bwe.details}")
        except Exception as e:
            logger.error(f"Error processing batches: {e}")
    
    async def migrate_episodes_collection(self):
        """Migrate episodes collection from old to new database"""
        try:
            episodes_list = list(self.old_episodes_collection.find())
            total_episodes = len(episodes_list)
            logger.info(f"Found {total_episodes} episodes to migrate")
            
            migrated_episodes = 0
            episodes_batch = []
            
            for episode_data in episodes_list:
                try:
                    # Transform episode data to new structure
                    new_episode_data = {
                        "file_link_key": episode_data.get("file_link_key"),
                        "files": episode_data.get("files", []),
                        "channel_id": episode_data.get("channel_id", 0),
                        "first_msg_id": episode_data.get("first_msg_id", 0),
                        "last_msg_id": episode_data.get("last_msg_id", 0)
                    }
                    
                    episodes_batch.append(new_episode_data)
                    
                    # Process batch if it reaches batch size
                    if len(episodes_batch) >= self.batch_size:
                        self.new_episodes_collection.insert_many(episodes_batch, ordered=False)
                        episodes_batch = []
                    
                    migrated_episodes += 1
                    
                except Exception as e:
                    logger.error(f"Error migrating episode {episode_data.get('file_link_key')}: {e}")
            
            # Process remaining items in batch
            if episodes_batch:
                self.new_episodes_collection.insert_many(episodes_batch, ordered=False)
            
            logger.info(f"Episodes migration completed: {migrated_episodes} episodes migrated")
            
        except Exception as e:
            logger.error(f"Error during episodes migration: {e}")
    
    async def close_connections(self):
        """Close database connections"""
        try:
            if hasattr(self, 'old_client'):
                self.old_client.close()
            if hasattr(self, 'new_client'):
                self.new_client.close()
            logger.info("Database connections closed")
        except Exception as e:
            logger.error(f"Error closing connections: {e}")

# Create migration instance
migration = MongoToMongoMigration()

@Client.on_message(filters.command("migrate_mongo") & filters.user(ADMINS))
async def start_migration(client: Client, message: Message):
    """Start the migration process from old MongoDB to new MongoDB"""
    try:
        progress_msg = await message.reply("🔄 **Starting MongoDB Migration**\n\nConnecting to databases...")
        
        # Check if MIGRATION_MODE is enabled
        if not MIGRATION_MODE:
            await progress_msg.edit("❌ **Migration Failed**\n\nMIGRATION_MODE is not enabled in info.py. Please set MIGRATION_MODE = True and restart the bot.")
            return
        
        # Connect to databases
        if not await migration.connect_databases():
            await progress_msg.edit("❌ **Migration Failed**\n\nCould not connect to databases. Check your MongoDB URIs.")
            return
        
        await progress_msg.edit("🔄 **Migrating Data**\n\nStarting series migration...")
        
        # Progress callback function
        async def update_progress(migrated, total):
            try:
                await progress_msg.edit(
                    f"🔄 **Migrating Data**\n\n"
                    f"Progress: {migrated}/{total} series\n"
                    f"Percentage: {migrated/total*100:.1f}%"
                )
            except:
                pass
        
        # Start migration
        results = await migration.migrate_series(update_progress)
        
        # Close connections
        await migration.close_connections()
        
        # Send results
        await progress_msg.edit(
            f"✅ **Migration Completed**\n\n"
            f"📊 **Results:**\n"
            f"• Migrated: {results['migrated']} series\n"
            f"• Skipped: {results['skipped']} series\n\n"
            f"🎉 All data has been successfully migrated to the new MongoDB!\n\n"
            f"⚠️ **Important:** Please set MIGRATION_MODE = False in info.py and restart the bot to use the new database."
        )
        
    except Exception as e:
        logger.error(f"Migration error: {e}", exc_info=True)
        await message.reply(f"❌ **Migration Failed**\n\nError: {str(e)}")

@Client.on_message(filters.command("check_migration") & filters.user(ADMINS))
async def check_migration_status(client: Client, message: Message):
    """Check the status of migrated data in new MongoDB"""
    try:
        status_msg = await message.reply("🔍 **Checking Migration Status**\n\nConnecting to new MongoDB...")
        
        # Connect to new MongoDB
        if not hasattr(migration, 'new_client') or migration.new_client is None:
            if not await migration.connect_databases():
                await status_msg.edit("❌ **Status Check Failed**\n\nCould not connect to new MongoDB.")
                return
        
        # Get counts from each collection
        series_count = migration.new_series_collection.count_documents({})
        episodes_count = migration.new_episodes_collection.count_documents({})
        posters_count = migration.new_posters_collection.count_documents({})
        
        # Get sample data
        sample_series = list(migration.new_series_collection.find().limit(5))
        sample_text = "\n".join([f"• {s['title']} ({s['_id']})" for s in sample_series])
        
        await status_msg.edit(
            f"📊 **Migration Status Report**\n\n"
            f"📈 **Data Counts:**\n"
            f"• Series: {series_count}\n"
            f"• Episodes: {episodes_count}\n"
            f"• Posters: {posters_count}\n\n"
            f"📝 **Sample Series:**\n{sample_text}"
        )
        
        # Close connections
        await migration.close_connections()
        
    except Exception as e:
        logger.error(f"Status check error: {e}", exc_info=True)
        await message.reply(f"❌ **Status Check Failed**\n\nError: {str(e)}")

@Client.on_message(filters.command("rollback_migration") & filters.user(ADMINS))
async def rollback_migration(client: Client, message: Message):
    """Rollback the migration by dropping all collections in the new database"""
    try:
        confirm_msg = await message.reply(
            "⚠️ **Rollback Migration**\n\n"
            "This will permanently delete all migrated data from the new MongoDB.\n\n"
            "Reply with 'CONFIRM' to continue or 'CANCEL' to abort."
        )
        
        # Wait for confirmation
        response = await client.listen(filters.text & filters.user(message.from_user.id), timeout=30)
        if response.text.upper() != "CONFIRM":
            await confirm_msg.edit("❌ **Rollback Aborted**")
            return
        
        await confirm_msg.edit("🔄 **Rolling Back Migration**\n\nDropping collections...")
        
        # Connect to new MongoDB
        if not hasattr(migration, 'new_client') or migration.new_client is None:
            if not await migration.connect_databases():
                await confirm_msg.edit("❌ **Rollback Failed**\n\nCould not connect to new MongoDB.")
                return
        
        # Drop collections
        migration.new_series_collection.drop()
        migration.new_episodes_collection.drop()
        migration.new_posters_collection.drop()
        migration.new_admin_assignments_collection.drop()
        
        await confirm_msg.edit("✅ **Rollback Completed**\n\nAll collections have been dropped. Migration data has been removed.")
        
        # Close connections
        await migration.close_connections()
        
    except Exception as e:
        logger.error(f"Rollback error: {e}", exc_info=True)
        await message.reply(f"❌ **Rollback Failed**\n\nError: {str(e)}")import os
import asyncio
import logging
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import BulkWriteError
from info import ADMINS, DATABASE_URI, NEW_DATABASE_URI, MIGRATION_MODE
from pyrogram import Client, filters
from pyrogram.types import Message

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MongoToMongoMigration:
    def __init__(self):
        self.old_mongo_uri = DATABASE_URI
        self.new_mongo_uri = NEW_DATABASE_URI
        self.batch_size = 100
        
    async def connect_databases(self):
        """Connect to both old and new MongoDB databases"""
        try:
            # Connect to old MongoDB
            self.old_client = MongoClient(self.old_mongo_uri)
            self.old_db = self.old_client['series_database']
            self.old_series_collection = self.old_db['series']
            self.old_links_collection = self.old_db['series_links']
            self.old_posters_collection = self.old_db['posters']
            self.old_episodes_collection = self.old_db.get('episodes', None)
            logger.info("Connected to old MongoDB successfully")
            
            # Connect to new MongoDB
            self.new_client = MongoClient(self.new_mongo_uri)
            self.new_db = self.new_client['series_database']
            self.new_series_collection = self.new_db['series']
            self.new_episodes_collection = self.new_db['episodes']
            self.new_posters_collection = self.new_db['posters']
            self.new_admin_assignments_collection = self.new_db['admin_assignments']
            logger.info("Connected to new MongoDB successfully")
            
            return True
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            return False
    
    async def migrate_series(self, progress_callback=None):
        """Migrate series data from old MongoDB to new MongoDB"""
        try:
            # Get all series from old MongoDB
            series_list = list(self.old_series_collection.find())
            total_series = len(series_list)
            logger.info(f"Found {total_series} series to migrate")
            
            migrated_series = 0
            skipped_series = 0
            
            # Prepare batch operations
            series_batch = []
            episodes_batch = []
            posters_batch = []
            
            for series_data in series_list:
                try:
                    # Transform series data to new structure
                    new_series_data = {
                        "_id": series_data.get('key', series_data.get('_id')),
                        "title": series_data.get('title', 'Unknown'),
                        "released_on": series_data.get('released_on', 'N/A'),
                        "genre": series_data.get('genre', 'N/A'),
                        "rating": series_data.get('rating', 'N/A'),
                        "media_type": series_data.get('media_type', 'tv'),
                        "published": True,  # Mark all migrated series as published
                        "languages": [],
                        "language_layout": [1] * len(series_data.get('languages', [])),
                        "poster_file_id": None
                    }
                    
                    # Get poster for this series
                    poster_doc = self.old_posters_collection.find_one({"series_key": series_data.get('key')})
                    if poster_doc:
                        new_series_data["poster_file_id"] = poster_doc.get('poster_url')
                    
                    # Process languages
                    languages = series_data.get('languages', [])
                    for language in languages:
                        language_name = language if isinstance(language, str) else language.get('name', 'Unknown')
                        
                        # Create language object
                        language_obj = {
                            "name": language_name,
                            "seasons": [],
                            "season_layout": [],
                            "poster_file_id": None
                        }
                        
                        # Get seasons for this language
                        seasons = series_data.get('seasons', {})
                        if isinstance(seasons, dict):
                            season_names = list(seasons.keys())
                        elif isinstance(seasons, list):
                            season_names = [s.get('name', 'Unknown') for s in seasons]
                        else:
                            season_names = []
                        
                        # Set season layout (1 button per row by default)
                        language_obj["season_layout"] = [1] * len(season_names)
                        
                        for season_name in season_names:
                            # Create season object
                            season_obj = {
                                "name": season_name,
                                "qualities": [],
                                "quality_layout": [],
                                "poster_file_id": None
                            }
                            
                            # Get links for this season
                            link_key = f"{series_data.get('key')}-{language_name.lower().replace(' ', '')}-{season_name.lower().replace(' ', '')}"
                            links_doc = self.old_links_collection.find_one({"series_key": link_key})
                            
                            if links_doc:
                                links = links_doc.get("links", {})
                                quality_names = list(links.keys())
                                
                                # Set quality layout (1 button per row by default)
                                season_obj["quality_layout"] = [1] * len(quality_names)
                                
                                for quality_name, link_value in links.items():
                                    # Create quality object
                                    quality_obj = {
                                        "name": quality_name,
                                        "link_key": link_value
                                    }
                                    
                                    # Add to episodes collection if needed
                                    if link_value and not link_value.startswith("get_"):
                                        episodes_batch.append({
                                            "file_link_key": link_value,
                                            "files": [{"file_id": link_value, "caption": ""}],
                                            "channel_id": 0,
                                            "first_msg_id": 0,
                                            "last_msg_id": 0
                                        })
                                    
                                    season_obj["qualities"].append(quality_obj)
                            
                            language_obj["seasons"].append(season_obj)
                        
                        new_series_data["languages"].append(language_obj)
                    
                    # Add to batch
                    series_batch.append(new_series_data)
                    
                    # Add poster to batch if exists
                    if poster_doc:
                        posters_batch.append({
                            "series_key": series_data.get('key'),
                            "poster_url": poster_doc.get('poster_url')
                        })
                    
                    # Process batch if it reaches batch size
                    if len(series_batch) >= self.batch_size:
                        await self.process_batches(series_batch, episodes_batch, posters_batch)
                        series_batch = []
                        episodes_batch = []
                        posters_batch = []
                    
                    migrated_series += 1
                    if progress_callback and migrated_series % 10 == 0:
                        await progress_callback(migrated_series, total_series)
                        
                except Exception as e:
                    logger.error(f"Error migrating series {series_data.get('key')}: {e}")
                    skipped_series += 1
            
            # Process remaining items in batches
            if series_batch:
                await self.process_batches(series_batch, episodes_batch, posters_batch)
            
            # Migrate episodes collection if it exists in old database
            if self.old_episodes_collection:
                await self.migrate_episodes_collection()
            
            logger.info(f"Migration completed: {migrated_series} series migrated, {skipped_series} skipped")
            return {"migrated": migrated_series, "skipped": skipped_series}
            
        except Exception as e:
            logger.error(f"Error during migration: {e}")
            return {"migrated": 0, "skipped": len(series_list) if 'series_list' in locals() else 0}
    
    async def process_batches(self, series_batch, episodes_batch, posters_batch):
        """Process and insert batches into new database"""
        try:
            # Insert series batch
            if series_batch:
                self.new_series_collection.insert_many(series_batch, ordered=False)
            
            # Insert episodes batch
            if episodes_batch:
                # Remove duplicates based on file_link_key
                unique_episodes = {}
                for episode in episodes_batch:
                    key = episode["file_link_key"]
                    if key not in unique_episodes:
                        unique_episodes[key] = episode
                    else:
                        # Merge files if duplicate key
                        unique_episodes[key]["files"].extend(episode["files"])
                
                self.new_episodes_collection.insert_many(list(unique_episodes.values()), ordered=False)
            
            # Insert posters batch
            if posters_batch:
                self.new_posters_collection.insert_many(posters_batch, ordered=False)
                
        except BulkWriteError as bwe:
            logger.warning(f"Bulk write error: {bwe.details}")
        except Exception as e:
            logger.error(f"Error processing batches: {e}")
    
    async def migrate_episodes_collection(self):
        """Migrate episodes collection from old to new database"""
        try:
            episodes_list = list(self.old_episodes_collection.find())
            total_episodes = len(episodes_list)
            logger.info(f"Found {total_episodes} episodes to migrate")
            
            migrated_episodes = 0
            episodes_batch = []
            
            for episode_data in episodes_list:
                try:
                    # Transform episode data to new structure
                    new_episode_data = {
                        "file_link_key": episode_data.get("file_link_key"),
                        "files": episode_data.get("files", []),
                        "channel_id": episode_data.get("channel_id", 0),
                        "first_msg_id": episode_data.get("first_msg_id", 0),
                        "last_msg_id": episode_data.get("last_msg_id", 0)
                    }
                    
                    episodes_batch.append(new_episode_data)
                    
                    # Process batch if it reaches batch size
                    if len(episodes_batch) >= self.batch_size:
                        self.new_episodes_collection.insert_many(episodes_batch, ordered=False)
                        episodes_batch = []
                    
                    migrated_episodes += 1
                    
                except Exception as e:
                    logger.error(f"Error migrating episode {episode_data.get('file_link_key')}: {e}")
            
            # Process remaining items in batch
            if episodes_batch:
                self.new_episodes_collection.insert_many(episodes_batch, ordered=False)
            
            logger.info(f"Episodes migration completed: {migrated_episodes} episodes migrated")
            
        except Exception as e:
            logger.error(f"Error during episodes migration: {e}")
    
    async def close_connections(self):import os
import asyncio
import logging
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import BulkWriteError
from info import ADMINS, DATABASE_URI, NEW_DATABASE_URI, MIGRATION_MODE
from pyrogram import Client, filters
from pyrogram.types import Message

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MongoToMongoMigration:
    def __init__(self):
        self.old_mongo_uri = DATABASE_URI
        self.new_mongo_uri = NEW_DATABASE_URI
        self.batch_size = 100
        
    async def connect_databases(self):
        """Connect to both old and new MongoDB databases"""
        try:
            # Connect to old MongoDB
            self.old_client = MongoClient(self.old_mongo_uri)
            self.old_db = self.old_client['series_database']
            self.old_series_collection = self.old_db['series']
            self.old_links_collection = self.old_db['series_links']
            self.old_posters_collection = self.old_db['posters']
            self.old_episodes_collection = self.old_db.get('episodes', None)
            logger.info("Connected to old MongoDB successfully")
            
            # Connect to new MongoDB
            self.new_client = MongoClient(self.new_mongo_uri)
            self.new_db = self.new_client['series_database']
            self.new_series_collection = self.new_db['series']
            self.new_episodes_collection = self.new_db['episodes']
            self.new_posters_collection = self.new_db['posters']
            self.new_admin_assignments_collection = self.new_db['admin_assignments']
            logger.info("Connected to new MongoDB successfully")
            
            return True
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            return False
    
    async def migrate_series(self, progress_callback=None):
        """Migrate series data from old MongoDB to new MongoDB"""
        try:
            # Get all series from old MongoDB
            series_list = list(self.old_series_collection.find())
            total_series = len(series_list)
            logger.info(f"Found {total_series} series to migrate")
            
            migrated_series = 0
            skipped_series = 0
            
            # Prepare batch operations
            series_batch = []
            episodes_batch = []
            posters_batch = []
            
            for series_data in series_list:
                try:
                    # Transform series data to new structure
                    new_series_data = {
                        "_id": series_data.get('key', series_data.get('_id')),
                        "title": series_data.get('title', 'Unknown'),
                        "released_on": series_data.get('released_on', 'N/A'),
                        "genre": series_data.get('genre', 'N/A'),
                        "rating": series_data.get('rating', 'N/A'),
                        "media_type": series_data.get('media_type', 'tv'),
                        "published": True,  # Mark all migrated series as published
                        "languages": [],
                        "language_layout": [1] * len(series_data.get('languages', [])),
                        "poster_file_id": None
                    }
                    
                    # Get poster for this series
                    poster_doc = self.old_posters_collection.find_one({"series_key": series_data.get('key')})
                    if poster_doc:
                        new_series_data["poster_file_id"] = poster_doc.get('poster_url')
                    
                    # Process languages
                    languages = series_data.get('languages', [])
                    for language in languages:
                        language_name = language if isinstance(language, str) else language.get('name', 'Unknown')
                        
                        # Create language object
                        language_obj = {
                            "name": language_name,
                            "seasons": [],
                            "season_layout": [],
                            "poster_file_id": None
                        }
                        
                        # Get seasons for this language
                        seasons = series_data.get('seasons', {})
                        if isinstance(seasons, dict):
                            season_names = list(seasons.keys())
                        elif isinstance(seasons, list):
                            season_names = [s.get('name', 'Unknown') for s in seasons]
                        else:
                            season_names = []
                        
                        # Set season layout (1 button per row by default)
                        language_obj["season_layout"] = [1] * len(season_names)
                        
                        for season_name in season_names:
                            # Create season object
                            season_obj = {
                                "name": season_name,
                                "qualities": [],
                                "quality_layout": [],
                                "poster_file_id": None
                            }
                            
                            # Get links for this season
                            link_key = f"{series_data.get('key')}-{language_name.lower().replace(' ', '')}-{season_name.lower().replace(' ', '')}"
                            links_doc = self.old_links_collection.find_one({"series_key": link_key})
                            
                            if links_doc:
                                links = links_doc.get("links", {})
                                quality_names = list(links.keys())
                                
                                # Set quality layout (1 button per row by default)
                                season_obj["quality_layout"] = [1] * len(quality_names)
                                
                                for quality_name, link_value in links.items():
                                    # Create quality object
                                    quality_obj = {
                                        "name": quality_name,
                                        "link_key": link_value
                                    }
                                    
                                    # Add to episodes collection if needed
                                    if link_value and not link_value.startswith("get_"):
                                        episodes_batch.append({
                                            "file_link_key": link_value,
                                            "files": [{"file_id": link_value, "caption": ""}],
                                            "channel_id": 0,
                                            "first_msg_id": 0,
                                            "last_msg_id": 0
                                        })
                                    
                                    season_obj["qualities"].append(quality_obj)
                            
                            language_obj["seasons"].append(season_obj)
                        
                        new_series_data["languages"].append(language_obj)
                    
                    # Add to batch
                    series_batch.append(new_series_data)
                    
                    # Add poster to batch if exists
                    if poster_doc:
                        posters_batch.append({
                            "series_key": series_data.get('key'),
                            "poster_url": poster_doc.get('poster_url')
                        })
                    
                    # Process batch if it reaches batch size
                    if len(series_batch) >= self.batch_size:
                        await self.process_batches(series_batch, episodes_batch, posters_batch)
                        series_batch = []
                        episodes_batch = []
                        posters_batch = []
                    
                    migrated_series += 1
                    if progress_callback and migrated_series % 10 == 0:
                        await progress_callback(migrated_series, total_series)
                        
                except Exception as e:
                    logger.error(f"Error migrating series {series_data.get('key')}: {e}")
                    skipped_series += 1
            
            # Process remaining items in batches
            if series_batch:
                await self.process_batches(series_batch, episodes_batch, posters_batch)
            
            # Migrate episodes collection if it exists in old database
            if self.old_episodes_collection:
                await self.migrate_episodes_collection()
            
            logger.info(f"Migration completed: {migrated_series} series migrated, {skipped_series} skipped")
            return {"migrated": migrated_series, "skipped": skipped_series}
            
        except Exception as e:
            logger.error(f"Error during migration: {e}")
            return {"migrated": 0, "skipped": len(series_list) if 'series_list' in locals() else 0}
    
    async def process_batches(self, series_batch, episodes_batch, posters_batch):
        """Process and insert batches into new database"""
        try:
            # Insert series batch
            if series_batch:
                self.new_series_collection.insert_many(series_batch, ordered=False)
            
            # Insert episodes batch
            if episodes_batch:
                # Remove duplicates based on file_link_key
                unique_episodes = {}
                for episode in episodes_batch:
                    key = episode["file_link_key"]
                    if key not in unique_episodes:
                        unique_episodes[key] = episode
                    else:
                        # Merge files if duplicate key
                        unique_episodes[key]["files"].extend(episode["files"])
                
                self.new_episodes_collection.insert_many(list(unique_episodes.values()), ordered=False)
            
            # Insert posters batch
            if posters_batch:
                self.new_posters_collection.insert_many(posters_batch, ordered=False)
                
        except BulkWriteError as bwe:
            logger.warning(f"Bulk write error: {bwe.details}")
        except Exception as e:
            logger.error(f"Error processing batches: {e}")
    
    async def migrate_episodes_collection(self):
        """Migrate episodes collection from old to new database"""
        try:
            episodes_list = list(self.old_episodes_collection.find())
            total_episodes = len(episodes_list)
            logger.info(f"Found {total_episodes} episodes to migrate")
            
            migrated_episodes = 0
            episodes_batch = []
            
            for episode_data in episodes_list:
                try:
                    # Transform episode data to new structure
                    new_episode_data = {
                        "file_link_key": episode_data.get("file_link_key"),
                        "files": episode_data.get("files", []),
                        "channel_id": episode_data.get("channel_id", 0),
                        "first_msg_id": episode_data.get("first_msg_id", 0),
                        "last_msg_id": episode_data.get("last_msg_id", 0)
                    }
                    
                    episodes_batch.append(new_episode_data)
                    
                    # Process batch if it reaches batch size
                    if len(episodes_batch) >= self.batch_size:
                        self.new_episodes_collection.insert_many(episodes_batch, ordered=False)
                        episodes_batch = []
                    
                    migrated_episodes += 1
                    
                except Exception as e:
                    logger.error(f"Error migrating episode {episode_data.get('file_link_key')}: {e}")
            
            # Process remaining items in batch
            if episodes_batch:
                self.new_episodes_collection.insert_many(episodes_batch, ordered=False)
            
            logger.info(f"Episodes migration completed: {migrated_episodes} episodes migrated")
            
        except Exception as e:
            logger.error(f"Error during episodes migration: {e}")
    
    async def close_connections(self):
        """Close database connections"""
        try:
            if hasattr(self, 'old_client'):
                self.old_client.close()
            if hasattr(self, 'new_client'):
                self.new_client.close()
            logger.info("Database connections closed")
        except Exception as e:
            logger.error(f"Error closing connections: {e}")

# Create migration instance
migration = MongoToMongoMigration()

@Client.on_message(filters.command("migrate_mongo") & filters.user(ADMINS))
async def start_migration(client: Client, message: Message):
    """Start the migration process from old MongoDB to new MongoDB"""
    try:
        progress_msg = await message.reply("🔄 **Starting MongoDB Migration**\n\nConnecting to databases...")
        
        # Check if MIGRATION_MODE is enabled
        if not MIGRATION_MODE:
            await progress_msg.edit("❌ **Migration Failed**\n\nMIGRATION_MODE is not enabled in info.py. Please set MIGRATION_MODE = True and restart the bot.")
            return
        
        # Connect to databases
        if not await migration.connect_databases():
            await progress_msg.edit("❌ **Migration Failed**\n\nCould not connect to databases. Check your MongoDB URIs.")
            return
        
        await progress_msg.edit("🔄 **Migrating Data**\n\nStarting series migration...")
        
        # Progress callback function
        async def update_progress(migrated, total):
            try:
                await progress_msg.edit(
                    f"🔄 **Migrating Data**\n\n"
                    f"Progress: {migrated}/{total} series\n"
                    f"Percentage: {migrated/total*100:.1f}%"
                )
            except:
                pass
        
        # Start migration
        results = await migration.migrate_series(update_progress)
        
        # Close connections
        await migration.close_connections()
        
        # Send results
        await progress_msg.edit(
            f"✅ **Migration Completed**\n\n"
            f"📊 **Results:**\n"
            f"• Migrated: {results['migrated']} series\n"
            f"• Skipped: {results['skipped']} series\n\n"
            f"🎉 All data has been successfully migrated to the new MongoDB!\n\n"
            f"⚠️ **Important:** Please set MIGRATION_MODE = False in info.py and restart the bot to use the new database."
        )
        
    except Exception as e:
        logger.error(f"Migration error: {e}", exc_info=True)
        await message.reply(f"❌ **Migration Failed**\n\nError: {str(e)}")

@Client.on_message(filters.command("check_migration") & filters.user(ADMINS))
async def check_migration_status(client: Client, message: Message):
    """Check the status of migrated data in new MongoDB"""
    try:
        status_msg = await message.reply("🔍 **Checking Migration Status**\n\nConnecting to new MongoDB...")
        
        # Connect to new MongoDB
        if not hasattr(migration, 'new_client') or migration.new_client is None:
            if not await migration.connect_databases():
                await status_msg.edit("❌ **Status Check Failed**\n\nCould not connect to new MongoDB.")
                return
        
        # Get counts from each collection
        series_count = migration.new_series_collection.count_documents({})
        episodes_count = migration.new_episodes_collection.count_documents({})
        posters_count = migration.new_posters_collection.count_documents({})
        
        # Get sample data
        sample_series = list(migration.new_series_collection.find().limit(5))
        sample_text = "\n".join([f"• {s['title']} ({s['_id']})" for s in sample_series])
        
        await status_msg.edit(
            f"📊 **Migration Status Report**\n\n"
            f"📈 **Data Counts:**\n"
            f"• Series: {series_count}\n"
            f"• Episodes: {episodes_count}\n"
            f"• Posters: {posters_count}\n\n"
            f"📝 **Sample Series:**\n{sample_text}"
        )
        
        # Close connections
        await migration.close_connections()
        
    except Exception as e:
        logger.error(f"Status check error: {e}", exc_info=True)
        await message.reply(f"❌ **Status Check Failed**\n\nError: {str(e)}")

@Client.on_message(filters.command("rollback_migration") & filters.user(ADMINS))
async def rollback_migration(client: Client, message: Message):
    """Rollback the migration by dropping all collections in the new database"""
    try:
        confirm_msg = await message.reply(
            "⚠️ **Rollback Migration**\n\n"
            "This will permanently delete all migrated data from the new MongoDB.\n\n"
            "Reply with 'CONFIRM' to continue or 'CANCEL' to abort."
        )
        
        # Wait for confirmation
        response = await client.listen(filters.text & filters.user(message.from_user.id), timeout=30)
        if response.text.upper() != "CONFIRM":
            await confirm_msg.edit("❌ **Rollback Aborted**")
            return
        
        await confirm_msg.edit("🔄 **Rolling Back Migration**\n\nDropping collections...")
        
        # Connect to new MongoDB
        if not hasattr(migration, 'new_client') or migration.new_client is None:
            if not await migration.connect_databases():
                await confirm_msg.edit("❌ **Rollback Failed**\n\nCould not connect to new MongoDB.")
                return
        
        # Drop collections
        migration.new_series_collection.drop()
        migration.new_episodes_collection.drop()
        migration.new_posters_collection.drop()
        migration.new_admin_assignments_collection.drop()
        
        await confirm_msg.edit("✅ **Rollback Completed**\n\nAll collections have been dropped. Migration data has been removed.")
        
        # Close connections
        await migration.close_connections()
        
    except Exception as e:
        logger.error(f"Rollback error: {e}", exc_info=True)
        await message.reply(f"❌ **Rollback Failed**\n\nError: {str(e)}")
        """Close database connections"""
        try:
            if hasattr(self, 'old_client'):
                self.old_client.close()
            if hasattr(self, 'new_client'):
                self.new_client.close()
            logger.info("Database connections closed")
        except Exception as e:
            logger.error(f"Error closing connections: {e}")

# Create migration instance
migration = MongoToMongoMigration()

@Client.on_message(filters.command("migrate_mongo") & filters.user(ADMINS))
async def start_migration(client: Client, message: Message):
    """Start the migration process from old MongoDB to new MongoDB"""
    try:
        progress_msg = await message.reply("🔄 **Starting MongoDB Migration**\n\nConnecting to databases...")
        
        # Check if MIGRATION_MODE is enabled
        if not MIGRATION_MODE:
            await progress_msg.edit("❌ **Migration Failed**\n\nMIGRATION_MODE is not enabled in info.py. Please set MIGRATION_MODE = True and restart the bot.")
            return
        
        # Connect to databases
        if not await migration.connect_databases():
            await progress_msg.edit("❌ **Migration Failed**\n\nCould not connect to databases. Check your MongoDB URIs.")
            return
        
        await progress_msg.edit("🔄 **Migrating Data**\n\nStarting series migration...")
        
        # Progress callback function
        async def update_progress(migrated, total):
            try:
                await progress_msg.edit(
                    f"🔄 **Migrating Data**\n\n"
                    f"Progress: {migrated}/{total} series\n"
                    f"Percentage: {migrated/total*100:.1f}%"
                )
            except:
                pass
        
        # Start migration
        results = await migration.migrate_series(update_progress)
        
        # Close connections
        await migration.close_connections()
        
        # Send results
        await progress_msg.edit(
            f"✅ **Migration Completed**\n\n"
            f"📊 **Results:**\n"
            f"• Migrated: {results['migrated']} series\n"
            f"• Skipped: {results['skipped']} series\n\n"
            f"🎉 All data has been successfully migrated to the new MongoDB!\n\n"
            f"⚠️ **Important:** Please set MIGRATION_MODE = False in info.py and restart the bot to use the new database."
        )
        
    except Exception as e:
        logger.error(f"Migration error: {e}", exc_info=True)
        await message.reply(f"❌ **Migration Failed**\n\nError: {str(e)}")

@Client.on_message(filters.command("check_migration") & filters.user(ADMINS))
async def check_migration_status(client: Client, message: Message):
    """Check the status of migrated data in new MongoDB"""
    try:
        status_msg = await message.reply("🔍 **Checking Migration Status**\n\nConnecting to new MongoDB...")
        
        # Connect to new MongoDB
        if not hasattr(migration, 'new_client') or migration.new_client is None:
            if not await migration.connect_databases():
                await status_msg.edit("❌ **Status Check Failed**\n\nCould not connect to new MongoDB.")
                return
        
        # Get counts from each collection
        series_count = migration.new_series_collection.count_documents({})
        episodes_count = migration.new_episodes_collection.count_documents({})
        posters_count = migration.new_posters_collection.count_documents({})
        
        # Get sample data
        sample_series = list(migration.new_series_collection.find().limit(5))
        sample_text = "\n".join([f"• {s['title']} ({s['_id']})" for s in sample_series])
        
        await status_msg.edit(
            f"📊 **Migration Status Report**\n\n"
            f"📈 **Data Counts:**\n"
            f"• Series: {series_count}\n"
            f"• Episodes: {episodes_count}\n"
            f"• Posters: {posters_count}\n\n"
            f"📝 **Sample Series:**\n{sample_text}"
        )
        
        # Close connections
        await migration.close_connections()
        
    except Exception as e:
        logger.error(f"Status check error: {e}", exc_info=True)
        await message.reply(f"❌ **Status Check Failed**\n\nError: {str(e)}")

@Client.on_message(filters.command("rollback_migration") & filters.user(ADMINS))
async def rollback_migration(client: Client, message: Message):
    """Rollback the migration by dropping all collections in the new database"""
    try:
        confirm_msg = await message.reply(
            "⚠️ **Rollback Migration**\n\n"
            "This will permanently delete all migrated data from the new MongoDB.\n\n"
            "Reply with 'CONFIRM' to continue or 'CANCEL' to abort."
        )
        
        # Wait for confirmation
        response = await client.listen(filters.text & filters.user(message.from_user.id), timeout=30)
        if response.text.upper() != "CONFIRM":
            await confirm_msg.edit("❌ **Rollback Aborted**")
            return
        
        await confirm_msg.edit("🔄 **Rolling Back Migration**\n\nDropping collections...")
        
        # Connect to new MongoDB
        if not hasattr(migration, 'new_client') or migration.new_client is None:
            if not await migration.connect_databases():
                await confirm_msg.edit("❌ **Rollback Failed**\n\nCould not connect to new MongoDB.")
                return
        
        # Drop collections
        migration.new_series_collection.drop()
        migration.new_episodes_collection.drop()
        migration.new_posters_collection.drop()
        migration.new_admin_assignments_collection.drop()
        
        await confirm_msg.edit("✅ **Rollback Completed**\n\nAll collections have been dropped. Migration data has been removed.")
        
        # Close connections
        await migration.close_connections()
        
    except Exception as e:
        logger.error(f"Rollback error: {e}", exc_info=True)
        await message.reply(f"❌ **Rollback Failed**\n\nError: {str(e)}") [],
                            "poster_file_id": None
                        }
                        
                        # Get seasons for this language
                        seasons = series_data.get('seasons', {})
                        if isinstance(seasons, dict):
                            season_names = list(seasons.keys())
                        elif isinstance(seasons, list):
                            season_names = [s.get('name', 'Unknown') for s in seasons]
                        else:
                            season_names = []
                        
                        # Set season layout (1 button per row by default)
                        language_obj["season_layout"] = [1] * len(season_names)
                        
                        for season_name in season_names:
                            # Create season object
                            season_obj = {
                                "name": season_name,
                                "qualities": [],
                                "quality_layout": [],
                                "poster_file_id": None
                            }
                            
                            # Get links for this season
                            link_key = f"{series_data.get('key')}-{language_name.lower().replace(' ', '')}-{season_name.lower().replace(' ', '')}"
                            links_doc = self.old_links_collection.find_one({"series_key": link_key})
                            
                            if links_doc:
                                links = links_doc.get("links", {})
                                quality_names = list(links.keys())
                                
                                # Set quality layout (1 button per row by default)
                                season_obj["quality_layout"] = [1] * len(quality_names)
                                
                                for quality_name, link_value in links.items():
                                    # Create quality object
                                    quality_obj = {
                                        "name": quality_name,
                                        "link_key": link_value
                                    }
                                    
                                    # Add to episodes collection if needed
                                    if link_value and not link_value.startswith("get_"):
                                        episodes_batch.append({
                                            "file_link_key": link_value,
                                            "files": [{"file_id": link_value, "caption": ""}],
                                            "channel_id": 0,
                                            "first_msg_id": 0,
                                            "last_msg_id": 0
                                        })
                                    
                                    season_obj["qualities"].append(quality_obj)
                            
                            language_obj["seasons"].append(season_obj)
                        
                        new_series_data["languages"].append(language_obj)
                    
                    # Add to batch
                    series_batch.append(new_series_data)
                    
                    # Add poster to batch if exists
                    if poster_doc:
                        posters_batch.append({
                            "series_key": series_data.get('key'),
                            "poster_url": poster_doc.get('poster_url')
                        })
                    
                    # Process batch if it reaches batch size
                    if len(series_batch) >= self.batch_size:
                        await self.process_batches(series_batch, episodes_batch, posters_batch)
                        series_batch = []
                        episodes_batch = []
                        posters_batch = []
                    
                    migrated_series += 1
                    if progress_callback and migrated_series % 10 == 0:
                        await progress_callback(migrated_series, total_series)
                        
                except Exception as e:
                    logger.error(f"Error migrating series {series_data.get('key')}: {e}")
                    skipped_series += 1
            
            # Process remaining items in batches
            if series_batch:
                await self.process_batches(series_batch, episodes_batch, posters_batch)
            
            # Migrate episodes collection if it exists in old database
            if self.old_episodes_collection:
                await self.migrate_episodes_collection()
            
            logger.info(f"Migration completed: {migrated_series} series migrated, {skipped_series} skipped")
            return {"migrated": migrated_series, "skipped": skipped_series}
            
        except Exception as e:
            logger.error(f"Error during migration: {e}")
            return {"migrated": 0, "skipped": len(series_list) if 'series_list' in locals() else 0}
    
    async def process_batches(self, series_batch, episodes_batch, posters_batch):
        """Process and insert batches into new database"""
        try:
            # Insert series batch
            if series_batch:
                self.new_series_collection.insert_many(series_batch, ordered=False)
            
            # Insert episodes batch
            if episodes_batch:
                # Remove duplicates based on file_link_key
                unique_episodes = {}
                for episode in episodes_batch:
                    key = episode["file_link_key"]
                    if key not in unique_episodes:
                        unique_episodes[key] = episode
                    else:
                        # Merge files if duplicate key
                        unique_episodes[key]["files"].extend(episode["files"])
                
                self.new_episodes_collection.insert_many(list(unique_episodes.values()), ordered=False)
            
            # Insert posters batch
            if posters_batch:
                self.new_posters_collection.insert_many(posters_batch, ordered=False)
                
        except BulkWriteError as bwe:
            logger.warning(f"Bulk write error: {bwe.details}")
        except Exception as e:
            logger.error(f"Error processing batches: {e}")
    
    async def migrate_episodes_collection(self):
        """Migrate episodes collection from old to new database"""
        try:
            episodes_list = list(self.old_episodes_collection.find())
            total_episodes = len(episodes_list)
            logger.info(f"Found {total_episodes} episodes to migrate")
            
            migrated_episodes = 0
            episodes_batch = []
            
            for episode_data in episodes_list:
                try:
                    # Transform episode data to new structure
                    new_episode_data = {
                        "file_link_key": episode_data.get("file_link_key"),
                        "files": episode_data.get("files", []),
                        "channel_id": episode_data.get("channel_id", 0),
                        "first_msg_id": episode_data.get("first_msg_id", 0),
                        "last_msg_id": episode_data.get("last_msg_id", 0)
                    }
                    
                    episodes_batch.append(new_episode_data)
                    
                    # Process batch if it reaches batch size
                    if len(episodes_batch) >= self.batch_size:
                        self.new_episodes_collection.insert_many(episodes_batch, ordered=False)
                        episodes_batch = []
                    
                    migrated_episodes += 1
                    
                except Exception as e:
                    logger.error(f"Error migrating episode {episode_data.get('file_link_key')}: {e}")
            
            # Process remaining items in batch
            if episodes_batch:
                self.new_episodes_collection.insert_many(episodes_batch, ordered=False)
            
            logger.info(f"Episodes migration completed: {migrated_episodes} episodes migrated")
            
        except Exception as e:
            logger.error(f"Error during episodes migration: {e}")
    
    async def close_connections(self):
        """Close database connections"""
        try:
            if hasattr(self, 'old_client'):
                self.old_client.close()
            if hasattr(self, 'new_client'):
                self.new_client.close()
            logger.info("Database connections closed")
        except Exception as e:
            logger.error(f"Error closing connections: {e}")

# Create migration instance
migration = MongoToMongoMigration()

@Client.on_message(filters.command("migrate_mongo") & filters.user(ADMINS))
async def start_migration(client: Client, message: Message):
    """Start the migration process from old MongoDB to new MongoDB"""
    try:
        progress_msg = await message.reply("🔄 **Starting MongoDB Migration**\n\nConnecting to databases...")
        
        # Check if MIGRATION_MODE is enabled
        if not MIGRATION_MODE:
            await progress_msg.edit("❌ **Migration Failed**\n\nMIGRATION_MODE is not enabled in info.py. Please set MIGRATION_MODE = True and restart the bot.")
            return
        
        # Connect to databases
        if not await migration.connect_databases():
            await progress_msg.edit("❌ **Migration Failed**\n\nCould not connect to databases. Check your MongoDB URIs.")
            return
        
        await progress_msg.edit("🔄 **Migrating Data**\n\nStarting series migration...")
        
        # Progress callback function
        async def update_progress(migrated, total):
            try:
                await progress_msg.edit(
                    f"🔄 **Migrating Data**\n\n"
                    f"Progress: {migrated}/{total} series\n"
                    f"Percentage: {migrated/total*100:.1f}%"
                )
            except:
                pass
        
        # Start migration
        results = await migration.migrate_series(update_progress)
        
        # Close connections
        await migration.close_connections()
        
        # Send results
        await progress_msg.edit(
            f"✅ **Migration Completed**\n\n"
            f"📊 **Results:**\n"
            f"• Migrated: {results['migrated']} series\n"
            f"• Skipped: {results['skipped']} series\n\n"
            f"🎉 All data has been successfully migrated to the new MongoDB!\n\n"
            f"⚠️ **Important:** Please set MIGRATION_MODE = False in info.py and restart the bot to use the new database."
        )
        
    except Exception as e:
        logger.error(f"Migration error: {e}", exc_info=True)
        await message.reply(f"❌ **Migration Failed**\n\nError: {str(e)}")

@Client.on_message(filters.command("check_migration") & filters.user(ADMINS))
async def check_migration_status(client: Client, message: Message):
    """Check the status of migrated data in new MongoDB"""
    try:
        status_msg = await message.reply("🔍 **Checking Migration Status**\n\nConnecting to new MongoDB...")
        
        # Connect to new MongoDB
        if not hasattr(migration, 'new_client') or migration.new_client is None:
            if not await migration.connect_databases():
                await status_msg.edit("❌ **Status Check Failed**\n\nCould not connect to new MongoDB.")
                return
        
        # Get counts from each collection
        series_count = migration.new_series_collection.count_documents({})
        episodes_count = migration.new_episodes_collection.count_documents({})
        posters_count = migration.new_posters_collection.count_documents({})
        
        # Get sample data
        sample_series = list(migration.new_series_collection.find().limit(5))
        sample_text = "\n".join([f"• {s['title']} ({s['_id']})" for s in sample_series])
        
        await status_msg.edit(
            f"📊 **Migration Status Report**\n\n"
            f"📈 **Data Counts:**\n"
            f"• Series: {series_count}\n"
            f"• Episodes: {episodes_count}\n"
            f"• Posters: {posters_count}\n\n"
            f"📝 **Sample Series:**\n{sample_text}"
        )
        
        # Close connections
        await migration.close_connections()
        
    except Exception as e:
        logger.error(f"Status check error: {e}", exc_info=True)
        await message.reply(f"❌ **Status Check Failed**\n\nError: {str(e)}")

@Client.on_message(filters.command("rollback_migration") & filters.user(ADMINS))
async def rollback_migration(client: Client, message: Message):
    """Rollback the migration by dropping all collections in the new database"""
    try:
        confirm_msg = await message.reply(
            "⚠️ **Rollback Migration**\n\n"
            "This will permanently delete all migrated data from the new MongoDB.\n\n"
            "Reply with 'CONFIRM' to continue or 'CANCEL' to abort."
        )
        
        # Wait for confirmation
        response = await client.listen(filters.text & filters.user(message.from_user.id), timeout=30)
        if response.text.upper() != "CONFIRM":
            await confirm_msg.edit("❌ **Rollback Aborted**")
            return
        
        await confirm_msg.edit("🔄 **Rolling Back Migration**\n\nDropping collections...")
        
        # Connect to new MongoDB
        if not hasattr(migration, 'new_client') or migration.new_client is None:
            if not await migration.connect_databases():
                await confirm_msg.edit("❌ **Rollback Failed**\n\nCould not connect to new MongoDB.")
                return
        
        # Drop collections
        migration.new_series_collection.drop()
        migration.new_episodes_collection.drop()
        migration.new_posters_collection.drop()
        migration.new_admin_assignments_collection.drop()
        
        await confirm_msg.edit("✅ **Rollback Completed**\n\nAll collections have been dropped. Migration data has been removed.")
        
        # Close connections
        await migration.close_connections()
        
    except Exception as e:
        logger.error(f"Rollback error: {e}", exc_info=True)
        await message.reply(f"❌ **Rollback Failed**\n\nError: {str(e)}")
