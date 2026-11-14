import logging

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import SQLAlchemyError

from app.services.catalog import CatalogService
from app.services.errors import BusinessError
from app.services.orders import OrderService
from app.services.slots import SlotService

logger = logging.getLogger(__name__)


class ServicesMiddleware(BaseMiddleware):
    def __init__(self, sessions, mini_app_url=""):
        self.catalog = CatalogService(sessions)
        self.orders = OrderService(sessions)
        self.slots = SlotService(sessions)
        self.mini_app_url = mini_app_url

    async def __call__(self, handler, event, data):
        data.update(catalog=self.catalog, orders=self.orders, slots=self.slots, mini_app_url=self.mini_app_url)
        try:
            return await handler(event, data)
        except BusinessError as exc:
            message = exc.message
        except SQLAlchemyError:
            logger.exception("Database operation failed")
            message = "Не удалось сохранить данные. Повторите попытку немного позже."
        target = event.message if isinstance(event, CallbackQuery) else event
        if isinstance(target, Message):
            await target.answer(message)
