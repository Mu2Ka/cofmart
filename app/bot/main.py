import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation

from app.bot.handlers import orders, student
from app.bot.middlewares import ServicesMiddleware
from app.config import get_bot_token, get_settings
from app.db.session import Database
from app.process_lock import AlreadyRunningError, bot_lock


async def main():
    token = get_bot_token()
    with bot_lock(token):
        await run_bot(token)


async def run_bot(token):
    settings = get_settings()
    db = Database(settings.database_url)
    dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    def mini_app_url():
        if os.getenv('COFMART_LOCAL_RUNTIME') == '1':
            path = Path(__file__).resolve().parents[2] / '.local' / 'mini-app-url.txt'
            if path.exists():
                return path.read_text(encoding='utf-8').strip()
        return settings.mini_app_url

    services = ServicesMiddleware(db.sessions, mini_app_url)
    dp.message.middleware(services)
    dp.callback_query.middleware(services)
    dp.include_routers(student.router, orders.router)
    try:
        async with Bot(token=token) as bot:
            await dp.start_polling(bot)
    finally:
        await dp.storage.close()
        await dp.fsm.events_isolation.close()
        await db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except AlreadyRunningError as exc:
        raise SystemExit(str(exc)) from None
