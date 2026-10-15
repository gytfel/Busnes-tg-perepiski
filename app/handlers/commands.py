"""Команды, доступные владельцу в личном чате с ботом."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.database import Database

router = Router(name="commands")

START_TEXT = (
    "👋 <b>Привет!</b> Это бот-архиватор переписки для вашего Telegram Business.\n\n"
    "Что я умею, когда подключён к вашему аккаунту:\n"
    "• сохраняю входящие и исходящие сообщения ваших чатов;\n"
    "• присылаю сюда копию, если сообщение <b>удалили</b> (🗑);\n"
    "• показываю, что было <b>изменено</b> (✏️), — старую и новую версии.\n\n"
    "<b>Как подключить (нужен Telegram Premium):</b>\n"
    "1. Telegram → Settings → <b>Telegram Business</b> → <b>Chatbots</b>.\n"
    "2. Впишите <b>username этого бота</b>.\n"
    "3. Выберите <b>«Все чаты»</b>, чтобы охватить всю переписку сразу.\n\n"
    "Уведомления приходят <b>только сюда, в этот личный чат</b> — больше их никто не видит.\n\n"
    "Команды: /status — статус подключения, /help — справка."
)

HELP_TEXT = (
    "ℹ️ <b>Справка</b>\n\n"
    "/start — как подключить бота\n"
    "/status — показать активные подключения и число сохранённых сообщений\n\n"
    "⚠️ Бот работает только с аккаунтом, который сам его подключил, и обрабатывает "
    "вашу собственную переписку. Соблюдайте законы вашей страны о записи переписки."
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(START_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("status"))
async def cmd_status(message: Message, db: Database) -> None:
    if message.from_user is None:
        return
    connections = await db.list_connections(message.from_user.id)
    total = await db.count_messages(message.from_user.id)

    if not connections:
        await message.answer(
            "❌ Активных подключений нет.\n"
            "Подключите бота в Settings → Telegram Business → Chatbots. См. /start."
        )
        return

    lines = ["📊 <b>Статус</b>", ""]
    for conn in connections:
        state = "🟢 активно" if conn["is_enabled"] else "🔴 отключено"
        reply = "да" if conn["can_reply"] else "нет"
        lines.append(f"• Подключение <code>{conn['connection_id']}</code>: {state}")
        lines.append(f"  право отвечать от вашего имени: {reply}")
    lines.append("")
    lines.append(f"💾 Сохранено сообщений: <b>{total}</b>")
    await message.answer("\n".join(lines))
