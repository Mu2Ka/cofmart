import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation

from app.bot.handlers import orders, student
from app.bot.middlewares import ServicesMiddleware
from app.config import get_bot_token, get_settings
from app.db.session import Database


async def main():
    settings = get_settings()
    db = Database(settings.database_url)
    dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    services = ServicesMiddleware(db.sessions, settings.mini_app_url)
    dp.message.middleware(services)
    dp.callback_query.middleware(services)
    dp.include_routers(student.router, orders.router)
    try:
        async with Bot(token=get_bot_token()) as bot:
            await dp.start_polling(bot)
    finally:
        await dp.storage.close()
        await dp.fsm.events_isolation.close()
        await db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
