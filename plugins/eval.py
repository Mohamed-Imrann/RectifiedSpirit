import sys
import os
import traceback
from io import StringIO
from pyrogram.errors import MessageTooLong
from pyrogram import Client, filters
from bot import Bot  # adjust this import to where Bot is defined


# Helper async exec
async def aexec(code, client, message):
    exec(
        "async def __aexec(client, message): "
        + "".join(f"\n {l}" for l in code.split("\n"))
    )
    return await locals()["__aexec"](client, message)


# 1) @Bot with client: Bot
@Bot.on_message(filters.command('eval') & filters.incoming)
async def eval_bot_bot(client: Bot, message):
    print("[LOG] Running eval_bot_bot → Decorator: @Bot | Argument: Bot")
    await run_eval_logic(client, message)


# 2) @Bot with client: Client
@Bot.on_message(filters.command('eval') & filters.incoming)
async def eval_bot_client(client: Client, message):
    print("[LOG] Running eval_bot_client → Decorator: @Bot | Argument: Client")
    await run_eval_logic(client, message)


# 3) @Client with client: Bot
@Client.on_message(filters.command('eval') & filters.incoming)
async def eval_client_bot(client: Bot, message):
    print("[LOG] Running eval_client_bot → Decorator: @Client | Argument: Bot")
    await run_eval_logic(client, message)


# 4) @Client with client: Client
@Client.on_message(filters.command('eval') & filters.incoming)
async def eval_client_client(client: Client, message):
    print("[LOG] Running eval_client_client → Decorator: @Client | Argument: Client")
    await run_eval_logic(client, message)


# Common logic for evaluation
async def run_eval_logic(client, message):
    try:
        code = message.text.split(" ", 1)[1]
    except:
        return await message.reply(
            'Command Incomplete!\nUsage: /eval your_python_code'
        )

    old_stderr = sys.stderr
    old_stdout = sys.stdout
    redirected_output = sys.stdout = StringIO()
    redirected_error = sys.stderr = StringIO()

    stdout, stderr, exc = None, None, None
    try:
        await aexec(code, client, message)
    except:
        exc = traceback.format_exc()

    stdout = redirected_output.getvalue()
    stderr = redirected_error.getvalue()

    sys.stdout = old_stdout
    sys.stderr = old_stderr

    evaluation = exc or stderr or stdout or "Success!"
    final_output = f"**Output:**\n\n{evaluation}"

    try:
        await message.reply(final_output)
    except MessageTooLong:
        with open('eval.txt', 'w+') as outfile:
            outfile.write(final_output)
        await message.reply_document('eval.txt')
        os.remove('eval.txt')
