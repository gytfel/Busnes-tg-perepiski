"""Интерфейс владельца в личном чате с ботом — на кнопках.

Главное меню — постоянная клавиатура снизу (app/keyboards.py). Слэш-команды
(/status, /search, /export, /help) оставлены как запасной вариант. Поиск
запрашивает текст через состояние FSM.
"""
from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, Message

from app import keyboards as kb
from app.config import Config
from app.database import Database
from app.export import build_export
from app.utils import esc

router = Router(name="commands")

START_TEXT = (
    "👋 <b>Привет!</b> Это бот-архиватор переписки для вашего Telegram Business.\n\n"
    "Что я умею, когда подключён к вашему аккаунту:\n"
    "• сохраняю входящие и исходящие сообщения ваших чатов;\n"
    "• присылаю сюда копию, если сообщение <b>удалили</b> (🗑);\n"
    "• показываю, что было <b>изменено</b> (✏️), — старую и новую версии.\n\n"
    "Пользуйтесь <b>кнопками снизу</b> 👇"
)

HELP_TEXT = (
    "ℹ️ <b>Справка</b>\n\n"
    "📊 <b>Статус</b> — активные подключения и число сохранённых сообщений\n"
    "🔍 <b>Поиск</b> — найти сообщение по тексту (нажмите и введите слово)\n"
    "📦 <b>Экспорт</b> — выгрузить всю переписку в HTML-файл\n\n"
    "Те же действия есть и командами: /status, /search, /export.\n\n"
    "⚠️ Бот работает только с аккаунтом, который сам его подключил, и обрабатывает "
    "вашу собственную переписку. Соблюдайте законы вашей страны о записи переписки."
)

SEARCH_LIMIT = 20


class SearchStates(StatesGroup):
    waiting_query = State()


def _fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "—"


# --- Общие действия (вызываются и кнопкой, и командой) ---------------------
async def _show_status(message: Message, db: Database) -> None:
    if message.from_user is None:
        return
    connections = await db.list_connections(message.from_user.id)
    total = await db.count_messages(message.from_user.id)

    if not connections:
        await message.answer(
            "❌ Активных подключений нет.\n"
            "Подключите бота в Settings → Telegram Business → Chatbots.",
            reply_markup=kb.main_menu(),
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
    await message.answer("\n".join(lines), reply_markup=kb.main_menu())


async def _do_search(message: Message, db: Database, query: str) -> None:
    if message.from_user is None:
        return
    query = query.strip()
    if not query:
        await message.answer("Пустой запрос. Введите слово для поиска.")
        return

    results = await db.search_messages(message.from_user.id, query, limit=SEARCH_LIMIT)
    if not results:
        await message.answer(
            f"🔍 По запросу «{esc(query)}» ничего не найдено.",
            reply_markup=kb.main_menu(),
        )
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
    await message.answer("\n".join(lines)[:4096], reply_markup=kb.main_menu())


async def _do_export(
    message: Message, db: Database, bot: Bot, config: Config
) -> None:
    if message.from_user is None:
        return
    messages = await db.all_messages(message.from_user.id)
    if not messages:
        await message.answer(
            "Пока нечего экспортировать — сохранённых сообщений нет.",
            reply_markup=kb.main_menu(),
        )
        return

    await message.answer(
        "⏳ Готовлю экспорт и скачиваю медиа — это может занять время…"
    )

    budget = config.export_media_mb * 1024 * 1024
    html_doc, stats = await build_export(bot, messages, budget)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M")
    document = BufferedInputFile(
        html_doc.encode("utf-8"), filename=f"perepiska_{stamp}.html"
    )

    caption = (
        f"📦 Экспорт: {len(messages)} сообщений, встроено медиа: {stats.embedded}.\n"
        "Откройте файл в браузере — фото/видео/голосовые играются прямо в нём."
    )
    if stats.notes:
        caption += "\n\n⚠️ " + " ".join(stats.notes)

    try:
        await message.answer_document(document, caption=caption[:1024])
    except Exception as exc:
        await message.answer(
            "❌ Не удалось отправить экспорт (вероятно, файл больше 50 МБ). "
            "Уменьшите EXPORT_MEDIA_MB в .env или экспортируйте меньше переписки.\n"
            f"<code>{esc(str(exc))[:200]}</code>",
            reply_markup=kb.main_menu(),
        )


# --- Слэш-команды ----------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(START_TEXT, reply_markup=kb.main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=kb.main_menu())


@router.message(Command("status"))
async def cmd_status(message: Message, db: Database) -> None:
    await _show_status(message, db)


@router.message(Command("export"))
async def cmd_export(message: Message, db: Database, bot: Bot, config: Config) -> None:
    await _do_export(message, db, bot, config)


@router.message(Command("search"))
async def cmd_search(
    message: Message, command: CommandObject, db: Database, state: FSMContext
) -> None:
    query = (command.args or "").strip()
    if not query:
        await state.set_state(SearchStates.waiting_query)
        await message.answer(
            "🔍 Введите текст для поиска:", reply_markup=kb.cancel_menu()
        )
        return
    await _do_search(message, db, query)


# --- Кнопки главного меню (срабатывают в любом состоянии) ------------------
@router.message(F.text == kb.BTN_STATUS)
async def btn_status(message: Message, db: Database, state: FSMContext) -> None:
    await state.clear()
    await _show_status(message, db)


@router.message(F.text == kb.BTN_EXPORT)
async def btn_export(
    message: Message, db: Database, state: FSMContext, bot: Bot, config: Config
) -> None:
    await state.clear()
    await _do_export(message, db, bot, config)


@router.message(F.text == kb.BTN_HELP)
async def btn_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(HELP_TEXT, reply_markup=kb.main_menu())


@router.message(F.text == kb.BTN_SEARCH)
async def btn_search(message: Message, state: FSMContext) -> None:
    await state.set_state(SearchStates.waiting_query)
    await message.answer("🔍 Введите текст для поиска:", reply_markup=kb.cancel_menu())


@router.message(F.text == kb.BTN_CANCEL)
async def btn_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=kb.main_menu())


# --- Ввод поискового запроса (только в состоянии ожидания) -----------------
@router.message(StateFilter(SearchStates.waiting_query), F.text)
async def on_search_query(message: Message, db: Database, state: FSMContext) -> None:
    await state.clear()
    await _do_search(message, db, message.text or "")


# --- Любой другой текст вне состояния — показать меню ----------------------
@router.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer(
        "Не понял. Выберите действие кнопками снизу 👇", reply_markup=kb.main_menu()
    )
