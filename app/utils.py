"""Вспомогательные функции: извлечение медиа и доставка уведомлений владельцу."""
from __future__ import annotations

import html
import logging
from collections.abc import Iterable
from datetime import datetime, timezone

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


def _fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "—"


def build_export_html(messages: Iterable) -> str:
    """Собирает HTML-файл с сохранённой перепиской, сгруппированной по чатам.

    Ожидает объекты StoredMessage (или совместимые) с полями chat_title,
    from_name, outgoing, date, text, media_type.
    """
    rows = list(messages)
    generated = datetime.now(tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

    parts: list[str] = [
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Экспорт переписки</title>",
        "<style>",
        "body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;",
        "background:#0e1621;color:#e6edf3;padding:16px;}",
        "h1{font-size:20px;} h2{font-size:16px;margin:24px 0 8px;color:#6ab7ff;",
        "border-bottom:1px solid #22303c;padding-bottom:4px;}",
        ".msg{padding:8px 12px;margin:6px 0;border-radius:10px;background:#17212b;}",
        ".msg.out{background:#2b5278;}",
        ".meta{font-size:12px;color:#8a98a5;margin-bottom:4px;}",
        ".media{font-size:12px;color:#f0b232;}",
        ".empty{color:#8a98a5;font-style:italic;}",
        "</style></head><body>",
        f"<h1>Экспорт переписки</h1><p class='meta'>Сформировано: {generated}. "
        f"Сообщений: {len(rows)}.</p>",
    ]

    current_chat: str | None = None
    if not rows:
        parts.append("<p class='empty'>Нет сохранённых сообщений.</p>")

    for m in rows:
        chat_title = m.chat_title or "—"
        if chat_title != current_chat:
            current_chat = chat_title
            parts.append(f"<h2>💬 {esc(chat_title)}</h2>")
        cls = "msg out" if m.outgoing else "msg"
        who = "Вы" if m.outgoing else (m.from_name or "собеседник")
        parts.append(f"<div class='{cls}'>")
        parts.append(f"<div class='meta'>{esc(who)} · {_fmt_ts(m.date)}</div>")
        if m.text:
            parts.append(esc(m.text).replace("\n", "<br>"))
        if m.media_type:
            parts.append(f"<div class='media'>[вложение: {esc(m.media_type)}]</div>")
        if not m.text and not m.media_type:
            parts.append("<span class='empty'>(пустое сообщение)</span>")
        parts.append("</div>")

    parts.append("</body></html>")
    return "".join(parts)
