import os
from dataclasses import dataclass

from dotenv import load_dotenv


def get_bot_token() -> str:
    load_dotenv()
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
    load_dotenv()
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("Добавьте DATABASE_URL в файл .env")
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
