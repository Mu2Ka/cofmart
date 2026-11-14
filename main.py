import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.types import BotCommand

from app.config import get_bot_token
from app.handlers.student import router as student_router
from app.handlers.entry import router as entry_router
from app.handlers.staff import router as staff_router
from app.handlers.customer import router as customer_router
from app.services.roles import roles
from app.services.bans import bans
from app.middlewares import install_ban_middleware


async def main():
    roles.validate_configuration()
    bans.validate_configuration()
    dp = Dispatcher()
    install_ban_middleware(dp)
    # Рабочие карточки и пожелания к заказам показываем только в личном чате.
    dp.message.filter(F.chat.type == "private")
    dp.callback_query.filter(F.message.chat.type == "private")
    # Общие команды подключены до текстового обработчика комментариев.
    dp.include_routers(entry_router, staff_router, customer_router, student_router)

    async with Bot(token=get_bot_token()) as bot:
        for warning in roles.configuration_warnings(bot.id):
            logging.warning(warning)
        try:
            await configure_commands(bot)
        except (TelegramNetworkError, TelegramRetryAfter, TelegramServerError):
            logging.warning("Не удалось обновить меню команд. Продолжаем запуск бота.", exc_info=True)
        await dp.start_polling(bot, close_bot_session=False)


async def configure_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Выбрать роль"),
        BotCommand(command="student", description="Заказать кофе"),
        BotCommand(command="myorders", description="Мои заказы и статусы"),
        BotCommand(command="favorites", description="Избранные напитки"),
        BotCommand(command="repeat", description="Повторить прошлый заказ"),
        BotCommand(command="barista", description="Рабочая панель баристы"),
        BotCommand(command="admin", description="Панель администратора"),
        BotCommand(command="roles", description="Сменить роль"),
        BotCommand(command="myid", description="Узнать свой Telegram ID"),
        BotCommand(command="schedule", description="Расписание и тестовый режим"),
    ])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
