"""Авто-выгрузка: когда файл БД подходит к лимиту, бот сам делает экспорт и
освобождает место. Чистит только при ПОЛНОЙ выгрузке (без обрезки по размеру),
чтобы ничего не потерять.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import FSInputFile

from app.config import Config
from app.database import Database
from app.export import build_export

logger = logging.getLogger(__name__)

TRIGGER_FRACTION = 0.9      # срабатывать на 90% от лимита
FAIL_BACKOFF_SEC = 3600.0   # при неудачной попытке — не чаще раза в час


def _human(num: int) -> str:
    size = float(num)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"


async def run_maintenance(bot: Bot, db: Database, config: Config) -> None:
    """Фоновый цикл: следит за размером БД и запускает авто-выгрузку."""
    if not config.auto_export_mb:
        logger.info("Авто-выгрузка выключена (AUTO_EXPORT_MB=0).")
        return

    limit = config.auto_export_mb * 1024 * 1024
    trigger = int(limit * TRIGGER_FRACTION)
    backoff_until = 0.0
    logger.info(
        "Авто-выгрузка включена: порог %s (лимит %s), проверка каждые %s c.",
        _human(trigger), _human(limit), config.auto_export_check_sec,
    )

    while True:
        await asyncio.sleep(config.auto_export_check_sec)
        try:
            if db.db_size_bytes() < trigger:
                continue
            if time.monotonic() < backoff_until:
                continue
            logger.info("БД %s — запускаю авто-выгрузку.", _human(db.db_size_bytes()))
            freed = await _auto_export_all(bot, db, config)
            if not freed:
                backoff_until = time.monotonic() + FAIL_BACKOFF_SEC
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка авто-выгрузки")
            backoff_until = time.monotonic() + FAIL_BACKOFF_SEC


async def _auto_export_all(bot: Bot, db: Database, config: Config) -> bool:
    freed_any = False
    for owner_id in await db.distinct_owners():
        try:
            if await _auto_export_owner(bot, db, config, owner_id):
                freed_any = True
        except Exception:
            logger.exception("Авто-выгрузка для %s не удалась", owner_id)
    return freed_any


async def _notify(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except Exception as exc:
        logger.warning("Авто-выгрузка: не удалось уведомить %s: %s", chat_id, exc)


async def _auto_export_owner(
    bot: Bot, db: Database, config: Config, owner_id: int
) -> bool:
    """Экспорт + отправка + (при полной выгрузке) очистка сообщений владельца.
    Возвращает True, если место освобождено."""
    messages = await db.all_messages(owner_id)
    if not messages:
        return False

    budget = config.export_media_mb * 1024 * 1024
    path, stats = await build_export(bot, messages, budget)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M")

    targets = [owner_id]
    if config.archive_chat_id and config.archive_chat_id != owner_id:
        targets.append(config.archive_chat_id)

    caption = (
        "🗄 <b>Авто-выгрузка</b>: база подошла к лимиту.\n"
        f"{len(messages)} сообщений, встроено медиа: {stats.embedded}."
    )
    if stats.notes:
        caption += "\n\n⚠️ " + " ".join(stats.notes)

    try:
        for chat_id in targets:
            await bot.send_document(
                chat_id,
                FSInputFile(path, filename=f"auto_perepiska_{stamp}.html"),
                caption=caption[:1024],
            )
    except Exception as exc:
        logger.warning("Авто-выгрузка: отправка не удалась: %s", exc)
        await _notify(bot, owner_id,
                      "⚠️ Авто-выгрузка не удалась (файл слишком большой). "
                      "База НЕ очищена — сделайте «Экспорт и очистку» вручную.")
        return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    # Чистим только если в файл попало ВСЁ (иначе потеряли бы данные).
    if stats.truncated_msgs:
        await _notify(bot, owner_id,
                      "⚠️ Авто-выгрузка частичная: данных больше, чем влезает в один "
                      "файл. База НЕ очищена — сделайте «Экспорт и очистку» вручную.")
        return False

    count, freed = await db.clear_messages(owner_id)
    await _notify(bot, owner_id,
                  f"🧹 Авто-очистка: выгрузка отправлена, удалено {count} сообщений, "
                  f"освобождено ~{_human(freed)}. Подключение сохранено, "
                  "бот продолжает работать.")
    logger.info("Авто-выгрузка для %s: %s сообщений, освобождено %s",
                owner_id, count, _human(freed))
    return True
