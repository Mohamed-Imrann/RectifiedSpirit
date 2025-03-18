from pymongo import MongoClient
from info import DATABASE_URI

client = MongoClient(DATABASE_URI)
db = client['series_database']
series_collection = db['series']
links_collection = db['series_links']
posters_collection = db['posters']

def add_poster_to_db(series_key, poster_url):
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

def add_series(series_data):
    series_collection.update_one({"key": series_data['key']}, {"$set": series_data}, upsert=True)

def delete_series_and_links(series_key):
    series_collection.delete_one({"key": series_key})
    links_collection.delete_many({"series_key": {"$regex": f"^{series_key}-"}})

def delete_all_series_and_links():
    series_collection.delete_many({})
    links_collection.delete_many({})

def add_series_links(season_key, links):
    links_collection.update_one({"series_key": season_key}, {"$set": {"links": links}}, upsert=True)

def get_links(query_key):
    document = links_collection.find_one({"series_key": query_key})
    if document:
        return document.get("links", {})
    return {}

def add_language(series_key, language):
    series = series_collection.find_one({"key": series_key})
    if series:
        languages = series.get("languages", [])
        if language not in languages:
            languages.append(language)
            series_collection.update_one({"key": series_key}, {"$set": {"languages": languages}})

def add_season(series_key, season_name):
    series = series_collection.find_one({"key": series_key})
    if series:
        seasons = series.get("seasons", {})
        if season_name not in seasons:
            seasons[season_name] = {"links": {}}
            series_collection.update_one({"key": series_key}, {"$set": {"seasons": seasons}})

def get_languages(series_key):
    series = series_collection.find_one({"key": series_key})
    if series:
        return series.get("languages", [])
    return []

def get_seasons(series_key):
    series = series_collection.find_one({"key": series_key})
    if series:
        return series.get("seasons", {}).keys()
    return []

def delete_series_language(series_key, language):
    # Remove the language from the series document
    series = series_collection.find_one({"key": series_key})
    if series:
        languages = series.get("languages", [])
        if language in languages:
            languages.remove(language)
            series_collection.update_one({"key": series_key}, {"$set": {"languages": languages}})
    
    # Delete all links for the specified language
    link_pattern = f"{series_key.lower().replace(' ', '')}-{language.lower().replace(' ', '')}-"
    links_collection.delete_many({"series_key": {"$regex": f"^{link_pattern}"}})


def delete_series_quality_and_links(series_key, language, season_name, quality):
    link_key = f"{series_key.lower().replace(' ', '')}-{language.lower().replace(' ', '')}-{season_name.lower().replace(' ', '')}"
    link_document = links_collection.find_one({"series_key": link_key})

    if link_document:
        updated_links = []
        found = False

        for link in link_document.get("links", []):
            if not found and quality in link:
                found = True
            else:
                updated_links.append(link)

        links_collection.update_one(
            {"series_key": link_key},
            {"$set": {"links": updated_links}}
        )
        
    
def delete_series_season(series_key, language, season_name):
    formatted_key = series_key.lower().replace(" ", "")
    formatted_language = language.lower().replace(" ", "")
    formatted_season_name = season_name.lower().replace(" ", "")
    
    season_key = f"{formatted_key}~{formatted_language}~{formatted_season_name}"

    series = series_collection.find_one({"key": formatted_key})
    if series:
        seasons = series.get("seasons", {})
        if season_name in seasons:
            del seasons[season_name]
            series_collection.update_one({"key": formatted_key}, {"$set": {"seasons": seasons}})
            
            # find
            links_collection.delete_many({"series_key": {"$regex": f"^{season_key}"}})
            return True  # Successful deletion
    return False #not found
