"""Точка входа: запуск бота в режиме long polling."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import Config, load_config, reload_into
from app.database import Database
from app.handlers import business, commands
from app.maintenance import run_maintenance

logger = logging.getLogger(__name__)

# Как часто перечитывать .env для применения изменений на лету.
ENV_RELOAD_INTERVAL = 30


async def run_env_reloader(config: Config, interval: int = ENV_RELOAD_INTERVAL) -> None:
    """Периодически перечитывает .env и применяет «горячие» поля без рестарта."""
    while True:
        await asyncio.sleep(interval)
        try:
            changed = reload_into(config)
            if changed:
                logger.info("Перечитан .env, применено: %s", ", ".join(changed))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Не удалось перечитать .env (оставляю прежние значения)")


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

    # Фоновые задачи: авто-выгрузка при приближении БД к лимиту и
    # перечитка .env для применения изменений без перезапуска.
    background = [
        asyncio.create_task(run_maintenance(bot, db, config)),
        asyncio.create_task(run_env_reloader(config)),
    ]

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    finally:
        for task in background:
            task.cancel()
        for task in background:
            try:
                await task
            except asyncio.CancelledError:
                pass
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановлено.")
