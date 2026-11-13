import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.orders import Order
from app.services.roles import roles
from app.ui import order_text

logger = logging.getLogger(__name__)


async def send(bot: Bot, user_id: int, text: str, callback_data: str, label: str):
    try:
        await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=callback_data)]]
        ))
    except TelegramAPIError:
        # Заблокированный бот или сбой уведомления не отменяет уже сохранённый заказ/статус.
        logger.warning("Не удалось уведомить пользователя %s", user_id, exc_info=True)


async def notify_staff(bot: Bot, order: Order):
    for user_id in roles.staff_for(order.draft.cafe_id):
        await send(bot, user_id, "<b>🔔 Новый заказ</b>\n\n" + order_text(order),
                   f"staff_order:{order.number}", "Открыть заказ")


async def notify_student(bot: Bot, order: Order):
    hint = "\n\nМожно забирать напиток!" if order.status == "ready" else ""
    await send(bot, order.draft.user_id, order_text(order) + hint,
               f"student_order:{order.number}", "Мой заказ")
