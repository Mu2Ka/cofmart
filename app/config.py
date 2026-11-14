import os
from pathlib import Path
from typing import Mapping, TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from sqlalchemy import URL

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def get_bot_token() -> str:
    load_dotenv(ENV_PATH)
    token = os.getenv("API_BOT")
    if not token:
        raise RuntimeError("Добавьте API_BOT в файл .env")
    return token


def database_url_from_values(values: Mapping[str, str]) -> "URL":
    from sqlalchemy import URL

    required = ("DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [key for key in required if not values.get(key, "").strip()]
    if missing:
        raise ValueError("Добавьте в .env параметры PostgreSQL: " + ", ".join(missing))
    try:
        port = int(values.get("DB_PORT", "5432"))
    except (ValueError, TypeError) as error:
        raise ValueError("DB_PORT должен быть числом от 1 до 65535.") from error
    if not 1 <= port <= 65535:
        raise ValueError("DB_PORT должен быть числом от 1 до 65535.")
    return URL.create(
        "postgresql+asyncpg", username=values["DB_USER"], password=values["DB_PASSWORD"],
        host=values.get("DB_HOST", "127.0.0.1"), port=port, database=values["DB_NAME"],
    )


def get_database_url() -> "URL":
    load_dotenv(ENV_PATH)
    return database_url_from_values(os.environ)
