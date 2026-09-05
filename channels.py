"""
Формирование быстрой ссылки «написать/позвонить» по каналу связи.
Система сама никому не пишет — она даёт тебе кнопку в один клик.
"""

from __future__ import annotations

from typing import Optional

import db


def channel_action(channel: str, ref: Optional[str]) -> Optional[tuple[str, str]]:
    """
    Возвращает (текст_кнопки, url) или None, если ссылки нет.
    ref — @username / ссылка / телефон, в зависимости от канала.
    """
    if not ref:
        ref = ""
    ref = ref.strip()

    if channel == db.CH_TELEGRAM and ref:
        username = ref.lstrip("@")
        if username.startswith("http"):
            return ("✍️ Написать в Telegram", username)
        return ("✍️ Написать в Telegram", f"https://t.me/{username}")

    if channel == db.CH_MAX and ref:
        # MAX (max.ru): если дали ссылку — используем как есть, иначе профиль по нику
        if ref.startswith("http"):
            return ("✍️ Открыть в MAX", ref)
        return ("✍️ Открыть в MAX", f"https://max.ru/{ref.lstrip('@')}")

    if channel == db.CH_YOUGILE and ref:
        # YouGile — ссылка на задачу/доску
        return ("📋 Открыть в YouGile", ref if ref.startswith("http") else f"https://ru.yougile.com/{ref}")

    if channel == db.CH_CALL and ref:
        # Телефон — tel: работает на телефоне
        phone = ref.replace(" ", "")
        return ("📞 Позвонить", f"tel:{phone}")

    return None
