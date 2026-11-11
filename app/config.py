import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    bot_token: str
    mini_app_url: str
    web_host: str = "127.0.0.1"
    web_port: int = 8080


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.getenv("API_BOT")
    if not token:
        raise RuntimeError("Добавьте API_BOT в файл .env")
    url = os.getenv("MINI_APP_URL", "").strip()
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password):
        raise RuntimeError(
            "Укажите MINI_APP_URL в .env: публичный HTTPS-адрес Mini App. "
            "Инструкция запуска находится в README.md."
        )
    try:
        port = int(os.getenv("WEB_PORT", "8080"))
    except ValueError as error:
        raise RuntimeError("WEB_PORT должен быть числом от 1 до 65535") from error
    if not 1 <= port <= 65535:
        raise RuntimeError("WEB_PORT должен быть числом от 1 до 65535")
    return Settings(token, url, os.getenv("WEB_HOST", "127.0.0.1"), port)
