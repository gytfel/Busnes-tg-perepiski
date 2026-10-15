"""Команды, доступные владельцу в личном чате с ботом."""
from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, Message

from app.database import Database
from app.utils import build_export_html, esc

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
    "Команды: /status — статус, /search — поиск, /export — выгрузка, /help — справка."
)

HELP_TEXT = (
    "ℹ️ <b>Справка</b>\n\n"
    "/start — как подключить бота\n"
    "/status — активные подключения и число сохранённых сообщений\n"
    "/search &lt;текст&gt; — поиск по сохранённой переписке\n"
    "/export — выгрузить всю сохранённую переписку в HTML-файл\n\n"
    "⚠️ Бот работает только с аккаунтом, который сам его подключил, и обрабатывает "
    "вашу собственную переписку. Соблюдайте законы вашей страны о записи переписки."
)

SEARCH_LIMIT = 20


def _fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "—"


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


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject, db: Database) -> None:
    if message.from_user is None:
        return
    query = (command.args or "").strip()
    if not query:
        await message.answer("Использование: <code>/search текст для поиска</code>")
        return

    results = await db.search_messages(message.from_user.id, query, limit=SEARCH_LIMIT)
    if not results:
        await message.answer(f"🔍 По запросу «{esc(query)}» ничего не найдено.")
        return

    lines = [f"🔍 Найдено (до {SEARCH_LIMIT}) по «{esc(query)}»:", ""]
    for m in results:
        who = "Вы" if m.outgoing else (m.from_name or "собеседник")
        snippet = (m.text or "")[:200]
        lines.append(
            f"💬 <b>{esc(m.chat_title or '—')}</b> · {esc(who)} · {_fmt_ts(m.date)}"
        )
        lines.append(esc(snippet) or "<i>(без текста)</i>")
        lines.append("")
    await message.answer("\n".join(lines)[:4096])


@router.message(Command("export"))
async def cmd_export(message: Message, db: Database) -> None:
    if message.from_user is None:
        return
    messages = await db.all_messages(message.from_user.id)
    if not messages:
        await message.answer("Пока нечего экспортировать — сохранённых сообщений нет.")
        return

    html_doc = build_export_html(messages)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M")
    document = BufferedInputFile(
        html_doc.encode("utf-8"), filename=f"perepiska_{stamp}.html"
    )
    await message.answer_document(
        document,
        caption=f"📦 Экспорт переписки: {len(messages)} сообщений. "
        "Откройте файл в браузере.",
    )
