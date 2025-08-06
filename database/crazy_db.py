from pymongo import MongoClient
from info import DATABASE_URI
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

client = MongoClient(DATABASE_URI)
db = client['series_database']
series_collection = db['series']
posters_collection = db['posters'] # For manual poster overrides

# New: episodes collection for file links, moved from genlink.py
episodes_collection = client["file_database"]["episodes"]

async def add_poster_to_db(series_key, poster_url):
  result = posters_collection.update_one(
      {'series_key': series_key},
      {'$set': {'poster_url': poster_url}},
      upsert=True
  )
  return result.modified_count > 0 or result.upserted_id is not None

def get_poster_manuel(series_key):
  poster = posters_collection.find_one({'series_key': series_key})
  return poster['poster_url'] if poster else None
  
def get_series():
  return list(series_collection.find())

def get_series_name(name):
  document = series_collection.find_one({"key": name.lower().replace(" ", "")})
  if document:
      return document
  return {}

async def add_series(series_data):
  """Adds or updates a series with its full nested structure."""
  series_key = series_data['key']
  await series_collection.update_one({"key": series_key}, {"$set": series_data}, upsert=True)
  logger.info(f"Series '{series_key}' added/updated in crazy_db.")

async def delete_series_and_links(series_key):
  """Deletes a series and all its associated file links."""
  await series_collection.delete_one({"key": series_key})
  # Delete all associated file links from episodes collection
  await episodes_collection.delete_many({"file_link_key": {"$regex": f"^{series_key}-"}})
  logger.info(f"Series '{series_key}' and its links deleted.")

async def delete_all_series_and_links():
  """Deletes all series and all associated file links."""
  await series_collection.delete_many({})
  await episodes_collection.delete_many({})
  logger.info("All series and links deleted.")

async def get_links_for_quality(file_link_key):
  """Retrieves file links for a specific quality from the episodes collection."""
  document = await episodes_collection.find_one({"file_link_key": file_link_key})
  if document:
      return document.get("files", []), document.get("channel_id"), document.get("first_msg_id"), document.get("last_msg_id")
  return [], None, None, None

async def delete_quality_files_from_episodes(file_link_key):
  """Deletes a specific quality's files from the episodes collection."""
  if file_link_key:
      await episodes_collection.delete_one({"file_link_key": file_link_key})
      logger.info(f"Deleted files for file_link_key: {file_link_key} from episodes collection.")

# The following functions are now handled by the nested structure in add_series
# and direct manipulation of the series_data dictionary in temp.USER_DATA
# before publishing. They are kept for compatibility or if direct DB manipulation is needed.

# def add_language(series_key, language):
#     series = series_collection.find_one({"key": series_key})
#     if series:
#         languages = series.get("languages", [])
#         if language not in languages:
#             languages.append(language)
#             series_collection.update_one({"key": series_key}, {"$set": {"languages": languages}})

# def add_season(series_key, season_name):
#     series = series_collection.find_one({"key": series_key})
#     if series:
#         seasons = series.get("seasons", {})
#         if season_name not in seasons:
#             seasons[season_name] = {"links": {}}
#             series_collection.update_one({"key": series_key}, {"$set": {"seasons": seasons}})

# def get_languages(series_key):
#     series = series_collection.find_one({"key": series_key})
#     if series:
#         return series.get("languages", [])
#     return []

# def get_seasons(series_key):
#     series = series_collection.find_one({"key": series_key})
#     if series:
#         return series.get("seasons", {}).keys()
#     return []

# def delete_series_language(series_key, language):
#     series = series_collection.find_one({"key": series_key})
#     if series:
#         languages = series.get("languages", [])
#         if language in languages:
#             languages.remove(language)
#             series_collection.update_one({"key": series_key}, {"$set": {"languages": languages}})
#     link_pattern = f"{series_key.lower().replace(' ', '')}-{language.lower().replace(' ', '')}-"
#     links_collection.delete_many({"series_key": {"$regex": f"^{link_pattern}"}})

# def delete_series_quality_and_links(series_key, language, season_name, quality):
#     link_key = f"{series_key.lower().replace(' ', '')}-{language.lower().replace(' ', '')}-{season_name.lower().replace(' ', '')}"
#     link_document = links_collection.find_one({"series_key": link_key})
#     if link_document:
#         updated_links = []
#         found = False
#         for link in link_document.get("links", []):
#             if not found and quality in link:
#                 found = True
#             else:
#                 updated_links.append(link)
#         links_collection.update_one(
#             {"series_key": link_key},
#             {"$set": {"links": updated_links}}
#         )
  
# def delete_series_season(series_key, language, season_name):
#     formatted_key = series_key.lower().replace(" ", "")
#     formatted_language = language.lower().replace(" ", "")
#     formatted_season_name = season_name.lower().replace(" ", "")
#     season_key = f"{formatted_key}~{formatted_language}~{formatted_season_name}"
#     series = series_collection.find_one({"key": formatted_key})
#     if series:
#         seasons = series.get("seasons", {})
#         if season_name in seasons:
#             del seasons[season_name]
#             series_collection.update_one({"key": formatted_key}, {"$set": {"seasons": seasons}})
#             links_collection.delete_many({"series_key": {"$regex": f"^{season_key}"}})
#             return True
#     return False
