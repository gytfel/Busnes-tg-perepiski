"""Точка входа: запуск бота в режиме long polling."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import Config, load_config
from app.database import Database
from app.handlers import business, commands
from app.platesh_client import PlateshClient

logger = logging.getLogger(__name__)

PAYWALL_TEXT = (
    "🔒 <b>Архиватор переписки для Telegram Business</b>\n\n"
    "Сохраняю сообщения ваших чатов и присылаю копию, если собеседник <b>удалит</b> "
    "или <b>изменит</b> сообщение. Плюс поиск и экспорт переписки.\n\n"
    "Доступ открывается после оплаты:"
)
BUSINESS_PAYWALL_TEXT = (
    "🔒 Бот подключён, но <b>сохранять переписку начнёт после оплаты</b>. "
    "До этого сообщения не записываются. Оформите доступ:"
)


def connect_platesh(config: Config) -> PlateshClient | None:
    """Платный доступ через Platesh, если он настроен в .env (PLATESH_URL, PLATESH_KEY, PLATESH_BOT)."""
    if not config.platesh_url:
        logger.warning("PLATESH_URL не задан — платный доступ выключен, бот бесплатный для всех.")
        return None
    platesh = PlateshClient.from_env()
    logger.info("Платный доступ через Platesh включён (%s, бот «%s»)", platesh.base_url, platesh.bot)
    return platesh


def build_dispatcher(db: Database, config: Config, platesh: PlateshClient | None) -> Dispatcher:
    # db и config доступны в хендлерах как аргументы через внедрение зависимостей.
    # MemoryStorage — для FSM (состояние ввода поискового запроса).
    dp = Dispatcher(storage=MemoryStorage(), db=db, config=config)
    if platesh is not None:
        # Раньше остальных роутеров: подтверждение оплат Stars и кнопки «Оплатить»/«Продлить».
        dp.include_router(platesh.router(guard=False))
        # Без оплаты: в личке — предложение оплатить, бизнес-переписка не сохраняется.
        platesh.install_paywall(
            dp,
            products=config.platesh_products or None,
            allow_commands=("paysupport", "terms", "help"),
            exempt_users=[config.owner_id] if config.owner_id else (),
            text=PAYWALL_TEXT,
            business_text=BUSINESS_PAYWALL_TEXT,
        )
    dp.include_router(commands.router)
    dp.include_router(business.router)
    return dp


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    config = load_config()

    db = Database(config.db_path)
    await db.init()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    platesh = connect_platesh(config)
    dp = build_dispatcher(db, config, platesh)

    # Явно подписываемся на бизнес-апдейты (их нужно перечислить в allowed_updates).
    allowed_updates = dp.resolve_used_update_types()
    logger.info("Запуск polling. allowed_updates=%s", allowed_updates)

    me = await bot.get_me()
    logger.info("Бот @%s запущен (id=%s)", me.username, me.id)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    finally:
        await bot.session.close()
        await db.close()
        if platesh is not None:
            await platesh.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановлено.")
