from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.catalog import CAFES, MENU, PRICES
from app.schedule import Break


def cafes_keyboard(session: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"cafe:{cafe_id}:{session}")]
            for cafe_id, name in CAFES.items()
        ]
    )


def drinks_keyboard(cafe_id: str, session: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{drink_name} {PRICES[cafe_id][drink_id]} ₽",
                    callback_data=f"drink:{cafe_id}:{drink_id}:{session}",
                )
            ]
            for drink_id, drink_name in MENU[cafe_id].items()
        ]
    )


def order_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Новый заказ", callback_data="new_order")],
    ])


def breaks_keyboard(cafe_id: str, drink_id: str, breaks: list[Break], session: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=item.label,
                              callback_data=f"pickup:{cafe_id}:{drink_id}:{item.id}:{session}")]
        for item in breaks
    ] + [[InlineKeyboardButton(text="Отменить", callback_data=f"cancel_order:{session}")]])


def confirmation_keyboard(token: str, session: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подтвердить тестовый заказ", callback_data=f"confirm:{token}")],
        [InlineKeyboardButton(text="Отменить", callback_data=f"cancel_order:{session}")],
    ])
