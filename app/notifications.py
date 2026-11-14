import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.orders import Order
from app.services.persistent import roles
from app.services.bans import bans
from app.ui import order_text
from app.customer_keyboards import student_order_keyboard
from app import settings
from app.message_cleanup import expire_message

logger = logging.getLogger(__name__)


async def send(bot: Bot, user_id: int, text: str, callback_data: str, label: str,
               keyboard: InlineKeyboardMarkup | None = None):
    if bans.is_blocked(user_id):
        return
    try:
        message = await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=keyboard or InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=callback_data)]]
        ))
        await expire_message(message, settings.NOTIFICATION_TTL_SECONDS)
    except TelegramAPIError:
        # Заблокированный бот или сбой уведомления не отменяет уже сохранённый заказ/статус.
        logger.warning("Не удалось уведомить пользователя %s", user_id, exc_info=True)


async def notify_staff(bot: Bot, order: Order):
    for user_id in await roles.staff_for(order.draft.cafe_id):
        await send(bot, user_id, "<b>🔔 Новый заказ</b>\n\n" + order_text(order),
                   f"staff_order:{order.reference}", "Открыть заказ")


async def notify_student(bot: Bot, order: Order):
    hint = "\n\nМожно забирать напиток!" if order.status == "ready" else ""
    if order.status == "done":
        hint = "\n\nОцените заказ от 1 до 5 ⭐"
    await send(bot, order.draft.user_id, order_text(order) + hint,
               f"student_order:{order.reference}", "Мой заказ",
               student_order_keyboard(order) if order.status == "done" else None)
