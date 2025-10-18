import speedtest
from time import time
from bot import Bot
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

# --- Helper Functions (Kept from the original logic) ---

def convert_from_bytes(size):
    """Converts bytes/bits per second to human-readable units (Kbps, Mbps, Gbps, Tbps)."""
    power = 1024  # Using 1024 for standard unit conversion (though speedtest usually uses powers of 1000 for bandwidth)
    n = 0
    units = {0: "bps", 1: "Kbps", 2: "Mbps", 3: "Gbps", 4: "Tbps"}
    
    # Speedtest results are usually in bits per second (bps). 
    # To convert to Bytes per second (B/s), we divide by 8.
    # The original code seems to treat the output of s.download() directly as if it were in bits/s 
    # and then uses 1024 as the base for scaling, which is common but sometimes inconsistent 
    # with strict network standards (where 1000 is often used for link capacity).
    # We will maintain the original structure's scaling logic based on 2**10 (1024).
    
    while size >= power and n < len(units) - 1:
        size /= power
        n += 1
        
    # Adjusting the initial unit name for clarity if n=0, though usually speedtest returns large enough numbers
    if n == 0:
        return f"{round(size, 2)} bps"
        
    return f"{round(size, 2)} {units[n]}"

# --- Pyrogram Command Definition ---

# Replace 'app' with your initialized Pyrogram Client instance.
# Assuming the command trigger is '/speedtest' followed by an optional argument.
@Bot.on_message(filters.command("speedtest"))
async def speedtest_command_handler(client: Client, message: Message):
    """Handles the /speedtest command with options: text, image, file."""
    
    input_arg = (message.text or message.caption or "").split(maxsplit=1)
    option = "image"  # Default option
    if len(input_arg) > 1:
        option = input_arg[1].strip().lower()

    as_text = (option == "text")
    as_document = (option == "file")
    
    # Send initial processing message
    processing_msg = await message.reply_text("`Calculating my internet speed. Please wait!`")
    
    start_time = time()
    
    try:
        s = speedtest.Speedtest()
        s.get_best_server()
        s.download()
        s.upload()
        end_time = time()
        
        ms = round(end_time - start_time, 2)
        results = s.results.dict()
        
        download_speed_bits = results.get("download")
        upload_speed_bits = results.get("upload")
        ping_time = results.get("ping")
        client_infos = results.get("client", {})
        i_s_p = client_infos.get("isp", "N/A")
        i_s_p_rating = client_infos.get("isprating", "N/A")

        # Convert speeds from bits/s to human-readable format
        download_hr = convert_from_bytes(download_speed_bits)
        upload_hr = convert_from_bytes(upload_speed_bits)
        
        # MB/s calculation (dividing bits/s by 8 to get Bytes/s, then by 1,048,576 for MB)
        download_mbps = round(download_speed_bits / 8e6, 2)
        upload_mbps = round(upload_speed_bits / 8e6, 2)

        
        if as_text:
            response_text = (
                f"`SpeedTest completed in {ms} seconds`"
                f"`Download: {download_hr} (or) {download_mbps} MB/s`"
                f"`Upload: {upload_hr} (or) {upload_mbps} MB/s`"
                f"`Ping: {ping_time:.2f} ms`"
                f"`Internet Service Provider: {i_s_p}`"
                f"`ISP Rating: {i_s_p_rating}`"
            )
            await processing_msg.edit(response_text, parse_mode=ParseMode.MARKDOWN)
            
        else:
            # Try to get the shareable image link/data
            try:
                # speedtest.results.share() returns the URL for the generated image
                speedtest_url = s.results.share() 
                
                caption = (
                    f"**SpeedTest** completed in {ms} seconds"
                    f"Download: `{download_hr}` / `{download_mbps} MB/s`"
                    f"Upload: `{upload_hr}` / `{upload_mbps} MB/s`"
                    f"Ping: `{ping_time:.2f} ms`"
                )
                
                # In Pyrogram, sending the image directly from the URL is often easiest
                await client.send_photo(
                    chat_id=message.chat.id,
                    photo=speedtest_url,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=message.id,
                    # force_document is equivalent to reply's force_document/as_document
                    # Note: Pyrogram handles file/document upload via specific parameters 
                    # like `send_document` or `send_photo(..., file_name=...)` if you save the image first.
                    # Since speedtest.share() provides a URL, we send a photo. If `as_document` is True, 
                    # Pyrogram's send_photo with the URL will usually result in a media file, 
                    # but if you strictly need it as a document/file, you would need to download the image first.
                )
                
                # Delete the processing message only after the final file is successfully sent
                await processing_msg.delete()

            except Exception as e:
                # Fallback if sending the image/URL fails (e.g., network issues accessing the image host)
                error_text = (
                    f"**SpeedTest** completed in {ms} seconds"
                    f"Download: `{download_hr}` (or) `{download_mbps} MB/s`"             
                    f"Upload: `{upload_hr}` (or) `{upload_mbps} MB/s`"
                    f"Ping: `{ping_time:.2f} ms`"
                    f"__Error generating/sending media:__ `{e}`"
                )
                await processing_msg.edit(error_text, parse_mode=ParseMode.MARKDOWN)

    except Exception as exc:
        # General error during speed testing
        await processing_msg.edit(
            f"**SpeedTest Error!**"
            f"An error occurred during execution: `{exc}`"
      )
      
