"""
Тексты и клавиатуры Telegram. Отдельный модуль, чтобы им пользовались
и бот, и планировщик без циклических импортов.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db
from channels import channel_action
from config import settings


def fmt_local(when: dt.datetime, tz: str) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    local = when.astimezone(ZoneInfo(tz or settings.default_tz))
    return local.strftime("%d.%m %H:%M")


def _type_note(task: "db.Task") -> str:
    if task.type == db.TYPE_INTERVAL and task.interval_hours:
        h = task.interval_hours
        h_str = f"{h:g}"
        return f"🔁 пинг каждые {h_str} ч"
    if task.type == db.TYPE_CHAIN:
        return "🔗 цепочка контроля"
    return "📌 разовая"


def reminder_text(task: "db.Task", tz: str) -> str:
    head = "⏰ <b>Пора проконтролировать</b>"
    who = f"<b>{task.person}</b> — " if task.person else ""
    lines = [
        head,
        f"{who}{task.title}",
        f"Канал: {db.CHANNEL_LABELS.get(task.channel, '—')}   ·   {_type_note(task)}",
    ]
    if task.fire_count:
        lines.append(f"<i>напоминание №{task.fire_count + 1}</i>")
    return "\n".join(lines)


def reminder_keyboard(task: "db.Task") -> InlineKeyboardMarkup:
    rows = []

    action = channel_action(task.channel, task.channel_ref)
    if action:
        label, url = action
        rows.append([InlineKeyboardButton(label, url=url)])

    rows.append([
        InlineKeyboardButton("✅ Готово", callback_data=f"done:{task.id}"),
        InlineKeyboardButton("⏳ Написал, жду", callback_data=f"waiting:{task.id}"),
    ])
    rows.append([
        InlineKeyboardButton("😴 +1ч", callback_data=f"snooze:{task.id}:1"),
        InlineKeyboardButton("+3ч", callback_data=f"snooze:{task.id}:3"),
        InlineKeyboardButton("Завтра", callback_data=f"snooze:{task.id}:24"),
    ])
    return InlineKeyboardMarkup(rows)


def task_line(task: "db.Task", tz: str) -> str:
    who = f"{task.person} — " if task.person else ""
    status_icon = {
        db.ST_ACTIVE: "🟢",
        db.ST_WAITING: "⏳",
        db.ST_SNOOZED: "😴",
        db.ST_DONE: "✅",
    }.get(task.status, "•")
    return f"{status_icon} <b>#{task.id}</b> {who}{task.title}  —  {fmt_local(task.next_fire_at, tz)}"
