from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.catalog import CAFES, MENU, PRICES


def cafes_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"cafe:{cafe_id}")]
            for cafe_id, name in CAFES.items()
        ]
    )


def drinks_keyboard(cafe_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{drink_name} {PRICES[cafe_id][drink_id]} ₽",
                    callback_data=f"drink:{cafe_id}:{drink_id}",
                )
            ]
            for drink_id, drink_name in MENU[cafe_id].items()
        ]
    )
