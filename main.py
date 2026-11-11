import asyncio

from aiogram import Bot, Dispatcher

from app.config import get_bot_token
from app.handlers.student import router as student_router


async def main():
    dp = Dispatcher()
    dp.include_router(student_router)

    bot = Bot(token=get_bot_token())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
