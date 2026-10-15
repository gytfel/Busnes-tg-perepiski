"""Вспомогательные функции: извлечение медиа и доставка уведомлений владельцу."""
from __future__ import annotations

import html
import logging

from aiogram import Bot
from aiogram.types import Message, User

logger = logging.getLogger(__name__)

# Тип медиа -> имя метода Bot.send_* для пересылки по file_id.
SENDERS: dict[str, str] = {
    "photo": "send_photo",
    "video": "send_video",
    "animation": "send_animation",
    "voice": "send_voice",
    "audio": "send_audio",
    "document": "send_document",
    "video_note": "send_video_note",
    "sticker": "send_sticker",
}

# Типы, которые нельзя сопроводить подписью (caption).
NO_CAPTION = {"sticker", "video_note"}

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096


def extract_media(message: Message) -> tuple[str | None, str | None]:
    """Возвращает (media_type, file_id) для самого «тяжёлого» вложения."""
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.video:
        return "video", message.video.file_id
    if message.animation:
        return "animation", message.animation.file_id
    if message.voice:
        return "voice", message.voice.file_id
    if message.video_note:
        return "video_note", message.video_note.file_id
    if message.audio:
        return "audio", message.audio.file_id
    if message.document:
        return "document", message.document.file_id
    if message.sticker:
        return "sticker", message.sticker.file_id
    return None, None


def user_title(user: User | None) -> str:
    if user is None:
        return "неизвестно"
    name = user.full_name or "без имени"
    if user.username:
        return f"{name} (@{user.username})"
    return f"{name} (id {user.id})"


def esc(text: str | None) -> str:
    return html.escape(text) if text else ""


async def deliver(
    bot: Bot,
    chat_id: int,
    header: str,
    text: str | None,
    media_type: str | None,
    file_id: str | None,
) -> None:
    """Отправляет владельцу уведомление с сохранённым содержимым.

    header уже должен быть в HTML-разметке; text — «сырой» текст сообщения,
    он экранируется здесь.
    """
    body = header
    if text:
        body += "\n\n" + esc(text)

    if media_type and file_id:
        method_name = SENDERS.get(media_type)
        if method_name is not None:
            sender = getattr(bot, method_name)
            try:
                if media_type in NO_CAPTION:
                    await sender(chat_id, file_id)
                    await bot.send_message(chat_id, body[:TEXT_LIMIT])
                else:
                    await sender(chat_id, file_id, caption=body[:CAPTION_LIMIT])
                return
            except Exception as exc:  # file_id может быть непересылаемым
                logger.warning("Не удалось переслать медиа (%s): %s", media_type, exc)
                note = "\n\n⚠️ Медиа не удалось переслать (возможно, самоуничтожающееся)."
                await bot.send_message(chat_id, (body + note)[:TEXT_LIMIT])
                return

    await bot.send_message(chat_id, body[:TEXT_LIMIT] or "(пустое сообщение)")
