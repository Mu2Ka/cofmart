from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.catalog import CAFES, CATEGORIES, PRODUCTS, get_drink, size_label
from app.schedule import Break
from app.services.persistent import cafes


def button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


async def cafes_keyboard(session: str, counts: dict[str, tuple[int, int]] | None = None) -> InlineKeyboardMarkup:
    cafes_view = await cafes.view()
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(f"{'☕' if cafes_view.is_open(cafe_id) else '⏸'} {name}"
                + (f" · свободно {counts[cafe_id][0]}/{counts[cafe_id][1]}" if counts else ""),
                f"cafe:{cafe_id}:{session}")]
        for cafe_id, name in CAFES.items()
    ] + [[button("↻ Обновить слоты", "new_order")],
         [button("⭐ Избранное", "favorites:0"), button("↻ Повторить", "repeat_last")]])


def categories_keyboard(cafe_id: str, session: str) -> InlineKeyboardMarkup:
    used = {product.category for product in PRODUCTS[cafe_id].values()}
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(name, f"category:{cafe_id}:{key}:{session}")]
        for key, name in CATEGORIES.items() if key in used
    ] + [[button("← Кофейни", "new_order")]])


async def drinks_keyboard(cafe_id: str, category: str, session: str) -> InlineKeyboardMarkup:
    cafes_view = await cafes.view()
    rows = []
    for product_id, product in PRODUCTS[cafe_id].items():
        if product.category == category and cafes_view.is_available(cafe_id, product_id):
            prefix = "от " if len(product.sizes) > 1 else ""
            rows.append([button(f"{product.name} · {prefix}{min(product.sizes.values())} ₽",
                                f"product:{cafe_id}:{product_id}:{session}")])
    rows.append([button("← Разделы меню", f"cafe:{cafe_id}:{session}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sizes_keyboard(cafe_id: str, product_id: str, session: str) -> InlineKeyboardMarkup:
    product = PRODUCTS[cafe_id][product_id]
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(f"{size_label(size)} · {price} ₽", f"size:{cafe_id}:{product_id}_{size}:{session}")]
        for size, price in product.sizes.items()
    ] + [[button("← Напитки", f"category:{cafe_id}:{product.category}:{session}")]])


def milk_keyboard(cafe_id: str, sku: str, session: str) -> InlineKeyboardMarkup:
    product_id = sku.split("_", 1)[0]
    drink = get_drink(cafe_id, sku)
    alternative = get_drink(cafe_id, sku + "a")
    if drink is None or alternative is None:
        raise ValueError("У этого напитка нет выбора молока")
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(f"Обычное · {drink.price} ₽", f"drink:{cafe_id}:{sku}:{session}")],
        [button(f"Альтернативное +70 ₽ · {alternative.price} ₽",
                f"drink:{cafe_id}:{sku}a:{session}")],
        [button("← Объём", f"product:{cafe_id}:{product_id}:{session}")],
    ])


def order_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("☕ Новый заказ", "new_order")],
        [button("↻ Повторить прошлый заказ", "repeat_last")],
        [button("⭐ Избранные напитки", "favorites:0")],
        [button("📋 Мои заказы", "my_orders")],
        [button("← Выбор роли", "roles")],
    ])


def breaks_keyboard(cafe_id: str, drink_id: str, breaks: list[Break], session: str,
                    counts: dict[str, tuple[int, int]] | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(item.label + (f" · {counts[item.id][0]}/{counts[item.id][1]} свободно" if counts else ""),
                f"pickup:{cafe_id}:{drink_id}:{item.id}:{session}")]
        for item in breaks
    ] + [[button("✕ Отменить", f"cancel_order:{session}")]])


def confirmation_keyboard(token: str, session: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("✎ Добавить / изменить комментарий", f"comment:{token}")],
        [button("⭐ В избранное", f"favorite_draft:{token}")],
        [button("✓ Подтвердить тестовый заказ", f"confirm:{token}")],
        [button("✕ Отменить", f"cancel_order:{session}")],
    ])


def comment_keyboard(token: str, session: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("Оставить как есть", f"skip_comment:{token}")],
        [button("✕ Отменить заказ", f"cancel_order:{session}")],
    ])
