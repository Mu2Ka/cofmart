import asyncio

import logging

from aiogram import Bot, Dispatcher, F
from aiogram.types import BotCommand

from app.config import get_bot_token
from app.handlers.student import router as student_router
from app.handlers.entry import router as entry_router
from app.handlers.staff import router as staff_router


async def main():
    dp = Dispatcher()
    # Рабочие карточки и пожелания к заказам показываем только в личном чате.
    dp.message.filter(F.chat.type == "private")
    dp.callback_query.filter(F.message.chat.type == "private")
    # Общие команды подключены до текстового обработчика комментариев.
    dp.include_routers(entry_router, staff_router, student_router)

    bot = Bot(token=get_bot_token())
    await bot.set_my_commands([
        BotCommand(command="start", description="Выбрать роль"),
        BotCommand(command="student", description="Заказать кофе"),
        BotCommand(command="myorders", description="Мои заказы и статусы"),
        BotCommand(command="barista", description="Рабочая панель баристы"),
        BotCommand(command="admin", description="Панель администратора"),
        BotCommand(command="roles", description="Сменить роль"),
        BotCommand(command="myid", description="Узнать свой Telegram ID"),
        BotCommand(command="schedule", description="Расписание и тестовый режим"),
    ])
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
