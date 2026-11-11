import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

load_dotenv()
dp = Dispatcher()


CAFES = {"1": "CaVa", "2": "Порт-Брю"}
MENU = {
    "1": {"1": "Капучино", "2": "Латте"},
    "2": {"1": "Американо", "2": "Раф"},
}


@dp.message(CommandStart())
async def start(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="CaVa", callback_data="cafe:1")
            ],
            [
                InlineKeyboardButton(text="Порт-Брю", callback_data="cafe:2")
            ]
        ]
    )
    await message.answer("Выберите кофейню!", reply_markup=keyboard)



@dp.callback_query(F.data.startswith("cafe:"))
async def cafe_callback(callback: CallbackQuery):
    await callback.answer()
    cafe_id = callback.data.split(":")[1]

    if cafe_id not in CAFES:
        if isinstance(callback.message, Message):
            await callback.message.answer("Неизвестная кофейня!")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=drink_name, callback_data=f"drink:{cafe_id}:{drink_id}")]
            for drink_id, drink_name in MENU[cafe_id].items()
        ]
    )
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"Вы выбрали кофейню {CAFES[cafe_id]}. Теперь выберите напиток:",
            reply_markup=keyboard,
        )


@dp.callback_query(F.data.startswith("drink:"))
async def drink_callback(callback: CallbackQuery):
    await callback.answer()
    _, cafe_id, drink_id = callback.data.split(":")
    drink_name = MENU.get(cafe_id, {}).get(drink_id)

    if isinstance(callback.message, Message):
        if drink_name is None:
            await callback.message.answer("Такого напитка нет в меню.")
        else:
            await callback.message.answer(
                f"Вы выбрали {drink_name} в кофейне {CAFES[cafe_id]}."
            )


async def main():
    token = os.getenv("API_BOT")
    if not token:
        raise RuntimeError("Добавьте API_BOT в файл .env")

    bot = Bot(token=token)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
