"""
Запуск бота на VPS в режиме polling (без домена и вебхука).
Явный жизненный цикл: initialize -> start -> polling -> вечный цикл планировщика.
Так процесс не завершается сам и не уходит в перезапуск.
"""

from __future__ import annotations

import asyncio
import logging

from telegram import BotCommand
from telegram.ext import Application

import bot as botmod
import db
import scheduler
from config import settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot_polling")


async def scheduler_loop(app: Application) -> None:
    """Раз в минуту проверяем задачи и шлём напоминания — вечно."""
    while True:
        try:
            await scheduler.tick(app.bot)
        except Exception:  # noqa: BLE001
            log.exception("Ошибка в тике планировщика")
        await asyncio.sleep(60)


async def main() -> None:
    if not settings.telegram_token:
        log.error("Не задан TELEGRAM_TOKEN — проверь .env")
        return

    db.init_db()
    app = Application.builder().token(settings.telegram_token).build()
    botmod.register(app)

    await app.initialize()
    await app.bot.set_my_commands([
        BotCommand("add", "Добавить задачу на контроль"),
        BotCommand("today", "Что на сегодня"),
        BotCommand("all", "Все активные"),
        BotCommand("help", "Как это работает"),
        BotCommand("cancel", "Отменить добавление"),
    ])
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log.info("Бот запущен (polling). Планировщик активен.")

    await scheduler_loop(app)  # блокирует процесс навсегда


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception:  # noqa: BLE001
        log.exception("Фатальная ошибка при запуске бота")
