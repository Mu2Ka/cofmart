import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv
from sqlalchemy import URL, make_url

ENV_PATH = Path(__file__).resolve().parents[1] / '.env'


def database_url_from_values(values: Mapping[str, str]) -> URL:
    required = ('DB_NAME', 'DB_USER', 'DB_PASSWORD')
    missing = [key for key in required if not values.get(key, '').strip()]
    if missing:
        raise ValueError('Добавьте параметры PostgreSQL: ' + ', '.join(missing))
    try:
        port = int(values.get('DB_PORT', '5432'))
    except (ValueError, TypeError) as error:
        raise ValueError('DB_PORT должен быть числом от 1 до 65535.') from error
    if not 1 <= port <= 65535:
        raise ValueError('DB_PORT должен быть числом от 1 до 65535.')
    return URL.create('postgresql+asyncpg', username=values['DB_USER'], password=values['DB_PASSWORD'],
                      host=values.get('DB_HOST', '127.0.0.1'), port=port, database=values['DB_NAME'])


def get_database_url() -> URL:
    load_dotenv(ENV_PATH)
    value = os.getenv('DATABASE_URL')
    return make_url(value) if value else database_url_from_values(os.environ)


def get_bot_token() -> str:
    load_dotenv(ENV_PATH)
    token = os.getenv("API_BOT")
    if not token:
        raise RuntimeError("Добавьте API_BOT в файл .env")
    return token


@dataclass(frozen=True)
class Settings:
    database_url: str
    bot_token: str = ""
    mini_app_url: str = ""
    cors_origins: tuple[str, ...] = ()
    init_data_max_age_seconds: int = 3600


def get_settings() -> Settings:
    load_dotenv(ENV_PATH)
    database_url = get_database_url().render_as_string(hide_password=False)
    max_age = int(os.getenv("INIT_DATA_MAX_AGE_SECONDS", "3600"))
    if max_age <= 0:
        raise RuntimeError("INIT_DATA_MAX_AGE_SECONDS должен быть положительным")
    return Settings(
        database_url=database_url,
        bot_token=os.getenv("API_BOT", ""),
        mini_app_url=os.getenv("MINI_APP_URL", ""),
        cors_origins=tuple(x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()),
        init_data_max_age_seconds=max_age,
    )
