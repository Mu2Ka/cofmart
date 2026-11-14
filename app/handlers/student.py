from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app import settings
from app.catalog import CAFES, CATEGORIES, PRODUCTS, get_drink
from app.keyboards import (
    cafes_keyboard, categories_keyboard, drinks_keyboard, sizes_keyboard,
    milk_keyboard, breaks_keyboard, confirmation_keyboard, comment_keyboard, order_keyboard,
    button,
)
from app.schedule import available_breaks, closed_message, daily_breaks, local_now
from app.services.orders import MAX_COMMENT_LENGTH, Draft, OrderError, orders
from app.services.cafes import CafeError, cafes
from app.notifications import notify_staff
from app.ui import order_text, show
from app.customer_keyboards import student_order_keyboard

router = Router()
# Число частей callback_data: действие, кофейня, выбор (если есть), сессия.
MENU_ACTIONS = {"cafe": 3, "category": 4, "product": 4, "size": 4, "drink": 4, "pickup": 5}


def mode_label() -> str:
    return "По расписанию пар" if settings.FOLLOW_SCHEDULE else "🧪 Тестовый режим · в любое время"


async def check_session(callback: CallbackQuery, session: str) -> bool:
    if orders.valid_session(callback.from_user.id, session):
        return True
    await show(callback, "Эти кнопки устарели. Начните новый заказ.")
    return False


async def show_cafes(message: Message, user_id: int):
    session = orders.begin(user_id)
    now = local_now()
    available = available_breaks(now)
    if not available:
        await message.answer(closed_message(now), reply_markup=order_keyboard())
        return
    counts = {}
    for cafe_id in CAFES:
        summary = orders.slots(cafe_id, available[0].id, now)
        counts[cafe_id] = (summary.free if cafes.is_open(cafe_id) else 0, summary.limit)
    await message.answer(
        f"<b>☕ Кофе к перерыву</b>\n{mode_label()}\n{available[0].label}\n\nВыберите кофейню:",
        reply_markup=cafes_keyboard(session, counts), parse_mode="HTML",
    )


@router.message(Command("student"))
async def start(message: Message):
    await show_cafes(message, message.from_user.id)


@router.message(Command("schedule"))
async def schedule(message: Message):
    now = local_now()
    lines = [f"{mode_label()}\nРасписание (Новосибирск):"]
    for item in daily_breaks(now.date()):
        lines.append(f"{item.label}; приём {item.opens_at:%H:%M}–{item.closes_at:%H:%M} (до)")
    await message.answer("\n".join(lines), reply_markup=order_keyboard())


@router.callback_query(F.data == "new_order")
async def new_order(callback: CallbackQuery):
    await callback.answer()
    if isinstance(callback.message, Message):
        await show_cafes(callback.message, callback.from_user.id)


@router.callback_query(F.data.startswith("cancel_order:"))
async def cancel_order(callback: CallbackQuery):
    await callback.answer()
    if not await check_session(callback, callback.data.split(":", 1)[1]):
        return
    orders.cancel(callback.from_user.id)
    await show(callback, "Оформление отменено.")


def comment_line(draft: Draft) -> str:
    return f"💬 Комментарий: {escape(draft.comment) if draft.comment else 'без пожеланий'}\n"


async def show_draft(target: CallbackQuery | Message, draft: Draft, session: str):
    deadline = (
        "🧪 Без ограничений по расписанию."
        if draft.pickup.is_test
        else f"Подтвердите до <b>{draft.pickup.closes_at:%H:%M}</b> (Новосибирск)."
    )
    text = (
        f"<b>🧾 Проверьте заказ</b>\n\n"
        f"☕ {escape(draft.cafe_name)}\n{escape(draft.drink_name)}\n"
        f"{comment_line(draft)}"
        f"<b>Итого: {draft.price} ₽</b>\n\n{draft.pickup.label}\n{deadline}\n\n"
        f"Один слот зарезервирован за вами до <b>{draft.reserved_until:%H:%M:%S}</b>.\n"
        "Тестовый заказ. Оплата пока не подключена."
    )
    keyboard = confirmation_keyboard(draft.token, session)
    if isinstance(target, Message):
        await target.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await show(target, text, keyboard)


async def prepare_order(
    callback: CallbackQuery, cafe_id: str, sku: str, break_id: str, session: str,
):
    try:
        draft = orders.prepare(callback.from_user.id, cafe_id, sku, break_id, local_now())
    except OrderError as error:
        await show(callback, escape(str(error)))
        return
    await show_draft(callback, draft, session)


async def select_drink(callback: CallbackQuery, cafe_id: str, sku: str, session: str):
    if not settings.FOLLOW_SCHEDULE:
        await prepare_order(callback, cafe_id, sku, available_breaks(local_now())[0].id, session)
        return
    now = local_now()
    available = available_breaks(now)
    if not available:
        await show(callback, closed_message(now))
        return
    drink = get_drink(cafe_id, sku)
    if drink is None:
        await show(callback, "Напиток больше недоступен.")
        return
    counts = {}
    for item in available:
        summary = orders.slots(cafe_id, item.id, now)
        counts[item.id] = (summary.free, summary.limit)
    await show(
        callback,
        f"<b>{escape(drink.name)}</b>\n{drink.price} ₽\n\nВыберите перерыв:",
        breaks_keyboard(cafe_id, sku, available, session, counts),
    )


@router.callback_query(F.data.regexp(r"^(" + "|".join(MENU_ACTIONS) + r"):"))
async def menu_callback(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    action = parts[0]
    if len(parts) != MENU_ACTIONS.get(action):
        await show(callback, "Эти кнопки устарели. Начните новый заказ.")
        return
    if not await check_session(callback, parts[-1]):
        return
    cafe_id, session = parts[1], parts[-1]
    if cafe_id not in CAFES:
        await show(callback, "Кофейня недоступна.")
        return
    if not cafes.is_open(cafe_id):
        await show(callback, "Кофейня временно остановила приём. Выберите другую кофейню.")
        return
    now = local_now()
    if not available_breaks(now):
        await show(callback, closed_message(now))
        return
    # Нельзя подтвердить прежний напиток, когда пользователь уже вернулся в меню.
    orders.discard_draft(callback.from_user.id)
    cafe_name = escape(CAFES[cafe_id])
    if action == "cafe":
        pickup = available_breaks(now)[0]
        summary = orders.slots(cafe_id, pickup.id, now)
        if summary.free == 0:
            await show(callback, f"<b>{cafe_name}</b>\nНа этот перерыв свободно 0/{summary.limit} слотов. "
                       "Выберите другую кофейню или обновите слоты.", cafes_keyboard(session, {
                           cid: (orders.slots(cid, pickup.id, now).free if cafes.is_open(cid) else 0,
                                 orders.slots(cid, pickup.id, now).limit) for cid in CAFES
                       }))
            return
        await show(callback, f"<b>☕ {cafe_name}</b>\nСвободно {summary.free}/{summary.limit} слотов.\n\nЧто приготовим? Выберите раздел:",
                   categories_keyboard(cafe_id, session))
    elif action == "category":
        category = parts[2]
        if category not in CATEGORIES:
            await show(callback, "Раздел меню больше недоступен.")
            return
        has_drinks = any(product.category == category and cafes.is_available(cafe_id, product_id)
                         for product_id, product in PRODUCTS[cafe_id].items())
        prompt = "Выберите напиток:" if has_drinks else "В этом разделе пока нет доступных напитков."
        await show(callback, f"<b>{cafe_name} · {CATEGORIES[category]}</b>\n\n{prompt}",
                   drinks_keyboard(cafe_id, category, session))
    elif action == "product":
        product_id = parts[2]
        product = PRODUCTS[cafe_id].get(product_id)
        if product is None:
            await show(callback, "Напиток больше недоступен.")
            return
        await show(callback, f"<b>{escape(product.name)}</b>\n{cafe_name}\n\nВыберите объём:",
                   sizes_keyboard(cafe_id, product_id, session))
    elif action in {"size", "drink"}:
        sku = parts[2]
        drink = get_drink(cafe_id, sku)
        if drink is None:
            await show(callback, "Напиток больше недоступен.")
            return
        try:
            cafes.require_orderable(cafe_id, sku)
        except CafeError as error:
            await show(callback, escape(str(error)))
            return
        if action == "size" and drink.product.alternative_milk and not sku.endswith("a"):
            await show(callback, f"<b>{escape(drink.name)}</b>\n\nВыберите молоко:",
                       milk_keyboard(cafe_id, sku, session))
        else:
            await select_drink(callback, cafe_id, sku, session)
    elif action == "pickup":
        await prepare_order(callback, cafe_id, parts[2], parts[3], session)


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_callback(callback: CallbackQuery):
    await callback.answer()
    token = callback.data.split(":", 1)[1]
    already_confirmed = token in orders.confirmed
    try:
        order = orders.confirm(callback.from_user.id, token, local_now())
    except OrderError as error:
        user_id = callback.from_user.id
        waiting_token = orders.waiting_comments.get(user_id)
        keyboard = (
            comment_keyboard(waiting_token, orders.sessions[user_id])
            if waiting_token else order_keyboard()
        )
        await show(callback, escape(str(error)), keyboard)
        return
    if not already_confirmed:
        await notify_staff(callback.bot, order)
    await show(
        callback,
        order_text(order) + "\n\nСтатусы можно проверить в разделе «Мои заказы». Оплата пока не подключена.",
        student_order_keyboard(order),
    )


async def show_my_orders(target: Message | CallbackQuery, user_id: int):
    recent = orders.for_user(user_id)[:5]
    lines = ["<b>📋 Мои последние заказы</b>"] + [order_text(order) for order in recent]
    if not recent:
        lines.append("Заказов пока нет.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [button(f"Открыть №{order.number}", f"student_order:{order.reference}")] for order in recent
    ] + order_keyboard().inline_keyboard)
    text = "\n\n".join(lines)
    if isinstance(target, Message):
        await target.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await show(target, text, keyboard)


@router.message(Command("myorders"))
async def my_orders_command(message: Message):
    await show_my_orders(message, message.from_user.id)


@router.callback_query(F.data == "my_orders")
async def my_orders_callback(callback: CallbackQuery):
    await callback.answer()
    await show_my_orders(callback, callback.from_user.id)


@router.callback_query(F.data.startswith("student_order:"))
async def student_order(callback: CallbackQuery):
    await callback.answer()
    try:
        order = orders.own_order(callback.from_user.id, callback.data.split(":", 1)[1])
    except (OrderError, ValueError) as error:
        await show(callback, escape(str(error)))
        return
    await show(callback, order_text(order), student_order_keyboard(order))


@router.callback_query(F.data.startswith("comment:"))
async def add_comment(callback: CallbackQuery):
    await callback.answer()
    try:
        draft = orders.start_comment(callback.from_user.id, callback.data.split(":", 1)[1], local_now())
    except OrderError as error:
        await show(callback, escape(str(error)))
        return
    await show(
        callback,
        f"<b>💬 Пожелания к напитку</b>\n\nНапишите сообщение, например: «со льдом» или «без сахара».\n"
        f"До {MAX_COMMENT_LENGTH} символов.\n\n{comment_line(draft)}",
        comment_keyboard(draft.token, orders.sessions[draft.user_id]),
    )


@router.callback_query(F.data.startswith("skip_comment:"))
async def skip_comment(callback: CallbackQuery):
    await callback.answer()
    try:
        draft = orders.save_comment(callback.from_user.id, callback.data.split(":", 1)[1], None, local_now())
    except OrderError as error:
        await show(callback, escape(str(error)))
        return
    await show_draft(callback, draft, orders.sessions[draft.user_id])


@router.message(F.text & ~F.text.startswith("/"))
async def receive_comment(message: Message):
    user_id = message.from_user.id
    token = orders.waiting_comments.get(user_id)
    if token is None:
        await message.answer("Для пожеланий откройте заказ и нажмите «Добавить / изменить комментарий».")
        return
    try:
        draft = orders.save_comment(user_id, token, message.text, local_now())
    except OrderError as error:
        await message.answer(str(error))
        return
    await show_draft(message, draft, orders.sessions[user_id])


@router.message()
async def unsupported_comment(message: Message):
    if message.from_user and message.from_user.id in orders.waiting_comments:
        await message.answer("Отправьте пожелание обычным текстом, например: «со льдом».")
