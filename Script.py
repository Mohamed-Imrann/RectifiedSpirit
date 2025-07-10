class script(object):
    START_TXT = """Bot Started..! And its Up and Running..!"""    
    HELP_TXT = """Admin Commands

/newseries - Add new series in the bot
/newmovie - Add new movie in the bot
/editseries - Edit a exisiting series
/editmovie - Edit a exisiting movie
/cloneseries - Clone an existing series filter to a new filter
/clonemovie - Clone an existing mocie filters to a new filter
/deleteseries - Delete a series filter from the bot
/deletemovie - Delete a movie filter from the bot
/deleteallseries - Delete all the series filters from the bot
/deleteallmovies - Delete all the movie filters from the bot
/viewall - Get the list of all filters in the bot

/gadd - Add a global filter
/gdel - Delete a global filter
/gfilters - View all global filters
/gdelall - Delete all global filters

/broadcast - Broadcast a message to all the chats
/totalusers - To get total number of users
/ban_user - Ban a user from using the bot
/unban_user - Unban a user from using the bot
/banned_users - Get the list of banned users

/start - Check if the bot is alive
/help - Get this message
/logs - Get the logs of the bot
/stats - Get the stats of the bot
/restart - Restart the bot
"""

    ABOUT_TXT = """<b>𝖰𝗎𝗂𝖼𝗄𝗅𝗒 𝖩𝗈𝗂𝗇 𝖮𝗎𝗋 𝖦𝗋𝗈𝗎𝗉𝗌 & 𝖢𝗁𝖺𝗇𝗇𝖾𝗅,
𝖫𝖾𝗍 𝖳𝗁𝖾 𝖴𝗇𝗅𝗂𝗆𝗂𝗍𝖾𝖽 𝖥𝗎𝗇 𝖡𝖾𝗀𝗂𝗇.! 🚀</b>"""

    ABOUT_TEXT = """<b>
○ 𝖢𝗋𝖾𝖺𝗍𝗈𝗋 : <a href='https://t.me/cold_onez'>Ꮯᴏʟᴅ_Ꮻɴᴇᴢ</a>
○ 𝖫𝖺𝗇𝗀𝗎𝖺𝗀𝖾 : <a href='https://www.python.org/downloads/release/python-3106/'>𝖯𝗒𝗍𝗁𝗈𝗇 𝟥</a>
○ 𝖲𝖾𝗋𝗏𝖾𝗋 : <a href='https://cloud.google.com/learn/what-is-a-virtual-private-server'>VPS</a>
○ 𝖣𝖺𝗍𝖺𝖻𝖺𝗌𝖾 : <a href='https://www.mongodb.com'>𝖬𝗈𝗇𝗀𝗈𝖣𝖡 𝖥𝗋𝖾𝖾 𝖳𝗂𝖾𝗋</a></b>"""

    STATUS_TXT = """<b><u>📂 𝖳𝗈𝗍𝖺𝗅 𝖥𝗂𝗅𝖾𝗌 -</u></b> <code>{}</code>

<b><u>🗃 𝖣𝖺𝗍𝖺𝖻𝖺𝗌𝖾 1️⃣</u></b>
╭ ▸ 𝖴𝗌𝖾𝗋𝗌 : <code>{}</code>
├ ▸ 𝖢𝗁𝖺𝗍𝗌  : <code>{}</code>
╰ ▸ 𝖴𝗌𝖾𝖽 𝖲𝗍𝗈𝗋𝖺𝗀𝖾: <code>{}</code>MB

<b><u>🗃 𝖣𝖺𝗍𝖺𝖻𝖺𝗌𝖾 2️⃣</u></b>
╭ ▸ 𝖳𝗈𝗍𝖺𝗅 𝖥𝗂𝗅𝖾𝗌 : <code>{}</code>
╰ ▸ 𝖴𝗌𝖾𝖽 𝖲𝗍𝗈𝗋𝖺𝗀𝖾: <code>{}</code>MB

<b><u>🗃 𝖣𝖺𝗍𝖺𝖻𝖺𝗌𝖾 3️⃣</u></b>
╭ ▸ 𝖳𝗈𝗍𝖺𝗅 𝖥𝗂𝗅𝖾𝗌 : <code>{}</code>
╰ ▸ 𝖴𝗌𝖾𝖽 𝖲𝗍𝗈𝗋𝖺𝗀𝖾: <code>{}</code>MB

<b><u>🗃 𝖣𝖺𝗍𝖺𝖻𝖺𝗌𝖾 4️⃣</u></b>
╭ ▸ 𝖳𝗈𝗍𝖺𝗅 𝖥𝗂𝗅𝖾𝗌 : <code>{}</code>
╰ ▸ 𝖴𝗌𝖾𝖽 𝖲𝗍𝗈𝗋𝖺𝗀𝖾: <code>{}</code>MB

<b><u>🗃 𝖣𝖺𝗍𝖺𝖻𝖺𝗌𝖾 5️⃣</u></b>
╭ ▸ 𝖳𝗈𝗍𝖺𝗅 𝖥𝗂𝗅𝖾𝗌 : <code>{}</code>
╰ ▸ 𝖴𝗌𝖾𝖽 𝖲𝗍𝗈𝗋𝖺𝗀𝖾: <code>{}</code>MB

<blockquote><b><u>🚀 𝖫𝖺𝗌𝗍 𝖴𝗉𝖽𝖺𝗍𝖾𝖽 𝖮𝗇 🚀</u></b>
{}</blockquote>"""

    TOTAL_TXT = """<b><u>📂 𝖳𝗈𝗍𝖺𝗅 𝖥𝗂𝗅𝖾𝗌 -</u></b> <code>{}</code>

<blockquote><b><u>🚀 𝖫𝖺𝗌𝗍 𝖴𝗉𝖽𝖺𝗍𝖾𝖽 𝖮𝗇 🚀</u></b>
{}</blockquote>"""

    LOG_TEXT_G = """#NewGroup
Group = {}(<code>{}</code>)
Total Members = <code>{}</code>
Added By - {}
"""

    LOG_TEXT_P = """#NewUser
ID - <code>{}</code>
Name - {}
"""

    SPELL_TEXT = """𝖸𝗈"""

    DMCA_TXT = """<b>📯𝗗𝗜𝗦𝗖𝗟𝗔𝗜𝗠𝗘𝗥 :
<blockquote>𝖠𝗅𝗅 𝗍𝗁𝖾 𝖿𝗂𝗅𝖾𝗌 𝗂𝗇 𝗍𝗁𝗂𝗌 𝖻𝗈𝗍 𝖺𝗋𝖾 𝖿𝗋𝖾𝖾𝗅𝗒 𝖺𝗏𝖺𝗂𝗅𝖺𝖻𝗅𝖾 𝗈𝗇 𝗍𝗁𝖾 𝗂𝗇𝗍𝖾𝗋𝗇𝖾𝗍 𝗈𝗋 𝗉𝗈𝗌𝗍𝖾𝖽 𝖻𝗒 𝗌𝗈𝗆𝖾𝖻𝗈𝖽𝗒 𝖾𝗅𝗌𝖾.
𝖳𝗁𝗂𝗌 𝖻𝗈𝗍 𝗂𝗌 𝗂𝗇𝖽𝖾𝗑𝗂𝗇𝗀 𝖿𝗂𝗅𝖾𝗌 𝗐𝗁𝗂𝖼𝗁 𝖺𝗋𝖾 𝖺𝗅𝗋𝖾𝖺𝖽𝗒 𝗎𝗉𝗅𝗈𝖺𝖽𝖾𝖽 𝗈𝗇 𝖳𝖾𝗅𝖾𝗀𝗋𝖺𝗆 𝖿𝗈𝗋 𝖾𝖺𝗌𝖾 𝗈𝖿 𝗌𝖾𝖺𝗋𝖼𝗁𝗂𝗇𝗀,
𝖶𝖾 𝗋𝖾𝗌𝗉𝖾𝖼𝗍 𝖺𝗅𝗅 𝗍𝗁𝖾 𝖼𝗈𝗉𝗒𝗋𝗂𝗀𝗁𝗍 𝗅𝖺𝗐𝗌 𝖺𝗇𝖽 𝗐𝗈𝗋𝗄𝗌 𝗂𝗇 𝖼𝗈𝗆𝗉𝗅𝗂𝖺𝗇𝖼𝖾 𝗐𝗂𝗍𝗁 𝖣𝖬𝖢𝖠 𝖺𝗇𝖽 𝖤𝖴𝖢𝖣.</blockquote>

𝖨𝖿 𝖺𝗇𝗒𝗍𝗁𝗂𝗇𝗀 𝗂𝗌 𝖺𝗀𝖺𝗂𝗇𝗌𝗍 𝗅𝖺𝗐 𝗉𝗅𝖾𝖺𝗌𝖾 𝖼𝗈𝗇𝗍𝖺𝖼𝗍 𝗎𝗌 𝗌𝗈 𝗍𝗁𝖺𝗍 𝗂𝗍 𝖼𝖺𝗇 𝖻𝖾 𝗋𝖾𝗆𝗈𝗏𝖾𝖽 𝖺𝗌𝖺𝗉.</b>"""

    DELETE_TXT = """‼️ 𝗜𝗠𝗣𝗢𝗥𝗧𝗔𝗡𝗧 ‼️

<b><blockquote>⚠️ Files Will be Delete Within 5 Minutes.</blockquote></b>

<b>If You Want To Download These Files, Kindly Forward These Files To Any Chat or Saved Message and Start Downloading...</b>

<b><blockquote>⚠️ ഫയലുകൾ 5 മിനിറ്റിനുള്ളിൽ ഡിലീറ്റ് ആകുന്നതാണ്.</blockquote></b>

<b>ഡൌൺലോഡ് ചെയ്യുന്നതിന് മുൻപ്, ഫയലുകൾ saved message ലേക്കോ അല്ലെങ്കിൽ മറ്റൊരു ചാറ്റിലേക്കോ ഫോർവേഡ് ചെയ്ത ശേഷം മാത്രം ഡൌൺലോഡ് ചെയ്യുക...</b>"""

#𝗝𝘂𝘀𝘁 𝗦𝗲𝗻𝗱 𝗖𝗼𝗿𝗿𝗲𝗰𝘁 𝗠𝗼𝘃𝗶𝗲/𝗦𝗲𝗿𝗶𝗲𝘀 𝗡𝗮𝗺𝗲 𝗪𝗶𝘁𝗵𝗼𝘂𝘁 𝗦𝗽𝗲𝗹𝗹𝗶𝗻𝗴 𝗠𝗶𝘀𝘁𝗮𝗸𝗲𝘀.
#𝗜 𝗪𝗶𝗹𝗹 𝗦𝗲𝗻𝗱 𝗙𝗶𝗹𝗲𝘀 𝗧𝗼 𝗬𝗼𝘂.
#[𝖣𝗈𝗇'𝗍 𝖴𝗌𝖾 𝖠𝗇𝗒 𝖲𝗒𝗆𝖻𝗈𝗅 : ; & 𝖾𝗍𝖼]
