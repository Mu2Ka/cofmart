from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.formatting import local_time, order_text, summary
from app.bot.handlers.student import cart_items, positive_id
from app.bot.keyboards import cart_keyboard, keyboard, slots_keyboard
from app.services.catalog import CatalogService
from app.services.dto import ItemInput, OrderCommand
from app.services.errors import BusinessError
from app.services.orders import OrderService
from app.services.slots import SlotService

router = Router()


def require_cart(data):
    if not data.get("cart") or not data.get("cafe_id"):
        raise BusinessError("EMPTY_CART", "Корзина пуста. Выберите напитки через /start.")


@router.callback_query(F.data == "cart")
async def cart(callback: CallbackQuery, state: FSMContext, orders: OrderService):
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    data = await state.get_data()
    require_cart(data)
    preview = await orders.preview(data["cafe_id"], cart_items(data))
    await callback.message.answer(summary(preview), reply_markup=cart_keyboard(data["cafe_id"]))


@router.callback_query(F.data == "clear_cart")
async def clear_cart(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    await state.set_data({"cafe_id": data.get("cafe_id"), "cart": {}})
    if isinstance(callback.message, Message):
        await callback.message.answer("Корзина очищена. Выберите напитки через /start.")


@router.callback_query(F.data == "checkout")
async def checkout(callback: CallbackQuery, state: FSMContext, slots: SlotService, catalog: CatalogService):
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    data = await state.get_data()
    require_cart(data)
    cafe = await catalog.cafe(data["cafe_id"])
    available = await slots.available(cafe.id)
    await state.update_data(checkout=None)
    if not available:
        await callback.message.answer("Свободного времени пока нет. Попробуйте позже.", reply_markup=cart_keyboard(cafe.id))
        return
    await callback.message.answer("Выберите время получения:", reply_markup=slots_keyboard(available, cafe.timezone))


@router.callback_query(F.data.startswith("slot:"))
async def slot(callback: CallbackQuery, state: FSMContext, slots: SlotService, catalog: CatalogService, orders: OrderService):
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    data = await state.get_data()
    require_cart(data)
    slot_id = positive_id(callback.data.split(":", 1)[1])
    available = {x.id: x for x in await slots.available(data["cafe_id"])}
    if slot_id not in available:
        raise BusinessError("SLOT_UNAVAILABLE", "Это время уже недоступно. Выберите другое.")
    preview = await orders.preview(data["cafe_id"], cart_items(data))
    cafe = await catalog.cafe(data["cafe_id"])
    key = uuid4().hex
    await state.update_data(checkout={"key": key, "cafe_id": cafe.id, "slot_id": slot_id,
                                     "items": data["cart"], "expected_total_minor": preview.total_minor})
    await callback.message.answer(
        f"{cafe.name}\nПолучение: {local_time(available[slot_id].starts_at, cafe.timezone)}\n" + summary(preview),
        reply_markup=keyboard([[("Подтвердить заказ", f"confirm:{key}")], [("В корзину", "cart")]]))


@router.callback_query(F.data.startswith("confirm:"))
async def confirm(callback: CallbackQuery, state: FSMContext, orders: OrderService):
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    data = await state.get_data()
    checkout = data.get("checkout")
    if not checkout or checkout["key"] != callback.data.split(":", 1)[1]:
        raise BusinessError("STALE_CHECKOUT", "Этот расчёт устарел. Откройте корзину заново.")
    order = await orders.create(callback.from_user.id, OrderCommand(
        checkout["cafe_id"], checkout["slot_id"],
        [ItemInput(int(k), v) for k, v in checkout["items"].items()],
        checkout["expected_total_minor"], checkout["key"]))
    # Retain the checkout key: duplicate callbacks return the same confirmed order.
    await state.update_data(cart={})
    await callback.message.answer(order_text(order), reply_markup=keyboard([[("Новый заказ", "cafes"), ("Мои заказы", "history")]]))


async def send_history(message, user_id, orders):
    history = await orders.list(user_id, limit=10)
    if not history:
        await message.answer("У вас пока нет заказов.")
    for order in history:
        await message.answer(order_text(order))


@router.callback_query(F.data == "history")
async def history(callback: CallbackQuery, orders: OrderService):
    await callback.answer()
    if isinstance(callback.message, Message):
        await send_history(callback.message, callback.from_user.id, orders)


@router.message(Command("orders"))
async def orders_command(message: Message, orders: OrderService):
    if message.from_user:
        await send_history(message, message.from_user.id, orders)
