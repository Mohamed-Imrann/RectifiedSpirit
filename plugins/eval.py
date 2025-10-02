import sys
import os
import traceback
from io import StringIO
from pyrogram.errors import MessageTooLong
from pyrogram import filters
from bot import Bot  # Import the Bot class from bot.py


# Helper async exec
async def aexec(code, client, message):
    exec(
        "async def __aexec(client, message): "
        + "".join(f"
 {l}" for l in code.split(""))
    )
    return await locals()["__aexec"](client, message)


# Single handler for /eval
@Bot.on_message(filters.command('eval') & filters.incoming)
async def eval_handler(client: Bot, message):
    print("[LOG] Running eval_handler → Decorator: @Bot | Argument: Bot")
    await run_eval_logic(client, message)


# Common logic for evaluation
async def run_eval_logic(client, message):
    try:
        code = message.text.split(" ", 1)[1]
    except IndexError:
        return await message.reply(
            'Command Incomplete!Usage: /eval your_python_code'
        )

    old_stderr = sys.stderr
    old_stdout = sys.stdout
    redirected_output = sys.stdout = StringIO()
    redirected_error = sys.stderr = StringIO()

    stdout, stderr, exc = None, None, None
    try:
        await aexec(code, client, message)
    except Exception:
        exc = traceback.format_exc()

    stdout = redirected_output.getvalue()
    stderr = redirected_error.getvalue()

    sys.stdout = old_stdout
    sys.stderr = old_stderr

    evaluation = exc or stderr or stdout or "Success!"
    final_output = f"**Output:**{evaluation}"

    try:
        await message.reply(final_output)
    except MessageTooLong:
        with open('eval.txt', 'w+') as outfile:
            outfile.write(final_output)
        await message.reply_document('eval.txt')
        os.remove('eval.txt')

