from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import CallbackQuery, Message
import logging
from sqlalchemy.exc import SQLAlchemyError

from app.services.bans import BLOCK_MESSAGE, BanService, bans
from app.services.orders import orders
from app.message_cleanup import answer_notice


class BanMiddleware(BaseMiddleware):
    def __init__(self, service: BanService = bans, cancel_order=None):
        self.service = service
        self.cancel_order = cancel_order

    async def __call__(self, handler, event, data):
        # В callback автор нажатия — event.from_user, а не автор сообщения с кнопкой.
        user = getattr(event, "from_user", None)
        if user is None or not self.service.is_blocked(user.id, user.username):
            return await handler(event, data)
        if self.cancel_order is None:
            orders.cancel(user.id)
        else:
            try:
                await self.cancel_order(user.id)
            except (SQLAlchemyError, OSError, TimeoutError):
                logging.warning("Не удалось освободить резерв недоступного аккаунта.")
        if isinstance(event, CallbackQuery):
            await event.answer(BLOCK_MESSAGE, show_alert=True)
        elif isinstance(event, Message) and event.chat.type == "private":
            await event.answer(BLOCK_MESSAGE)
        # Обработчики команд, ролей, заказов и комментариев не вызываются.
        return None


def install_ban_middleware(dispatcher: Dispatcher, service: BanService = bans, cancel_order=None):
    middleware = BanMiddleware(service, cancel_order)
    dispatcher.message.outer_middleware(middleware)
    dispatcher.callback_query.outer_middleware(middleware)


class DatabaseMiddleware(BaseMiddleware):
    """Регистрируем автора действия и обновляем его имя/username до обработчика."""

    async def __call__(self, handler, event, data):
        chat = event.message.chat if isinstance(event, CallbackQuery) and event.message else getattr(event, "chat", None)
        user = getattr(event, "from_user", None)
        if user is None or chat is None or chat.type != "private":
            return None
        from app.services.persistent import get_store
        try:
            await get_store().register(user)
            return await handler(event, data)
        except (SQLAlchemyError, OSError, TimeoutError):
            logging.error("Ошибка PostgreSQL при обработке действия; проверьте подключение к базе.")
            text = "Не удалось обратиться к базе данных. Повторите действие чуть позже."
            if isinstance(event, CallbackQuery):
                await answer_notice(event.message, text)
            else:
                await answer_notice(event, text)
            return None


def install_database_middleware(dispatcher: Dispatcher):
    middleware = DatabaseMiddleware()
    dispatcher.message.outer_middleware(middleware)
    dispatcher.callback_query.outer_middleware(middleware)
