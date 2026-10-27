"""Конфигурация бота. Значения берутся из переменных окружения (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(slots=True)
class Config:
    bot_token: str
    # Необязательный явный ID владельца. Если не задан — владельцем считается
    # пользователь, который подключил бота к своему Telegram Business аккаунту.
    owner_id: int | None
    db_path: str
    # Уведомлять ли владельца о сообщениях, которые он удалил сам.
    notify_own_deletions: bool
    # Необязательный ID канала/группы-«архива», куда дублировать удалённые
    # и изменённые сообщения. Бот должен быть участником/админом этого чата.
    archive_chat_id: int | None
    # Сколько МБ медиа максимум встраивать в один HTML-экспорт (под лимит
    # отправки Telegram ≤50 МБ и память сервера).
    export_media_mb: int
    # Автоматически очищать базу после каждого обычного экспорта.
    purge_after_export: bool
    # Авто-выгрузка: когда файл БД подходит к этому размеру (МБ), бот сам
    # делает экспорт и очищает базу. 0 — выключено.
    auto_export_mb: int
    # Как часто (сек) проверять размер БД для авто-выгрузки.
    auto_export_check_sec: int


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on", "да"}


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN не задан. Создайте бота у @BotFather и укажите токен в .env "
            "(смотрите .env.example)."
        )

    owner_raw = os.getenv("OWNER_ID", "").strip()
    owner_id = int(owner_raw) if owner_raw else None

    archive_raw = os.getenv("ARCHIVE_CHAT_ID", "").strip()
    archive_chat_id = int(archive_raw) if archive_raw else None

    try:
        export_media_mb = int(os.getenv("EXPORT_MEDIA_MB", "25").strip() or "25")
    except ValueError:
        export_media_mb = 25
    # Сколько «сырых» медиа встраивать. Итоговый файл дополнительно жёстко
    # ограничен в export.py (MAX_FILE_BYTES ≈48 МБ, с учётом base64 и текста),
    # поэтому за лимит отправки Telegram (50 МБ) выйти нельзя даже на потолке.
    export_media_mb = max(0, min(export_media_mb, 35))

    def _get_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)).strip() or default)
        except ValueError:
            return default

    return Config(
        bot_token=token,
        owner_id=owner_id,
        db_path=os.getenv("DB_PATH", "messages.db").strip() or "messages.db",
        notify_own_deletions=_get_bool("NOTIFY_OWN_DELETIONS", True),
        archive_chat_id=archive_chat_id,
        export_media_mb=export_media_mb,
        purge_after_export=_get_bool("PURGE_AFTER_EXPORT", False),
        auto_export_mb=max(0, _get_int("AUTO_EXPORT_MB", 0)),
        auto_export_check_sec=max(30, _get_int("AUTO_EXPORT_CHECK_SEC", 300)),
    )
