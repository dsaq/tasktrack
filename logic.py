"""
Чистая логика напоминаний — без Telegram и без БД-сессий, чтобы её можно
было покрыть тестами.

Ключевая функция: next_fire_after — когда напомнить в следующий раз,
после того как напоминание уже отправлено (и задача не закрыта).
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import db


def _aware(when: dt.datetime) -> dt.datetime:
    if when.tzinfo is None:
        return when.replace(tzinfo=dt.timezone.utc)
    return when


def apply_quiet_hours(
    when: dt.datetime,
    tz: str,
    quiet_start: int | None,
    quiet_end: int | None,
) -> dt.datetime:
    """
    Если время попадает в «тихие часы» (например 23:00–08:00), сдвигаем на конец
    окна. Окно может пересекать полночь. Возвращает время в UTC (aware).
    """
    if quiet_start is None or quiet_end is None or quiet_start == quiet_end:
        return _aware(when)

    zone = ZoneInfo(tz or "UTC")
    local = _aware(when).astimezone(zone)
    h = local.hour

    def in_quiet(hour: int) -> bool:
        if quiet_start < quiet_end:
            return quiet_start <= hour < quiet_end
        # окно через полночь, напр. 23..8
        return hour >= quiet_start or hour < quiet_end

    if not in_quiet(h):
        return _aware(when)

    # сдвигаем на quiet_end того же/следующего дня
    target = local.replace(minute=0, second=0, microsecond=0, hour=quiet_end % 24)
    if quiet_start < quiet_end:
        # проснёмся в тот же день в quiet_end
        if local.hour >= quiet_end:
            target = target + dt.timedelta(days=1)
    else:
        # окно через полночь: если сейчас поздний вечер — конец завтра утром
        if local.hour >= quiet_start:
            target = target + dt.timedelta(days=1)
    return target.astimezone(dt.timezone.utc)


def next_fire_after(task: "db.Task", now: dt.datetime) -> dt.datetime:
    """
    Когда напомнить в следующий раз после текущего срабатывания.
    now — момент срабатывания (UTC, aware).
    """
    now = _aware(now)

    if task.type == db.TYPE_INTERVAL:
        step = dt.timedelta(hours=task.interval_hours or 3.0)
        return now + step

    if task.type == db.TYPE_CHAIN:
        # эскалация: перенос на сутки вперёд
        return now + dt.timedelta(days=1)

    # TYPE_ONCE: дожимаем каждые overdue_hours
    return now + dt.timedelta(hours=task.overdue_hours or 2.0)


def is_due(task: "db.Task", now: dt.datetime) -> bool:
    if task.status == db.ST_DONE:
        return False
    return _aware(task.next_fire_at) <= _aware(now)
