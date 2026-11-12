import os

from dotenv import load_dotenv


def get_bot_token() -> str:
    load_dotenv()
    token = os.getenv("API_BOT")
    if not token:
        raise RuntimeError("Добавьте API_BOT в файл .env")
    return token
