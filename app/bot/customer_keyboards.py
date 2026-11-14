from aiogram.types import InlineKeyboardMarkup

from app.ordering.catalog import get_drink
from app.bot.order_keyboards import button, order_keyboard
from app.ordering.schedule import Break
from app.ordering.customer import Favorite
from app.ordering.orders import Order

FAVORITES_PAGE_SIZE = 5


def student_order_keyboard(order: Order) -> InlineKeyboardMarkup:
    rows = [
        [button("↻ Повторить этот заказ", f"repeat:{order.reference}")],
        [button("⭐ В избранное", f"favorite_add:{order.reference}")],
    ]
    if order.status == "done":
        rows.append([button(f"{'✓ ' if order.rating == score else ''}{score} ⭐",
                            f"rate:{order.reference}:{score}") for score in range(1, 6)])
    rows.append([button("↻ Обновить статус", f"student_order:{order.reference}")])
    return InlineKeyboardMarkup(inline_keyboard=rows + order_keyboard().inline_keyboard)


def favorites_keyboard(items: list[Favorite], page: int) -> InlineKeyboardMarkup:
    rows = [[button(f"{favorite.cafe_name} · {favorite.drink_name}", f"favorite:{favorite.key}")]
            for favorite in items[page * FAVORITES_PAGE_SIZE:(page + 1) * FAVORITES_PAGE_SIZE]]
    navigation = []
    if page:
        navigation.append(button("←", f"favorites:{page - 1}"))
    if (page + 1) * FAVORITES_PAGE_SIZE < len(items):
        navigation.append(button("→", f"favorites:{page + 1}"))
    if navigation:
        rows.append(navigation)
    return InlineKeyboardMarkup(inline_keyboard=rows + order_keyboard().inline_keyboard)


def favorite_keyboard(favorite: Favorite) -> InlineKeyboardMarkup:
    rows = []
    if get_drink(favorite.cafe_id, favorite.drink_id):
        rows.append([button("☕ Заказать", f"favorite_order:{favorite.key}")])
    rows += [[button("Удалить из избранного", f"favorite_remove:{favorite.key}")],
             [button("← Избранное", "favorites:0")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shortcut_breaks_keyboard(kind: str, key: str, session: str,
                              pickups: list[tuple[Break, int, int]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(f"{pickup.label} · свободно {free}/{limit}", f"quick:{kind}:{key}:{pickup.id}:{session}")]
        for pickup, free, limit in pickups
    ] + [[button("✕ Отменить", f"cancel_order:{session}")]])
