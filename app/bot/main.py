import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.types import BotCommand
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation

from app.config import get_bot_token
from app.process_lock import AlreadyRunningError, bot_lock


async def main():
    token = get_bot_token()
    with bot_lock(token):
        await run_bot(token)


async def configure_commands(bot):
    commands = [
        ('start','Выбрать роль'), ('student','Заказать кофе'), ('myorders','Мои заказы и статусы'),
        ('favorites','Избранные напитки'), ('repeat','Повторить прошлый заказ'),
        ('barista','Рабочая панель баристы'), ('admin','Панель администратора'),
        ('roles','Сменить роль'), ('myid','Узнать свой Telegram ID'), ('schedule','Расписание и режим'),
    ]
    await bot.set_my_commands([BotCommand(command=name,description=label) for name,label in commands])


async def run_bot(token):
    from app.bot.flows import entry, student, staff, customer
    from app.bot.full_middlewares import install_ban_middleware, install_database_middleware
    from app.bot.message_cleanup import message_cleanup_worker
    from app.ordering.persistent import orders as full_orders
    from app.ordering.roles import roles
    from app.ordering.bans import bans
    from app.db.ordering_connection import close
    from app.db.ordering_connection import database
    from app.db.readiness import ensure_schema
    from app.ordering.seed import seed
    roles.validate_configuration()
    bans.validate_configuration()
    dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    install_ban_middleware(dp, cancel_order=full_orders.cancel)
    install_database_middleware(dp)
    dp.message.filter(F.chat.type == 'private')
    dp.callback_query.filter(F.message.chat.type == 'private')
    dp.include_routers(entry.router, staff.router, customer.router, student.router)
    try:
        await ensure_schema(database())
        await seed(database().sessions)
        async with Bot(token=token) as bot, message_cleanup_worker(bot):
            for warning in roles.configuration_warnings(bot.id):
                logging.warning(warning)
            try:
                await configure_commands(bot)
            except (TelegramNetworkError, TelegramRetryAfter, TelegramServerError):
                logging.warning('Не удалось обновить меню команд; продолжаем запуск.')
            await dp.start_polling(bot, close_bot_session=False)
    finally:
        await dp.storage.close()
        await dp.fsm.events_isolation.close()
        await close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except AlreadyRunningError as exc:
        raise SystemExit(str(exc)) from None
