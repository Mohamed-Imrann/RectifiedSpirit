from pyrogram import Client

API_ID = 31445120
API_HASH = "5e6c06ca38688ec6ec6e65dbff6d9b07"

app = Client("user", api_id=API_ID, api_hash=API_HASH)
app.start()
print("✅ Logged in, session created")
app.stop()
