"""Точка входа: запуск бота в режиме long polling."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import load_config
from app.database import Database
from app.handlers import business, commands
from app.maintenance import run_maintenance

logger = logging.getLogger(__name__)


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

    # db и config доступны в хендлерах как аргументы через внедрение зависимостей.
    # MemoryStorage — для FSM (состояние ввода поискового запроса).
    dp = Dispatcher(storage=MemoryStorage(), db=db, config=config)
    dp.include_router(commands.router)
    dp.include_router(business.router)

    # Явно подписываемся на бизнес-апдейты (их нужно перечислить в allowed_updates).
    allowed_updates = dp.resolve_used_update_types()
    logger.info("Запуск polling. allowed_updates=%s", allowed_updates)

    me = await bot.get_me()
    logger.info("Бот @%s запущен (id=%s)", me.username, me.id)

    # Фоновая авто-выгрузка при приближении БД к лимиту (если включена).
    maintenance_task = asyncio.create_task(run_maintenance(bot, db, config))

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    finally:
        maintenance_task.cancel()
        try:
            await maintenance_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановлено.")
