"""
Небольшой API к той же базе, что и бот (для десктоп-виджета).
Работает рядом с ботом, отдельным процессом на порту 8080.
Запуск: uvicorn api:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import datetime as dt

import dateparser
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select

import db
from config import settings

db.init_db()  # гарантируем, что таблицы существуют

app = FastAPI(title="TaskTrack API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def check_token(x_token: str = Header(default="")) -> None:
    if x_token != settings.secret:
        raise HTTPException(401, "bad token")


def parse_when(text: str, tz: str) -> dt.datetime:
    from zoneinfo import ZoneInfo
    base = dt.datetime.now(ZoneInfo(tz))
    parsed = dateparser.parse(
        text or "сейчас", languages=["ru"],
        settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": base,
                  "RETURN_AS_TIMEZONE_AWARE": True, "TIMEZONE": tz, "TO_TIMEZONE": "UTC"},
    )
    if parsed is None:
        return dt.datetime.now(dt.timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def task_to_dict(t: "db.Task") -> dict:
    return {
        "id": t.id, "title": t.title, "person": t.person,
        "channel": t.channel, "channel_ref": t.channel_ref,
        "type": t.type, "status": t.status,
        "next_fire_at": t.next_fire_at.astimezone(dt.timezone.utc).isoformat(),
        "fire_count": t.fire_count,
    }


@app.get("/")
def health():
    return {"ok": True, "service": "tasktrack-api"}


@app.get("/api/tasks", dependencies=[Depends(check_token)])
def api_tasks(chat_id: int, all: bool = False):
    with db.SessionLocal() as s:
        q = (select(db.Task)
             .where(db.Task.owner_chat_id == chat_id)
             .where(db.Task.status != db.ST_DONE)
             .order_by(db.Task.next_fire_at))
        tasks = s.scalars(q).all()
    if not all:
        end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)
        tasks = [t for t in tasks if t.next_fire_at <= end]
    return {"tasks": [task_to_dict(t) for t in tasks]}


class CreateTask(BaseModel):
    chat_id: int
    title: str
    person: str | None = None
    channel: str = db.CH_NONE
    channel_ref: str | None = None
    type: str = db.TYPE_ONCE
    interval_hours: float | None = None
    when: str = "сейчас"
    tz: str | None = None


@app.post("/api/tasks", dependencies=[Depends(check_token)])
def api_create(body: CreateTask):
    tz = body.tz or settings.default_tz
    when = parse_when(body.when, tz)
    with db.SessionLocal() as s:
        if s.get(db.User, body.chat_id) is None:
            s.add(db.User(chat_id=body.chat_id, tz=tz))
        t = db.Task(
            owner_chat_id=body.chat_id, title=body.title, person=body.person,
            channel=body.channel, channel_ref=body.channel_ref, type=body.type,
            interval_hours=body.interval_hours, due_at=when, next_fire_at=when,
            status=db.ST_ACTIVE,
        )
        s.add(t)
        s.commit()
        s.refresh(t)
        return task_to_dict(t)


def _mutate(task_id: int, chat_id: int, **fields):
    with db.SessionLocal() as s:
        t = s.get(db.Task, task_id)
        if not t or t.owner_chat_id != chat_id:
            raise HTTPException(404, "not found")
        for k, v in fields.items():
            setattr(t, k, v)
        s.commit()
        s.refresh(t)
        return task_to_dict(t)


@app.post("/api/tasks/{task_id}/done", dependencies=[Depends(check_token)])
def api_done(task_id: int, chat_id: int):
    return _mutate(task_id, chat_id, status=db.ST_DONE)


@app.post("/api/tasks/{task_id}/snooze", dependencies=[Depends(check_token)])
def api_snooze(task_id: int, chat_id: int, hours: float = 1.0):
    nf = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)
    return _mutate(task_id, chat_id, status=db.ST_SNOOZED, next_fire_at=nf)


@app.post("/api/tasks/{task_id}/waiting", dependencies=[Depends(check_token)])
def api_waiting(task_id: int, chat_id: int):
    nf = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)
    return _mutate(task_id, chat_id, status=db.ST_WAITING, next_fire_at=nf)
