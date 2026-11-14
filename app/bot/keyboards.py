from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.bot.formatting import local_time, money
from app.services.dto import CafeData, MenuData, SlotData


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, callback_data=data) for text, data in row
    ] for row in rows])


def cafes_keyboard(cafes: list[CafeData], mini_app_url: str = ""):
    result = keyboard([[(x.name, f"cafe:{x.id}")] for x in cafes] + [[("Мои заказы", "history")]])
    if mini_app_url:
        result.inline_keyboard.append([InlineKeyboardButton(text="Открыть Mini App", web_app=WebAppInfo(url=mini_app_url))])
    return result


def drinks_keyboard(cafe_id: int, items: list[MenuData]):
    return keyboard([[(f"{x.name} {money(x.price_minor)}", f"drink:{cafe_id}:{x.legacy_code}")] for x in items]
                    + [[("Корзина", "cart"), ("Кофейни", "cafes")]])


def cart_keyboard(cafe_id: int):
    return keyboard([[("Добавить напиток", f"cafe:{cafe_id}")], [("Выбрать время", "checkout")],
                     [("Очистить корзину", "clear_cart"), ("Кофейни", "cafes")]])


def slots_keyboard(slots: list[SlotData], zone: str):
    return keyboard([[(f"{local_time(x.starts_at, zone)} · мест: {x.available}", f"slot:{x.id}")] for x in slots]
                    + [[("В корзину", "cart")]])
