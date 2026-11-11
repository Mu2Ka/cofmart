from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def order_keyboard(mini_app_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Заказать кофе", web_app=WebAppInfo(url=mini_app_url))]
        ]
    )
