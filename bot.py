"""
Telegram-бот TaskTrack: команды, пошаговое добавление задач, кнопки действий.
"""

from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

import dateparser
from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
import logic
import ui
from config import settings

log = logging.getLogger("bot")

# Состояния диалога добавления
TITLE, PERSON, CHANNEL, CHANNEL_REF, TTYPE, INTERVAL, WHEN = range(7)


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def get_user_tz(chat_id: int) -> str:
    with db.SessionLocal() as s:
        u = s.get(db.User, chat_id)
        return u.tz if u else settings.default_tz


def ensure_user(chat_id: int, name: str | None) -> None:
    with db.SessionLocal() as s:
        u = s.get(db.User, chat_id)
        if u is None:
            s.add(db.User(chat_id=chat_id, name=name))
            s.commit()


def parse_when(text: str, tz: str) -> dt.datetime | None:
    """Парсит русскую дату/время в UTC-aware datetime."""
    zone = ZoneInfo(tz)
    base = dt.datetime.now(zone)
    parsed = dateparser.parse(
        text,
        languages=["ru"],
        settings={
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": base,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TIMEZONE": tz,
            "TO_TIMEZONE": "UTC",
        },
    )
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


# ---------------------------------------------------------------------------
# Базовые команды
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    ensure_user(chat.id, update.effective_user.full_name if update.effective_user else None)
    await update.message.reply_text(
        "Привет! Я держу твои задачи на контроле и напоминаю, пока ты не закроешь их.\n\n"
        "• /add — добавить задачу на контроль\n"
        "• /today — что на сегодня\n"
        "• /all — все активные\n"
        "• /help — подробнее\n\n"
        "Добавь первую задачу командой /add.",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Как это работает</b>\n\n"
        "Ты заводишь задачу и указываешь:\n"
        "• что проконтролировать и с кем;\n"
        "• канал (Telegram / MAX / YouGile / звонок);\n"
        "• тип контроля:\n"
        "   📌 <b>разовая</b> — напомню к сроку и буду дожимать, пока не закроешь;\n"
        "   🔗 <b>цепочка</b> — если не сделано, напомню снова на следующий день, и так далее;\n"
        "   🔁 <b>интервал</b> — пингую каждые N часов (для горящего).\n\n"
        "В напоминании — кнопки: <b>Готово</b>, <b>Написал/жду</b> (перенос на завтра), "
        "<b>Отложить</b> (+1ч/+3ч/завтра) и быстрая ссылка «написать» по каналу.\n\n"
        "Команды: /add /today /all /cancel",
        parse_mode=ParseMode.HTML,
    )


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cid = update.effective_chat.id
    await update.message.reply_text(
        f"Твой chat_id: <code>{cid}</code>\nВставь его в config.json виджета.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _list_tasks(update, only_today=True)


async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _list_tasks(update, only_today=False)


async def _list_tasks(update: Update, only_today: bool) -> None:
    chat_id = update.effective_chat.id
    tz = get_user_tz(chat_id)
    with db.SessionLocal() as s:
        q = (
            select(db.Task)
            .where(db.Task.owner_chat_id == chat_id)
            .where(db.Task.status != db.ST_DONE)
            .order_by(db.Task.next_fire_at)
        )
        tasks = s.scalars(q).all()

    if only_today:
        end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)
        tasks = [t for t in tasks if t.next_fire_at <= end]

    if not tasks:
        await update.message.reply_text("Пусто. Всё под контролем ✅")
        return

    header = "🗓 <b>На сегодня</b>" if only_today else "📋 <b>Все активные</b>"
    lines = [header] + [ui.task_line(t, tz) for t in tasks]
    lines.append("\nЗакрыть: /done_&lt;номер&gt;   ·   добавить: /add")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)


async def cmd_done_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка /done_12 — закрыть задачу №12."""
    text = update.message.text or ""
    try:
        task_id = int(text.split("_", 1)[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Формат: /done_12")
        return
    ok = _set_done(update.effective_chat.id, task_id)
    await update.message.reply_text("Закрыто ✅" if ok else "Не нашёл такую задачу.")


def _set_done(chat_id: int, task_id: int) -> bool:
    with db.SessionLocal() as s:
        t = s.get(db.Task, task_id)
        if not t or t.owner_chat_id != chat_id:
            return False
        t.status = db.ST_DONE
        s.commit()
        return True


# ---------------------------------------------------------------------------
# Диалог добавления задачи
# ---------------------------------------------------------------------------

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ensure_user(update.effective_chat.id,
                update.effective_user.full_name if update.effective_user else None)
    context.user_data["new"] = {}
    await update.message.reply_text(
        "Что проконтролировать? Коротко.\n<i>Например: «прислать остатки», «подписать договор»</i>\n\n/cancel — отмена",
        parse_mode=ParseMode.HTML,
    )
    return TITLE


async def add_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new"]["title"] = update.message.text.strip()
    await update.message.reply_text("Кого контролируем? Имя. (или «-» если никого)")
    return PERSON


async def add_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    context.user_data["new"]["person"] = None if val in ("-", "—") else val
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Telegram", callback_data="ch:telegram"),
         InlineKeyboardButton("MAX", callback_data="ch:max")],
        [InlineKeyboardButton("YouGile", callback_data="ch:yougile"),
         InlineKeyboardButton("Звонок/лично", callback_data="ch:call")],
        [InlineKeyboardButton("Без канала", callback_data="ch:none")],
    ])
    await update.message.reply_text("Как будешь связываться?", reply_markup=kb)
    return CHANNEL


async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    channel = q.data.split(":", 1)[1]
    context.user_data["new"]["channel"] = channel
    if channel == db.CH_NONE:
        context.user_data["new"]["channel_ref"] = None
        return await _ask_type(q)
    prompts = {
        db.CH_TELEGRAM: "Дай @ник или ссылку t.me (или «-»):",
        db.CH_MAX: "Ник/ссылка в MAX (или «-»):",
        db.CH_YOUGILE: "Ссылка на задачу/доску в YouGile (или «-»):",
        db.CH_CALL: "Телефон (или «-»):",
    }
    await q.edit_message_text(prompts.get(channel, "Контакт (или «-»):"))
    return CHANNEL_REF


async def add_channel_ref(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    val = update.message.text.strip()
    context.user_data["new"]["channel_ref"] = None if val in ("-", "—") else val
    return await _ask_type(update.message)


async def _ask_type(msg_or_query) -> int:
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Разовая", callback_data="ty:once")],
        [InlineKeyboardButton("🔗 Цепочка контроля", callback_data="ty:chain")],
        [InlineKeyboardButton("🔁 Каждые N часов", callback_data="ty:interval")],
    ])
    text = (
        "Тип контроля:\n"
        "📌 <b>разовая</b> — напомню к сроку и дожму;\n"
        "🔗 <b>цепочка</b> — не сделано → напомню и завтра, и дальше;\n"
        "🔁 <b>интервал</b> — пинг каждые N часов."
    )
    if hasattr(msg_or_query, "edit_message_text"):
        await msg_or_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await msg_or_query.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return TTYPE


async def add_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    ttype = q.data.split(":", 1)[1]
    context.user_data["new"]["type"] = ttype
    if ttype == db.TYPE_INTERVAL:
        await q.edit_message_text("Каждые сколько часов пинговать? Число, напр. 3")
        return INTERVAL
    await q.edit_message_text(
        "Когда первое напоминание?\n<i>Напиши: «завтра 15:00», «через 2 часа», «в пятницу 10:00», «сейчас»</i>",
        parse_mode=ParseMode.HTML,
    )
    return WHEN


async def add_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        hours = float(update.message.text.strip().replace(",", "."))
        if hours <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Нужно положительное число часов, напр. 3")
        return INTERVAL
    context.user_data["new"]["interval_hours"] = hours
    await update.message.reply_text(
        "Когда первый пинг?\n<i>«сейчас», «через 1 час», «сегодня 18:00»</i>",
        parse_mode=ParseMode.HTML,
    )
    return WHEN


async def add_when(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    tz = get_user_tz(chat_id)
    when = parse_when(update.message.text.strip(), tz)
    if when is None:
        await update.message.reply_text(
            "Не понял время. Попробуй: «завтра 15:00», «через 2 часа», «в пятницу 10:00».")
        return WHEN

    data = context.user_data["new"]
    with db.SessionLocal() as s:
        task = db.Task(
            owner_chat_id=chat_id,
            title=data["title"],
            person=data.get("person"),
            channel=data.get("channel", db.CH_NONE),
            channel_ref=data.get("channel_ref"),
            type=data.get("type", db.TYPE_ONCE),
            interval_hours=data.get("interval_hours"),
            due_at=when,
            next_fire_at=when,
            status=db.ST_ACTIVE,
        )
        s.add(task)
        s.commit()
        s.refresh(task)
        line = ui.task_line(task, tz)

    context.user_data.pop("new", None)
    await update.message.reply_text(
        "Готово, поставил на контроль:\n" + line + "\n\nЕщё: /add   ·   список: /today",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new", None)
    await update.message.reply_text("Отменил.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Кнопки в напоминаниях: Готово / Жду / Отложить
# ---------------------------------------------------------------------------

async def on_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    parts = q.data.split(":")
    action = parts[0]
    task_id = int(parts[1])
    chat_id = update.effective_chat.id
    now = dt.datetime.now(dt.timezone.utc)

    with db.SessionLocal() as s:
        t = s.get(db.Task, task_id)
        if not t or t.owner_chat_id != chat_id:
            await q.answer("Задача не найдена", show_alert=False)
            return

        if action == "done":
            t.status = db.ST_DONE
            note = "✅ Закрыто"
        elif action == "waiting":
            t.status = db.ST_WAITING
            t.next_fire_at = now + dt.timedelta(hours=24)
            note = "⏳ Перенёс на завтра — проверю снова"
        elif action == "snooze":
            hours = float(parts[2])
            t.status = db.ST_SNOOZED
            t.next_fire_at = now + dt.timedelta(hours=hours)
            when_txt = ui.fmt_local(t.next_fire_at, get_user_tz(chat_id))
            note = f"😴 Отложил до {when_txt}"
        else:
            await q.answer()
            return
        s.commit()

    await q.answer(note)
    # снимаем кнопки и помечаем, что сделали
    try:
        base = q.message.text_html if q.message else ""
        await q.edit_message_text(f"{base}\n\n<b>{note}</b>", parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Регистрация обработчиков
# ---------------------------------------------------------------------------

def register(app: Application) -> None:
    conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_title)],
            PERSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_person)],
            CHANNEL: [CallbackQueryHandler(add_channel, pattern=r"^ch:")],
            CHANNEL_REF: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_channel_ref)],
            TTYPE: [CallbackQueryHandler(add_type, pattern=r"^ty:")],
            INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_interval)],
            WHEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_when)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        name="add_task",
        persistent=False,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("all", cmd_all))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(MessageHandler(filters.Regex(r"^/done_\d+"), cmd_done_number))
    app.add_handler(CallbackQueryHandler(on_action, pattern=r"^(done|waiting|snooze):"))
