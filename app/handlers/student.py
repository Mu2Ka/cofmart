from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.catalog import CAFES, MENU, PRICES
from app.keyboards import (
    cafes_keyboard, drinks_keyboard, breaks_keyboard,
    confirmation_keyboard, order_keyboard,
)
from app.schedule import available_breaks, closed_message, daily_breaks, local_now
from app.services.orders import OrderError, orders

router = Router()


async def check_session(callback: CallbackQuery, session: str) -> bool:
    if orders.valid_session(callback.from_user.id, session):
        return True
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Эти кнопки устарели. Начните новый заказ.", reply_markup=order_keyboard()
        )
    return False


async def show_cafes(message: Message, user_id: int):
    session = orders.begin(user_id)
    now = local_now()
    if not available_breaks(now):
        await message.answer(closed_message(now), reply_markup=order_keyboard())
        return
    await message.answer("Выберите кофейню!", reply_markup=cafes_keyboard(session))


@router.message(CommandStart())
async def start(message: Message):
    orders.cancel(message.from_user.id)
    await show_cafes(message, message.from_user.id)


@router.message(Command("schedule"))
async def schedule(message: Message):
    now = local_now()
    lines = ["Расписание на сегодня:"]
    for item in daily_breaks(now.date()):
        lines.append(f"{item.label}; заказы {item.opens_at:%H:%M}–{item.closes_at:%H:%M} (до)")
    await message.answer("\n".join(lines), reply_markup=order_keyboard())


@router.callback_query(F.data == "new_order")
async def new_order(callback: CallbackQuery):
    await callback.answer()
    orders.cancel(callback.from_user.id)
    if isinstance(callback.message, Message):
        await show_cafes(callback.message, callback.from_user.id)


@router.callback_query(F.data.startswith("cancel_order:"))
async def cancel_order(callback: CallbackQuery):
    await callback.answer()
    if not await check_session(callback, callback.data.split(":", 1)[1]):
        return
    orders.cancel(callback.from_user.id)
    if isinstance(callback.message, Message):
        await callback.message.answer("Оформление отменено.", reply_markup=order_keyboard())


@router.callback_query(F.data.startswith("cafe:"))
async def cafe_callback(callback: CallbackQuery):
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    now = local_now()
    if not available_breaks(now):
        await callback.message.answer(closed_message(now), reply_markup=order_keyboard())
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not await check_session(callback, parts[-1]):
        return
    _, cafe_id, session = parts
    if cafe_id not in CAFES:
        await callback.message.answer("Неизвестная кофейня!")
        return
    await callback.message.answer(
        f"Вы выбрали кофейню {CAFES[cafe_id]}. Теперь выберите напиток:",
        reply_markup=drinks_keyboard(cafe_id, session),
    )


@router.callback_query(F.data.startswith("drink:"))
async def drink_callback(callback: CallbackQuery):
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.message.answer("Начните новый заказ.")
        return
    if not await check_session(callback, parts[-1]):
        return
    _, cafe_id, drink_id, session = parts
    drink_name = MENU.get(cafe_id, {}).get(drink_id)
    if drink_name is None:
        await callback.message.answer("Такого напитка нет в меню.")
        return
    now = local_now()
    available = available_breaks(now)
    if not available:
        await callback.message.answer(closed_message(now), reply_markup=order_keyboard())
        return
    await callback.message.answer(
        f"{drink_name} — {PRICES[cafe_id][drink_id]} ₽. Выберите перерыв для получения:",
        reply_markup=breaks_keyboard(cafe_id, drink_id, available, session),
    )


@router.callback_query(F.data.startswith("pickup:"))
async def pickup_callback(callback: CallbackQuery):
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.message.answer("Начните новый заказ.")
        return
    if not await check_session(callback, parts[-1]):
        return
    _, cafe_id, drink_id, break_id, session = parts
    try:
        draft = orders.prepare(callback.from_user.id, cafe_id, drink_id, break_id, local_now())
    except OrderError as error:
        await callback.message.answer(str(error), reply_markup=order_keyboard())
        return
    await callback.message.answer(
        f"Проверьте тестовый заказ:\n{CAFES[cafe_id]} — {MENU[cafe_id][drink_id]}\n"
        f"Сумма: {draft.price} ₽\n{draft.pickup.label}\n"
        f"Подтвердите до {draft.pickup.closes_at:%H:%M} (Новосибирск).",
        reply_markup=confirmation_keyboard(draft.token, session),
    )


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_callback(callback: CallbackQuery):
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    try:
        order = orders.confirm(callback.from_user.id, callback.data.split(":", 1)[1], local_now())
    except OrderError as error:
        await callback.message.answer(str(error), reply_markup=order_keyboard())
        return
    draft = order.draft
    await callback.message.answer(
        f"Тестовый заказ №{order.number} сохранён.\n"
        f"{draft.cafe_name} — {draft.drink_name}, {draft.price} ₽\n"
        f"{draft.pickup.label}\nоплата и передача заказа бариста пока не подключены.",
        reply_markup=order_keyboard(),
    )
