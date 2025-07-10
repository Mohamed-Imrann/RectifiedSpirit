import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from pyrogram import Client, filters
from pyrogram.types import Message
from info import ADMINS
import io
import sys
import traceback

@Client.on_message(filters.command("eval") & filters.user(ADMINS))
async def eval_command(client, message: Message):
    if len(message.command) &lt; 2:
        return await message.reply_text("Usage: /eval [code]")
    
    cmd = message.text.split(" ", 1)[1]
    
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    redirected_output = io.StringIO()
    redirected_error = io.StringIO()
    sys.stdout = redirected_output
    sys.stderr = redirected_error
    
    try:
        # Create a dictionary for local variables, including client and message
        exec_globals = globals().copy()
        exec_locals = {'client': client, 'message': message}
        
        exec(cmd, exec_globals, exec_locals)
        
        output = redirected_output.getvalue()
        error = redirected_error.getvalue()
        
        if output:
            await message.reply_text(f"**Output:**\n```\n{output}```")
        if error:
            await message.reply_text(f"**Error:**\n```\n{error}```")
        if not output and not error:
            await message.reply_text("Execution completed with no output.")
            
    except Exception as e:
        await message.reply_text(f"**Exception:**\n```\n{traceback.format_exc()}```")
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
