import os
from pathlib import Path

from dotenv import load_dotenv


def get_bot_token() -> str:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    token = os.getenv("API_BOT")
    if not token:
        raise RuntimeError("Добавьте API_BOT в файл .env")
    return token
