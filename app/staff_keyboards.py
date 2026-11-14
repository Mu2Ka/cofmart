from aiogram.types import InlineKeyboardMarkup

from app.catalog import CAFES, PRODUCTS
from app.keyboards import button
from app.services.cafes import cafes
from app.services.orders import Order, STATUSES, TRANSITIONS
from app.services.orders import MAX_SLOT_LIMIT, SlotSummary
from app.schedule import Break
from app.services.roles import roles

PAGE_SIZE = 6


def roles_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [[button("🎓 Студент · заказать кофе", "role:student")]]
    if roles.cafes_for(user_id):
        rows.append([button("☕ Бариста · рабочая панель", "role:barista")])
    if roles.is_admin(user_id):
        rows.append([button("⚙ Администратор", "role:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def staff_home_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(CAFES[cafe_id], f"staff_cafe:{cafe_id}")]
        for cafe_id in sorted(roles.cafes_for(user_id))
    ] + [[button("← Выбор роли", "roles")]])


def cafe_keyboard(cafe_id: str) -> InlineKeyboardMarkup:
    opened = cafes.is_open(cafe_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("📋 Активные заказы", f"staff_queue:{cafe_id}:active:0")],
        [button("🎟 Слоты на перемены", f"staff_slots:{cafe_id}")],
        [button("✅ Выданные", f"staff_queue:{cafe_id}:done:0"),
         button("Отменённые", f"staff_queue:{cafe_id}:cancelled:0")],
        [button("🥤 Наличие напитков", f"staff_menu:{cafe_id}:0")],
        [button("⏸ Остановить приём" if opened else "▶ Возобновить приём",
                f"staff_accept:{cafe_id}:{int(not opened)}")],
        [button("← Кофейни", "role:barista")],
    ])


def queue_keyboard(cafe_id: str, status: str, page: int, orders: list[Order]) -> InlineKeyboardMarkup:
    rows = [[button(f"№{order.number} · {STATUSES[order.status]} · {order.draft.price} ₽",
                    f"staff_order:{order.reference}")]
            for order in orders[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    rows += [[button("Новые", f"staff_queue:{cafe_id}:new:0"),
              button("Готовятся", f"staff_queue:{cafe_id}:preparing:0"),
              button("Готовы", f"staff_queue:{cafe_id}:ready:0")]]
    navigation = []
    if page:
        navigation.append(button("←", f"staff_queue:{cafe_id}:{status}:{page - 1}"))
    if (page + 1) * PAGE_SIZE < len(orders):
        navigation.append(button("→", f"staff_queue:{cafe_id}:{status}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows += [[button("↻ Обновить", f"staff_queue:{cafe_id}:{status}:{page}")],
             [button("← Кофейня", f"staff_cafe:{cafe_id}")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def staff_order_keyboard(order: Order, actor_id: int) -> InlineKeyboardMarkup:
    labels = {"preparing": "☕ Взять в работу", "ready": "✅ Готов", "done": "📦 Выдан", "cancelled": "✕ Отменить заказ"}
    allowed = order.barista_id in {None, actor_id} or roles.is_admin(actor_id)
    rows = [[button(labels[status], f"staff_status:{order.reference}:{status}:{order.revision}")]
            for status in labels if allowed and status in TRANSITIONS[order.status]]
    rows += [[button("↻ Обновить", f"staff_order:{order.reference}")],
             [button("← Очередь", f"staff_queue:{order.draft.cafe_id}:active:0")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def availability_keyboard(cafe_id: str, page: int) -> InlineKeyboardMarkup:
    products = list(PRODUCTS[cafe_id].items())
    rows = [[button(f"{'✅' if cafes.is_available(cafe_id, product_id) else '⛔'} {product.name}",
                    f"staff_item:{cafe_id}:{product_id}:{int(not cafes.is_available(cafe_id, product_id))}:{page}")]
            for product_id, product in products[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    navigation = []
    if page:
        navigation.append(button("←", f"staff_menu:{cafe_id}:{page - 1}"))
    if (page + 1) * PAGE_SIZE < len(products):
        navigation.append(button("→", f"staff_menu:{cafe_id}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([button("← Кофейня", f"staff_cafe:{cafe_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def slot_breaks_keyboard(cafe_id: str, items: list[tuple[Break, SlotSummary]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button((f"{pickup.starts_at:%d.%m %H:%M}" if not pickup.is_test else f"Тест {pickup.starts_at:%d.%m}")
                + f" · {summary.free}/{summary.limit} свободно", f"staff_slot:{cafe_id}:{pickup.id}")]
        for pickup, summary in items
    ] + [[button("↻ Обновить", f"staff_slots:{cafe_id}")],
         [button("← Кофейня", f"staff_cafe:{cafe_id}")]])


def slot_limit_keyboard(cafe_id: str, pickup: Break, summary: SlotSummary) -> InlineKeyboardMarkup:
    values = sorted({0, 5, 10, 15, 20, max(0, summary.limit - 1), min(MAX_SLOT_LIMIT, summary.limit + 1)})
    buttons = [button(str(value), f"staff_setslots:{cafe_id}:{pickup.id}:{value}:{summary.revision}")
               for value in values]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[index:index + 4] for index in range(0, len(buttons), 4)] + [
        [button("✎ Ввести число", f"staff_editslots:{cafe_id}:{pickup.id}")],
        [button("↻ Обновить", f"staff_slot:{cafe_id}:{pickup.id}")],
        [button("← Перемены", f"staff_slots:{cafe_id}")],
    ])
