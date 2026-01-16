# utils.py
from pyrogram.types import Message


def get_file_id(message: Message):
    """
    Returns the media object containing file_id + message_type.
    Supports: document, video, audio, photo
    """
    if message.document:
        message.document.message_type = "document"
        return message.document
    if message.video:
        message.video.message_type = "video"
        return message.video
    if message.audio:
        message.audio.message_type = "audio"
        return message.audio
    if message.photo:
        message.photo.message_type = "photo"
        return message.photo
    return None
