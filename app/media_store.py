"""Локальные копии медиа.

Одноразовые и самоуничтожающиеся вложения Telegram нельзя открыть повторно,
поэтому бот скачивает файл сразу, как только тот пришёл, и хранит его на диске.
Так владелец может смотреть его сколько угодно раз, даже если собеседник
удалил сообщение или файл недоступен по file_id.

Переменные окружения:
  MEDIA_DIR          папка для копий (по умолчанию media)
  FORWARD_MEDIA_NOW  присылать входящее медиа владельцу сразу (true/false, по умолчанию true)
"""
from __future__ import annotations

import hashlib
import logging
import os

from aiogram import Bot
from aiogram.types import FSInputFile

from app.utils import NO_CAPTION, SENDERS

logger = logging.getLogger(__name__)


def media_dir() -> str:
    return os.getenv("MEDIA_DIR", "").strip() or "media"


def forward_media_now() -> bool:
    raw = os.getenv("FORWARD_MEDIA_NOW", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


async def save_media_copy(
    bot: Bot, chat_id: int, message_id: int, media_type: str, file_id: str
) -> str | None:
    """Скачивает медиа на диск. Возвращает путь к файлу или None при ошибке."""
    try:
        os.makedirs(media_dir(), exist_ok=True)
        key = hashlib.sha1(file_id.encode()).hexdigest()[:16]
        tg_file = await bot.get_file(file_id)
        ext = os.path.splitext(tg_file.file_path or "")[1]
        path = os.path.join(media_dir(), f"{chat_id}_{message_id}_{key}{ext}")
        if not os.path.exists(path):
            await bot.download_file(tg_file.file_path, destination=path)
        return path
    except Exception as exc:  # файл может быть больше 20 МБ или уже недоступен
        logger.warning("Не удалось сохранить копию медиа (%s): %s", media_type, exc)
        return None


def remove_media_files(paths: list[str]) -> int:
    """Удаляет файлы копий (при очистке базы). Возвращает число удалённых."""
    removed = 0
    for path in paths:
        if not path:
            continue
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    return removed


async def send_saved_media(
    bot: Bot, chat_id: int, media_type: str, path: str, caption: str | None
) -> bool:
    """Отправляет сохранённый файл с диска. Возвращает True при успехе."""
    method_name = SENDERS.get(media_type)
    if method_name is None or not os.path.exists(path):
        return False
    sender = getattr(bot, method_name)
    if media_type in NO_CAPTION:
        await sender(chat_id, FSInputFile(path))
    else:
        await sender(chat_id, FSInputFile(path), caption=(caption or None) and caption[:1024])
    return True
