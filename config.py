"""
Конфигурация TaskTrack. Всё читается из переменных окружения.
Локально можно положить .env рядом (см. .env.example).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


@dataclass
class Settings:
    # Токен Telegram-бота от @BotFather
    telegram_token: str = os.getenv("TELEGRAM_TOKEN", "")

    # Публичный адрес сервиса, куда Telegram шлёт вебхуки (без слэша в конце)
    # Пример: https://tasktrack-production.up.railway.app
    base_url: str = os.getenv("BASE_URL", "").rstrip("/")

    # Секрет для пути вебхука и для API виджета
    secret: str = os.getenv("SECRET", "change-me")

    # База данных. По умолчанию локальный SQLite-файл.
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///tasktrack.db")

    # Часовой пояс по умолчанию (для показа времени и тихих часов)
    default_tz: str = os.getenv("DEFAULT_TZ", "Europe/Moscow")

    # Порт (хостинги обычно задают его сами)
    port: int = int(os.getenv("PORT", "8080"))

    @property
    def webhook_path(self) -> str:
        return f"/telegram/{self.secret}"

    @property
    def webhook_url(self) -> str:
        return f"{self.base_url}{self.webhook_path}"


settings = Settings()
