from html import escape

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.bot.order_keyboards import order_keyboard
from app.ordering.orders import Order, STATUSES
from app.ordering import settings
from app.bot.message_cleanup import expire_message, keep_message


async def show(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None = None,
               *, temporary: bool = False):
    if not isinstance(callback.message, Message):
        return
    # Если worker уже удаляет карточку, дождёмся его и восстановим экран новым сообщением.
    await keep_message(callback.message)
    result = callback.message
    try:
        await callback.message.edit_text(text, reply_markup=keyboard or order_keyboard(), parse_mode="HTML")
    except TelegramBadRequest as error:
        reason = str(error).lower()
        if "message is not modified" in reason:
            pass
        elif "message to edit not found" in reason or "message can't be edited" in reason:
            # Карточку могли удалить или она стала слишком старой для редактирования.
            result = await callback.message.answer(text, reply_markup=keyboard or order_keyboard(), parse_mode="HTML")
        else:
            raise
    if temporary:
        await expire_message(result, settings.SERVICE_MESSAGE_TTL_SECONDS)


async def show_notice(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None = None):
    await show(callback, text, keyboard, temporary=True)


def order_text(order: Order, staff: bool = False) -> str:
    draft = order.draft
    text = (
        f"<b>Заказ №{order.number} · {STATUSES[order.status]}</b>\n\n"
        f"☕ {escape(draft.cafe_name)}\n{escape(draft.drink_name)}\n"
        f"💬 {escape(draft.comment) if draft.comment else 'Без пожеланий'}\n"
        f"<b>{draft.price} ₽</b>\n{draft.pickup.label}"
    )
    if staff:
        text += f"\nСоздан: {order.created_at:%d.%m %H:%M}" if order.created_at else ""
        text += f"\nБариста: {order.barista_id}" if order.barista_id else "\nЕщё не взят в работу"
    if order.rating is not None:
        text += f"\n⭐ Оценка: {order.rating}/5"
    return text
