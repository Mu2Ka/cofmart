from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from app.catalog import CAFES, MENU
from app.keyboards import cafes_keyboard, drinks_keyboard

router = Router()


@router.message(CommandStart())
async def start(message: Message):
    await message.answer("Выберите кофейню!", reply_markup=cafes_keyboard())


@router.callback_query(F.data.startswith("cafe:"))
async def cafe_callback(callback: CallbackQuery):
    await callback.answer()
    cafe_id = callback.data.split(":", 1)[1]

    if not isinstance(callback.message, Message):
        return
    if cafe_id not in CAFES:
        await callback.message.answer("Неизвестная кофейня!")
        return

    await callback.message.answer(
        f"Вы выбрали кофейню {CAFES[cafe_id]}. Теперь выберите напиток:",
        reply_markup=drinks_keyboard(cafe_id),
    )


@router.callback_query(F.data.startswith("drink:"))
async def drink_callback(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")

    if not isinstance(callback.message, Message):
        return
    if len(parts) != 3:
        await callback.message.answer("Не удалось определить напиток.")
        return

    _, cafe_id, drink_id = parts
    drink_name = MENU.get(cafe_id, {}).get(drink_id)
    if drink_name is None:
        await callback.message.answer("Такого напитка нет в меню.")
        return

    await callback.message.answer(
        f"Вы выбрали {drink_name} в кофейне {CAFES[cafe_id]}."
    )
