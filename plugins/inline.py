import logging
from pyrogram import Client, filters, types
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
from database.crazy_db import get_series, get_series_name, get_poster_manuel
from info import CACHE_TIME, AUTH_USERS, NO_POSTER_FOUND_IMG

logger = logging.getLogger(__name__)
cache_time = 0 if AUTH_USERS else CACHE_TIME
MAX_RESULTS = 50  # Limit the number of results

def get_movie_poster(series_key):
  poster_url = get_poster_manuel(series_key)
  if not poster_url:
      series = get_series_name(series_key)
      if series:
          poster_url = series.get('poster_url') # Get from the main series data
  return poster_url or NO_POSTER_FOUND_IMG[0]

@Client.on_inline_query()
async def inline_query_handler(client, inline_query):
  query_text = inline_query.query.lower().strip()
  results = []

  if not query_text:
      await inline_query.answer(results, cache_time=cache_time, is_personal=True)
      return

  series_infos = get_series()
  matching_series = [s for s in series_infos if query_text in s['title'].lower()]

  # If no exact matches, try to find partial matches or return all if query is very short
  if not matching_series and len(query_text) > 2:
      matching_series = [s for s in series_infos if query_text.split()[0] in s['title'].lower()]
  
  # If still no matches, or query is too short, don't return everything
  if not matching_series and len(query_text) <= 2:
      await inline_query.answer(results, cache_time=cache_time, is_personal=True)
      return

  # Sort and limit results
  matching_series = sorted(matching_series, key=lambda x: x['title'].lower())
  matching_series = matching_series[:MAX_RESULTS]

  for series in matching_series:
      series_key = series['key']
      title = series['title']
      released_on = series.get('released_on', 'N/A')
      genre = series.get('genre', 'N/A')
      rating = series.get('rating', 'N/A')
      media_type = series.get('media_type', 'N/A').upper()

      poster_url = get_movie_poster(series_key)

      result = InlineQueryResultArticle(
          id=series_key,
          title=title,
          description=f"Released: {released_on} | Genre: {genre} | Rating: {rating}/10 | Type: {media_type}",
          input_message_content=InputTextMessageContent(
              f"**{title}**\nReleased: {released_on}\nGenre: {genre}\nRating: {rating}/10\nMedia Type: {media_type}"
          ),
          thumb_url=poster_url,
          reply_markup=InlineKeyboardMarkup([
              [InlineKeyboardButton("View Details", callback_data=f"user_series:{series_key}")]
          ])
      )
      results.append(result)

  await inline_query.answer(results, cache_time=cache_time, is_personal=True)
