"""
База данных TaskTrack.

Одна таблица задач + таблица пользователей (кто общается с ботом).
Работает и на SQLite (локально), и на PostgreSQL (облако) — выбор по DATABASE_URL.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from config import settings


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

# Тип задачи
TYPE_ONCE = "once"          # разовая со сроком; если не закрыл — дожимает
TYPE_CHAIN = "chain"        # цепочка контроля; эскалация день за днём
TYPE_INTERVAL = "interval"  # пинг каждые N часов, пока не закрыл

# Статусы
ST_ACTIVE = "active"        # ждёт своего времени / напоминает
ST_WAITING = "waiting"      # «написал, жду ответа» — контроль отложен на завтра
ST_SNOOZED = "snoozed"      # отложено вручную
ST_DONE = "done"            # закрыто

# Каналы связи
CH_TELEGRAM = "telegram"
CH_MAX = "max"
CH_YOUGILE = "yougile"
CH_CALL = "call"
CH_NONE = "none"

CHANNEL_LABELS = {
    CH_TELEGRAM: "Telegram",
    CH_MAX: "MAX",
    CH_YOUGILE: "YouGile",
    CH_CALL: "Звонок/лично",
    CH_NONE: "—",
}


# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tz: Mapped[str] = mapped_column(String(64), default=settings.default_tz)
    quiet_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # час 0-23
    quiet_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)

    title: Mapped[str] = mapped_column(Text)                                    # что сделать
    person: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)   # кого контролировать
    channel: Mapped[str] = mapped_column(String(32), default=CH_NONE)
    channel_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)     # @user / url / телефон

    type: Mapped[str] = mapped_column(String(16), default=TYPE_ONCE)
    interval_hours: Mapped[Optional[float]] = mapped_column(nullable=True)      # для interval
    overdue_hours: Mapped[float] = mapped_column(default=2.0)                   # для once: как часто дожимать

    due_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))        # первый срок
    next_fire_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_fired_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default=ST_ACTIVE, index=True)
    fire_count: Mapped[int] = mapped_column(Integer, default=0)                 # сколько раз напомнили

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------------------
# Движок / сессии
# ---------------------------------------------------------------------------

def _normalize_url(url: str) -> str:
    # Драйвер psycopg v3 для Postgres
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


engine = create_engine(_normalize_url(settings.database_url), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(engine)
