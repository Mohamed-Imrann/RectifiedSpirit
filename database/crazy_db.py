# database/crazy_db.py (Conceptual additions/modifications)

from pymongo import MongoClient

# Assuming your MongoDB setup
client = MongoClient('mongodb://localhost:27017/') # Replace with your MongoDB URI
db = client['your_database_name'] # Replace with your database name

series_collection = db['series']
links_collection = db['links']
temp_series_data_collection = db['temp_series_data'] # New collection for temporary data

def add_series(series_data):
    # Adds/updates series in the permanent collection
    series_collection.update_one(
        {'key': series_data['key']},
        {'$set': series_data},
        upsert=True
    )

def add_language(series_key, language):
    series_collection.update_one(
        {'key': series_key},
        {'$addToSet': {'languages': language}}
    )

def add_season(series_key, season_name):
    series_collection.update_one(
        {'key': series_key},
        {'$addToSet': {'seasons': season_name}}
    )

def add_series_links(link_key, links_dict):
    # Adds/updates links in the permanent collection
    links_collection.update_one(
        {'link_key': link_key},
        {'$set': {'links': links_dict}},
        upsert=True
    )

def get_series_name(series_key):
    return series_collection.find_one({'key': series_key})

def get_series():
    return list(series_collection.find({}))

def get_languages(series_key):
    series = series_collection.find_one({'key': series_key})
    return series.get('languages', []) if series else []

def get_seasons(series_key):
    series = series_collection.find_one({'key': series_key})
    return series.get('seasons', []) if series else []

def get_links(link_key):
    link_doc = links_collection.find_one({'link_key': link_key})
    return link_doc.get('links', {}) if link_doc else {}

def add_poster_to_db(series_key, poster_url):
    result = series_collection.update_one(
        {'key': series_key},
        {'$set': {'poster': poster_url}}
    )
    return result.modified_count > 0 or result.upserted_id is not None

def get_poster_manuel(series_key):
    series = series_collection.find_one({'key': series_key})
    return series.get('poster') if series else None

# --- New Temporary Data Functions ---

def add_temp_series_data(user_id, data):
    """Stores temporary series data for a user."""
    temp_series_data_collection.update_one(
        {'user_id': user_id},
        {'$set': {'data': data}},
        upsert=True
    )

def get_temp_series_data(user_id):
    """Retrieves temporary series data for a user."""
    doc = temp_series_data_collection.find_one({'user_id': user_id})
    return doc.get('data', {}) if doc else {}

def clear_temp_series_data(user_id):
    """Clears temporary series data for a user."""
    temp_series_data_collection.delete_one({'user_id': user_id})

def add_temp_quality_links(user_id, series_key, language, season, quality, links):
    """Adds temporary quality links to a user's temporary data."""
    temp_series_data_collection.update_one(
        {'user_id': user_id},
        {
            '$set': {
                f'data.qualities.{series_key}.{language}.{season}.{quality}': links
            }
        },
        upsert=True
    )

def get_temp_quality_links(user_id, series_key, language, season, quality):
    """Retrieves temporary quality links for a specific quality."""
    doc = temp_series_data_collection.find_one({'user_id': user_id})
    return doc.get('data', {}).get('qualities', {}).get(series_key, {}).get(language, {}).get(season, {}).get(quality, {})

def get_all_temp_qualities_for_series(user_id, series_key, language, season):
    """Retrieves all temporary qualities for a specific series, language, season."""
    doc = temp_series_data_collection.find_one({'user_id': user_id})
    return doc.get('data', {}).get('qualities', {}).get(series_key, {}).get(language, {}).get(season, {})

def publish_temp_data(user_id):
    """Moves all temporary data for a user to permanent storage."""
    temp_data = get_temp_series_data(user_id)
    if not temp_data:
        return False

    # Add/update series info
    series_info = temp_data.get('series_info')
    if series_info:
        add_series(series_info)
        # Add languages and seasons if they were part of the temp data
        for lang in series_info.get('languages', []):
            add_language(series_info['key'], lang)
        for season in series_info.get('seasons', []):
            add_season(series_info['key'], season)

    # Add/update quality links
    qualities_data = temp_data.get('qualities', {})
    for series_key, langs in qualities_data.items():
        for language, seasons in langs.items():
            for season, qualities in seasons.items():
                link_key_base = f"{series_key.lower().replace(' ', '')}-{language.lower().replace(' ', '')}-{season.lower().replace(' ', '')}"
                # Get existing links for this link_key_base
                existing_links = get_links(link_key_base)
                # Merge new qualities
                for quality, links in qualities.items():
                    existing_links[quality] = links # Overwrite or add new quality
                add_series_links(link_key_base, existing_links)

    clear_temp_series_data(user_id)
    return True

# Utility functions for deletion (from your original crazy_db.py)
def delete_series_and_links(series_key):
    series_collection.delete_one({'key': series_key})
    links_collection.delete_many({'link_key': {'$regex': f'^{series_key}-'}})

def delete_series_quality_and_links(series_key, language, season_name, quality):
    link_key = f"{series_key.lower().replace(' ', '')}-{language.lower().replace(' ', '')}-{season_name.lower().replace(' ', '')}"
    links_collection.update_one(
        {'link_key': link_key},
        {'$unset': {f'links.{quality}': ""}}
    )

def delete_series_language(series_key, language):
    series_collection.update_one(
        {'key': series_key},
        {'$pull': {'languages': language}}
    )
    links_collection.delete_many({'link_key': {'$regex': f'^{series_key}-{language.lower().replace(" ", "")}-'}})

def delete_series_season(series_key, language, season_name):
    series_collection.update_one(
        {'key': series_key},
        {'$pull': {'seasons': season_name}}
    )
    links_collection.delete_many({'link_key': {'$regex': f'^{series_key}-{language.lower().replace(" ", "")}-{season_name.lower().replace(" ", "")}'}})

def tadd_series(series_data):
    # This function is used by the admin panel to add series info
    # It should now add to the permanent collection directly or manage temp data
    # For simplicity, let's assume it adds to permanent for now,
    # and the new /addseries command will use temp data.
    add_series(series_data)

def tadd_poster_to_db(series_key, poster_url):
    add_poster_to_db(series_key, poster_url)

def tadd_language(series_key, language):
    add_language(series_key, language)

def tdelete_group(series_key):
    delete_series_and_links(series_key)

