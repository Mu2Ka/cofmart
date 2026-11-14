import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.ordering.orders import Order
from app.ordering.persistent import roles
from app.ordering.bans import bans
from app.bot.ui import order_text
from app.bot.customer_keyboards import student_order_keyboard
from app.ordering import settings
from app.bot.message_cleanup import expire_message

logger = logging.getLogger(__name__)


async def send(bot: Bot, user_id: int, text: str, callback_data: str, label: str,
               keyboard: InlineKeyboardMarkup | None = None, *, store=None):
    if bans.is_blocked(user_id):
        return
    try:
        message = await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=keyboard or InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=callback_data)]]
        ))
        await expire_message(message, settings.NOTIFICATION_TTL_SECONDS, store=store)
    except TelegramAPIError:
        # Заблокированный бот или сбой уведомления не отменяет уже сохранённый заказ/статус.
        logger.warning("Не удалось уведомить пользователя %s", user_id, exc_info=True)


async def notify_staff(bot: Bot, order: Order, *, store=None):
    from app.ordering.persistent import PersistentService
    recipients = roles if store is None else PersistentService('roles', store)
    for user_id in await recipients.staff_for(order.draft.cafe_id):
        await send(bot, user_id, "<b>🔔 Новый заказ</b>\n\n" + order_text(order),
                   f"staff_order:{order.reference}", "Открыть заказ", store=store)


async def notify_student(bot: Bot, order: Order, *, store=None):
    hint = "\n\nМожно забирать напиток!" if order.status == "ready" else ""
    if order.status == "done":
        hint = "\n\nОцените заказ от 1 до 5 ⭐"
    await send(bot, order.draft.user_id, order_text(order) + hint,
               f"student_order:{order.reference}", "Мой заказ",
               student_order_keyboard(order) if order.status == "done" else None, store=store)
