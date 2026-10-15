"""Обработчики Telegram Business: подключение, новые/изменённые/удалённые сообщения."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.types import BusinessConnection, BusinessMessagesDeleted, Message

from app.config import Config
from app.database import Database, StoredMessage
from app.utils import deliver, esc, extract_media, user_title

logger = logging.getLogger(__name__)
router = Router(name="business")


def _resolve_can_reply(conn: BusinessConnection) -> bool:
    """can_reply (старый Bot API) или rights.can_reply (новый) — читаем мягко."""
    rights = getattr(conn, "rights", None)
    if rights is not None and getattr(rights, "can_reply", None) is not None:
        return bool(rights.can_reply)
    return bool(getattr(conn, "can_reply", False))


def _targets(owner_id: int, config: Config) -> list[int]:
    """Куда слать уведомления: владельцу и, если задан, в архивный канал."""
    targets = [owner_id]
    if config.archive_chat_id and config.archive_chat_id != owner_id:
        targets.append(config.archive_chat_id)
    return targets


def _fmt_date(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")
    except Exception:
        return "—"


@router.business_connection()
async def on_business_connection(
    conn: BusinessConnection, bot: Bot, db: Database
) -> None:
    """Пользователь подключил/обновил/отключил бота в настройках Business."""
    can_reply = _resolve_can_reply(conn)
    user_chat_id = getattr(conn, "user_chat_id", None) or conn.user.id

    await db.save_connection(
        connection_id=conn.id,
        owner_id=conn.user.id,
        user_chat_id=user_chat_id,
        is_enabled=bool(conn.is_enabled),
        can_reply=can_reply,
    )

    if conn.is_enabled:
        text = (
            "✅ <b>Бот подключён к вашему Telegram Business.</b>\n\n"
            "Теперь я сохраняю входящие и исходящие сообщения ваших чатов и "
            "пришлю сюда копию, если кто-то <b>удалит</b> или <b>изменит</b> сообщение.\n\n"
            "💡 Чтобы охватить все диалоги, в настройках подключения выберите "
            "<b>«Все чаты»</b> (Settings → Telegram Business → Chatbots)."
        )
    else:
        text = (
            "⛔️ <b>Бот отключён от вашего Telegram Business.</b>\n"
            "Новые сообщения больше не сохраняются. Уже сохранённые копии остаются в базе."
        )

    try:
        await bot.send_message(conn.user.id, text)
    except Exception as exc:
        logger.warning("Не удалось уведомить владельца о подключении: %s", exc)


async def _store(message: Message, db: Database) -> None:
    media_type, file_id = extract_media(message)
    chat = message.chat
    stored = StoredMessage(
        connection_id=message.business_connection_id or "",
        chat_id=chat.id,
        message_id=message.message_id,
        from_id=message.from_user.id if message.from_user else None,
        from_name=user_title(message.from_user),
        chat_title=chat.full_name or chat.title or str(chat.id),
        outgoing=_is_outgoing(message),
        text=message.text or message.caption,
        media_type=media_type,
        file_id=file_id,
        date=int(message.date.timestamp()) if message.date else 0,
    )
    await db.save_message(stored)


def _is_outgoing(message: Message) -> bool:
    """Сообщение отправлено владельцем (исходящее)."""
    # В business_message от имени владельца from_user == владелец аккаунта.
    # Надёжный признак отсутствует во всех версиях API, поэтому опираемся на
    # сравнение отправителя с chat, если это личный чат.
    if message.from_user and message.chat and message.chat.type == "private":
        return message.from_user.id != message.chat.id
    return False


@router.business_message()
async def on_business_message(message: Message, db: Database) -> None:
    """Новое сообщение в чате владельца — сохраняем для возможного восстановления."""
    try:
        await _store(message, db)
    except Exception as exc:
        logger.exception("Ошибка сохранения business_message: %s", exc)


@router.edited_business_message()
async def on_edited_business_message(
    message: Message, bot: Bot, db: Database, config: Config
) -> None:
    """Сообщение изменено — показываем владельцу старую и новую версии."""
    old = await db.get_message(message.chat.id, message.message_id)
    owner = await db.get_owner(message.business_connection_id or "")
    # Обновляем сохранённую копию на новую версию.
    try:
        await _store(message, db)
    except Exception as exc:
        logger.exception("Ошибка обновления изменённого сообщения: %s", exc)

    if owner is None:
        return

    sender_name = old.from_name if old else user_title(message.from_user)
    chat_title = (old.chat_title if old else None) or message.chat.full_name or str(message.chat.id)
    old_text = old.text if old else None
    new_text = message.text or message.caption

    header = (
        "✏️ <b>Сообщение изменено</b>\n"
        f"👤 {esc(sender_name)}\n"
        f"💬 Чат: {esc(chat_title)}"
    )
    body = header
    body += "\n\n<b>Было:</b>\n" + (esc(old_text) if old_text else "<i>нет сохранённой копии</i>")
    body += "\n\n<b>Стало:</b>\n" + (esc(new_text) if new_text else "<i>(без текста)</i>")

    for chat_id in _targets(owner.owner_id, config):
        try:
            await bot.send_message(chat_id, body[:4096])
        except Exception as exc:
            logger.warning("Не удалось отправить уведомление об изменении: %s", exc)


@router.deleted_business_messages()
async def on_deleted_business_messages(
    event: BusinessMessagesDeleted, bot: Bot, db: Database, config: Config
) -> None:
    """Сообщения удалены — присылаем владельцу сохранённые копии."""
    owner = await db.get_owner(event.business_connection_id)
    if owner is None:
        logger.info("Удаление в неизвестном подключении %s", event.business_connection_id)
        return

    targets = _targets(owner.owner_id, config)

    for message_id in event.message_ids:
        stored = await db.get_message(event.chat.id, message_id)

        if stored is None:
            header = (
                "🗑 <b>Удалено сообщение</b>\n"
                f"💬 Чат: {esc(event.chat.full_name or str(event.chat.id))}\n"
                "<i>Нет сохранённой копии (сообщение пришло до запуска бота).</i>"
            )
            for chat_id in targets:
                try:
                    await bot.send_message(chat_id, header)
                except Exception as exc:
                    logger.warning("Ошибка уведомления об удалении: %s", exc)
            continue

        # Пропустить удаления, сделанные самим владельцем, если так настроено.
        if stored.outgoing and not config.notify_own_deletions:
            continue

        header = (
            "🗑 <b>Удалённое сообщение</b>\n"
            f"👤 {esc(stored.from_name)}\n"
            f"💬 Чат: {esc(stored.chat_title)}\n"
            f"🕒 {_fmt_date(stored.date)}"
        )
        for chat_id in targets:
            try:
                await deliver(
                    bot=bot,
                    chat_id=chat_id,
                    header=header,
                    text=stored.text,
                    media_type=stored.media_type,
                    file_id=stored.file_id,
                )
            except Exception as exc:
                logger.warning("Ошибка доставки удалённого сообщения: %s", exc)
