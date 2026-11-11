import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiohttp import web

from app.config import load_settings
from app.handlers.student import router as student_router
from app.web import create_web_app


async def main():
    settings = load_settings()
    runner = web.AppRunner(create_web_app())
    dp = Dispatcher()
    dp.include_router(student_router)

    bot = Bot(token=settings.bot_token)
    try:
        await runner.setup()
        await web.TCPSite(runner, settings.web_host, settings.web_port).start()
        logging.info("Mini App: http://%s:%s", settings.web_host, settings.web_port)
        await dp.start_polling(bot, settings=settings, close_bot_session=False)
    finally:
        await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
