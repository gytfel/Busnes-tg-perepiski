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
    # Со скольких удалённых за раз сообщений считать это удалением всей
    # переписки (одно сводное уведомление вместо потока отдельных).
    bulk_delete_threshold: int


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
        bulk_delete_threshold=max(2, _get_int("BULK_DELETE_THRESHOLD", 5)),
    )


# Поля, которые можно менять «на лету» (перечиткой .env без перезапуска).
# bot_token и db_path сюда НЕ входят — для них нужен рестарт.
_RELOADABLE = (
    "owner_id",
    "notify_own_deletions",
    "archive_chat_id",
    "export_media_mb",
    "purge_after_export",
    "auto_export_mb",
    "auto_export_check_sec",
    "bulk_delete_threshold",
)


def reload_into(config: Config, dotenv_path: str | None = None) -> list[str]:
    """Перечитывает .env и обновляет «горячие» поля config на месте.

    Возвращает список изменившихся полей в виде ["name=value", ...].
    Токен и путь к БД не трогаются. Если .env временно некорректен
    (напр. нет токена) — пробрасывает исключение, вызывающий его гасит.
    dotenv_path — явный путь к .env (по умолчанию авто-поиск, как при старте).
    """
    load_dotenv(dotenv_path=dotenv_path, override=True)
    fresh = load_config()
    changed: list[str] = []
    for name in _RELOADABLE:
        new_value = getattr(fresh, name)
        if getattr(config, name) != new_value:
            setattr(config, name, new_value)
            changed.append(f"{name}={new_value}")
    return changed
