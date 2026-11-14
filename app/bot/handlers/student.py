from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.formatting import summary
from app.bot.keyboards import cafes_keyboard, cart_keyboard, drinks_keyboard
from app.services.catalog import CatalogService
from app.services.dto import ItemInput
from app.services.errors import BusinessError
from app.services.orders import OrderService

router = Router()


def positive_id(raw: str) -> int:
    try:
        result = int(raw)
        if result <= 0:
            raise ValueError
        return result
    except ValueError:
        raise BusinessError("INVALID_CALLBACK", "Эта кнопка недействительна. Откройте /start.") from None


def cart_items(data) -> list[ItemInput]:
    return [ItemInput(int(k), v) for k, v in data.get("cart", {}).items()]


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, catalog: CatalogService, mini_app_url: str):
    await state.clear()
    url = mini_app_url if message.chat.type == "private" else ""
    await message.answer("Выберите кофейню!", reply_markup=cafes_keyboard(await catalog.cafes(), url))


@router.callback_query(F.data == "cafes")
async def show_cafes(callback: CallbackQuery, catalog: CatalogService, mini_app_url: str):
    await callback.answer()
    if isinstance(callback.message, Message):
        url = mini_app_url if callback.message.chat.type == "private" else ""
        await callback.message.answer("Выберите кофейню!", reply_markup=cafes_keyboard(await catalog.cafes(), url))


@router.callback_query(F.data.startswith("cafe:"))
async def cafe_callback(callback: CallbackQuery, state: FSMContext, catalog: CatalogService):
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    cafe_id = positive_id(callback.data.split(":", 1)[1])
    cafe = await catalog.cafe(cafe_id)
    data = await state.get_data()
    if data.get("cafe_id") != cafe_id:
        await state.set_data({"cafe_id": cafe_id, "cart": {}})
    await callback.message.answer(f"Вы выбрали кофейню {cafe.name}. Теперь выберите напиток:",
                                  reply_markup=drinks_keyboard(cafe_id, await catalog.menu(cafe_id)))


@router.callback_query(F.data.startswith("drink:"))
async def drink_callback(callback: CallbackQuery, state: FSMContext, catalog: CatalogService, orders: OrderService):
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        raise BusinessError("INVALID_CALLBACK", "Не удалось определить напиток.")
    cafe_id = positive_id(parts[1])
    drink = await catalog.legacy_drink(cafe_id, parts[2])
    cafe = await catalog.cafe(cafe_id)
    data = await state.get_data()
    cart = dict(data.get("cart", {})) if data.get("cafe_id") == cafe_id else {}
    cart[str(drink.id)] = cart.get(str(drink.id), 0) + 1
    preview = await orders.preview(cafe_id, cart_items({"cart": cart}))
    await state.set_data({"cafe_id": cafe_id, "cart": cart})
    await callback.message.answer(f"Вы выбрали {drink.name} в кофейне {cafe.name}.\n\n" + summary(preview),
                                  reply_markup=cart_keyboard(cafe_id))
