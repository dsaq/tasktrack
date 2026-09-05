"""
Планировщик: раз в минуту ищет задачи, которым пора напомнить, и шлёт напоминание.
Подход «тик по БД» устойчив к перезапускам — ничего не теряется, всё в базе.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from telegram import Bot
from telegram.constants import ParseMode

import db
import logic
import ui

log = logging.getLogger("scheduler")


async def tick(bot: Bot) -> int:
    """Один проход. Возвращает число отправленных напоминаний."""
    now = dt.datetime.now(dt.timezone.utc)
    sent = 0

    with db.SessionLocal() as s:
        due = s.scalars(
            select(db.Task)
            .where(db.Task.status != db.ST_DONE)
            .where(db.Task.next_fire_at <= now)
        ).all()

        # карта часовых поясов пользователей
        tz_cache: dict[int, str] = {}

        for task in due:
            tz = tz_cache.get(task.owner_chat_id)
            if tz is None:
                user = s.get(db.User, task.owner_chat_id)
                tz = user.tz if user else db.settings.default_tz  # type: ignore[attr-defined]
                tz_cache[task.owner_chat_id] = tz

            try:
                await bot.send_message(
                    chat_id=task.owner_chat_id,
                    text=ui.reminder_text(task, tz),
                    reply_markup=ui.reminder_keyboard(task),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("Не удалось отправить напоминание #%s: %s", task.id, e)
                # чтобы не долбить в цикле, всё равно сдвигаем время
            # обновляем состояние
            task.fire_count += 1
            task.last_fired_at = now
            task.status = db.ST_ACTIVE
            task.next_fire_at = logic.next_fire_after(task, now)
            sent += 1

        if sent:
            s.commit()

    if sent:
        log.info("tick: отправлено напоминаний: %s", sent)
    return sent
