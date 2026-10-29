"""Обработчики Telegram Business: подключение, новые/изменённые/удалённые сообщения."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.types import BusinessConnection, BusinessMessagesDeleted, Message

from app.config import Config
from app.database import Database, StoredMessage
from app.utils import deliver, esc, extract_media, user_title

logger = logging.getLogger(__name__)
router = Router(name="business")

# Антиспам для уведомлений об изменении: одно и то же сообщение, которое правят
# пачкой (таймеры/счётчики/дашборды ботов, трансляции), не должно засыпать
# владельца. Копим КАЖДУЮ версию в БД как и раньше — глушим только уведомления.
_EDIT_NOTIFY_WINDOW = 5.0
_last_edit_notify: dict[tuple[int, int], float] = {}


def _edit_too_frequent(chat_id: int, message_id: int) -> bool:
    """True, если это же сообщение уведомлялось менее окна назад."""
    now = time.monotonic()
    key = (chat_id, message_id)
    last = _last_edit_notify.get(key)
    _last_edit_notify[key] = now
    if len(_last_edit_notify) > 10000:  # лёгкая очистка старых ключей
        cutoff = now - _EDIT_NOTIFY_WINDOW
        for k, t in list(_last_edit_notify.items()):
            if t < cutoff:
                del _last_edit_notify[k]
    return last is not None and (now - last) < _EDIT_NOTIFY_WINDOW


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


def _is_location(message: Message) -> bool:
    """Геопозиция/трансляция (шлёт десятки edited-апдейтов). Venue не считается:
    у него тоже есть .location, но он статичен и не спамит."""
    return (
        getattr(message, "location", None) is not None
        and getattr(message, "venue", None) is None
    )


def _special_text(message: Message) -> str | None:
    """Человекочитаемое описание для сообщений без текста (гео, контакт и т.п.)."""
    # Venue проверяем до location: у venue есть и .venue, и .location.
    venue = getattr(message, "venue", None)
    if venue is not None:
        return f"📍 {venue.title}, {venue.address}"
    loc = getattr(message, "location", None)
    if loc is not None:
        if getattr(loc, "live_period", None):
            return "📍 Трансляция геопозиции"
        return "📍 Геопозиция"
    contact = getattr(message, "contact", None)
    if contact is not None:
        name = " ".join(filter(None, [contact.first_name, contact.last_name]))
        return f"👤 Контакт: {name} {contact.phone_number}".strip()
    poll = getattr(message, "poll", None)
    if poll is not None:
        return f"📊 Опрос: {poll.question}"
    dice = getattr(message, "dice", None)
    if dice is not None:
        return f"🎲 {dice.emoji}"
    return None


def _forward_origin(message: Message) -> str | None:
    """Источник пересланного сообщения (откуда его переслали в наш чат)."""
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        otype = str(getattr(origin, "type", ""))
        if otype == "user":
            return user_title(getattr(origin, "sender_user", None))
        if otype == "hidden_user":
            return getattr(origin, "sender_user_name", None) or "скрытый пользователь"
        if otype == "chat":
            chat = getattr(origin, "sender_chat", None)
            if chat is not None:
                return getattr(chat, "title", None) or getattr(chat, "full_name", None)
        if otype == "channel":
            chat = getattr(origin, "chat", None)
            if chat is not None:
                return getattr(chat, "title", None)
    # Фолбэк для старых версий API.
    if getattr(message, "forward_from", None):
        return user_title(message.forward_from)
    if getattr(message, "forward_from_chat", None):
        return getattr(message.forward_from_chat, "title", None)
    if getattr(message, "forward_sender_name", None):
        return message.forward_sender_name
    return None


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
        text=message.text or message.caption or _special_text(message),
        media_type=media_type,
        file_id=file_id,
        date=int(message.date.timestamp()) if message.date else 0,
        forward_from=_forward_origin(message),
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


async def _ensure_owner(bot: Bot, db: Database, connection_id: str):
    """Владелец подключения; если записи нет (напр. после полной очистки) —
    восстанавливаем её из Telegram через getBusinessConnection."""
    owner = await db.get_owner(connection_id)
    if owner is not None or not connection_id:
        return owner
    try:
        conn = await bot.get_business_connection(connection_id)
    except Exception as exc:
        logger.warning("Не удалось восстановить подключение %s: %s", connection_id, exc)
        return None
    user_chat_id = getattr(conn, "user_chat_id", None) or conn.user.id
    await db.save_connection(
        conn.id, conn.user.id, user_chat_id,
        bool(conn.is_enabled), _resolve_can_reply(conn),
    )
    logger.info("Подключение %s восстановлено после очистки", connection_id)
    return await db.get_owner(connection_id)


@router.business_message()
async def on_business_message(message: Message, bot: Bot, db: Database) -> None:
    """Новое сообщение в чате владельца — сохраняем для возможного восстановления."""
    try:
        await _store(message, db)
        # Восстанавливаем запись о подключении, если её нет (после очистки).
        await _ensure_owner(bot, db, message.business_connection_id or "")
    except Exception as exc:
        logger.exception("Ошибка сохранения business_message: %s", exc)


@router.edited_business_message()
async def on_edited_business_message(
    message: Message, bot: Bot, db: Database, config: Config
) -> None:
    """Сообщение изменено — показываем владельцу старую и новую версии."""
    # Трансляция геопозиции обновляется каждые несколько секунд через
    # edited-апдейты. Тихо обновляем копию, но НЕ спамим уведомлениями.
    if _is_location(message):
        try:
            await _store(message, db)
        except Exception as exc:
            logger.exception("Ошибка обновления геопозиции: %s", exc)
        return

    old = await db.get_message(message.chat.id, message.message_id)
    owner = await _ensure_owner(bot, db, message.business_connection_id or "")
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
    new_text = message.text or message.caption or _special_text(message)

    # Нечего показывать: нет ни старой копии, ни нового текста — не шумим.
    if not old_text and not new_text:
        return
    # Текст не изменился (частый случай «тихих» правок) — тоже не уведомляем.
    if old_text is not None and old_text == new_text:
        return
    # Антиспам по частоте: одно и то же сообщение, правленное пачкой (таймеры,
    # счётчики, дашборды ботов), не засыпает владельца уведомлениями.
    if _edit_too_frequent(message.chat.id, message.message_id):
        return

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


async def _notify_bulk_delete(
    bot: Bot, db: Database, event: BusinessMessagesDeleted, targets: list[int]
) -> None:
    """Сводное уведомление о массовом удалении (вся переписка/очистка чата)."""
    # Имя собеседника берём из любой сохранённой входящей копии (первые N id).
    sender = None
    for mid in event.message_ids[:20]:
        stored = await db.get_message(event.chat.id, mid)
        if stored and not stored.outgoing and stored.from_name:
            sender = stored.from_name
            break

    chat_name = event.chat.full_name or event.chat.title or str(event.chat.id)
    text = (
        "🧨 <b>Удалена вся переписка</b>\n"
        f"💬 Чат: {esc(chat_name)}\n"
    )
    if sender:
        text += f"👤 Собеседник: {esc(sender)}\n"
    text += (
        f"Удалено сразу: <b>{len(event.message_ids)}</b> сообщений.\n"
        "📦 Сохранённые копии на месте — откройте «Экспорт», чтобы их посмотреть."
    )
    for chat_id in targets:
        try:
            await bot.send_message(chat_id, text)
        except Exception as exc:
            logger.warning("Ошибка уведомления о массовом удалении: %s", exc)


@router.deleted_business_messages()
async def on_deleted_business_messages(
    event: BusinessMessagesDeleted, bot: Bot, db: Database, config: Config
) -> None:
    """Сообщения удалены — присылаем владельцу сохранённые копии."""
    owner = await _ensure_owner(bot, db, event.business_connection_id)
    if owner is None:
        logger.info("Удаление в неизвестном подключении %s", event.business_connection_id)
        return

    targets = _targets(owner.owner_id, config)

    # Массовое удаление (очистка/удаление всей переписки у обоих) — одно
    # сводное уведомление вместо потока отдельных.
    if len(event.message_ids) >= config.bulk_delete_threshold:
        await _notify_bulk_delete(bot, db, event, targets)
        return

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
        if stored.forward_from:
            header += f"\n↪️ Переслано от: {esc(stored.forward_from)}"
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
