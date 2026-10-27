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
from app.platesh_client import PlateshClient, PlateshError

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


PAYWALL_TEXT = (
    "🔒 <b>Бот ограничен</b>\n\n"
    "Чтобы пользоваться ботом, нужна подписка. С ней я:\n"
    "• сохраняю сообщения ваших чатов в Telegram Business;\n"
    "• присылаю копию, если собеседник <b>удалит</b> или <b>изменит</b> сообщение;\n"
    "• ищу по переписке и выгружаю её в файл.\n\n"
    "Выберите подписку:"
)
BUSINESS_PAYWALL_TEXT = (
    "🔒 <b>Бот ограничен</b>\n\n"
    "Бот подключён к вашему аккаунту, но <b>сохранять переписку начнёт после оформления подписки</b>. "
    "До этого сообщения не записываются.\n\n"
    "Выберите подписку:"
)
METHOD_TEXT = "Выберите способ оплаты:"
COIN_TEXT = "Выберите монету:"


def connect_platesh(config: Config) -> PlateshClient | None:
    """Платный доступ через Platesh, если он настроен в .env (PLATESH_URL, PLATESH_KEY, PLATESH_BOT)."""
    if not config.platesh_url:
        logger.warning("PLATESH_URL не задан — платный доступ выключен, бот бесплатный для всех.")
        return None
    try:
        platesh = PlateshClient.from_env()
    except PlateshError as exc:
        # Не запускаемся бесплатно по ошибке: лучше понятная остановка, чем открытый доступ.
        logger.error(
            "Платный доступ настроен не полностью: %s. Исправь одной командой в папке бота: "
            "sudo bash connect_platesh.sh", exc,
        )
        raise SystemExit(1) from None
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
            method_text=METHOD_TEXT,
            coin_text=COIN_TEXT,
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
    platesh = connect_platesh(config)

    db = Database(config.db_path)
    await db.init()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = build_dispatcher(db, config, platesh)

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
        if platesh is not None:
            await platesh.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановлено.")
