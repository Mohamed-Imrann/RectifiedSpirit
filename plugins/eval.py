import logging
import os
import sys
import traceback
from pyrogram import Client, filters
from pyrogram.types import Message
from info import ADMINS

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@Client.on_message(filters.command("eval") & filters.user(ADMINS))
async def eval_command(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /eval <code>")
        return

    cmd = message.text.split(" ", 1)[1]
    reply_to_id = message.id
    if message.reply_to_message:
        reply_to_id = message.reply_to_message.id

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    redirected_output = sys.stdout = sys.stderr = os.StringIO()

    try:
        exec(cmd)
        output = redirected_output.getvalue()
    except Exception:
        output = traceback.format_exc()

    sys.stdout = old_stdout
    sys.stderr = old_stderr

    if output:
        if len(output) > 4096:
            with open("eval_output.txt", "w") as f:
                f.write(output)
            await message.reply_document("eval_output.txt", caption="Output too long, sent as file.")
            os.remove("eval_output.txt")
        else:
            await message.reply_text(f"\`\`\`python\n{output}\n\`\`\`", reply_to_message_id=reply_to_id)
    else:
        await message.reply_text("No output.", reply_to_message_id=reply_to_id)
