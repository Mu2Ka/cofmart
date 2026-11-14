from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import CallbackQuery, Message

from app.services.bans import BLOCK_MESSAGE, BanService, bans
from app.services.orders import orders


class BanMiddleware(BaseMiddleware):
    def __init__(self, service: BanService = bans):
        self.service = service

    async def __call__(self, handler, event, data):
        # В callback автор нажатия — event.from_user, а не автор сообщения с кнопкой.
        user = getattr(event, "from_user", None)
        if user is None or not self.service.is_blocked(user.id, user.username):
            return await handler(event, data)
        orders.cancel(user.id)
        if isinstance(event, CallbackQuery):
            await event.answer(BLOCK_MESSAGE, show_alert=True)
        elif isinstance(event, Message) and event.chat.type == "private":
            await event.answer(BLOCK_MESSAGE)
        # Обработчики команд, ролей, заказов и комментариев не вызываются.
        return None


def install_ban_middleware(dispatcher: Dispatcher, service: BanService = bans):
    middleware = BanMiddleware(service)
    dispatcher.message.outer_middleware(middleware)
    dispatcher.callback_query.outer_middleware(middleware)
