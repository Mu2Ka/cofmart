import asyncio
import os
from aiogram import Dispatcher,Bot,F
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

load_dotenv()
bot = Bot(token=os.getenv("API_BOT"))
dp = Dispatcher()
bot = Bot(token=os.getenv("API_BOT"))
print("Токен загружен:", bool(os.getenv("API_BOT")))


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
    await message.answer("Выберите Кофейню!", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("cafe:"))
async def cafe_callback(callback: CallbackQuery):
    await callback.answer()
    cafe_id = callback.data.split(":")[1]
    if cafe_id == "1":
        await callback.message.answer("Вы выбрали Кофейню CaVa!")
    elif cafe_id == "2":
        await callback.message.answer("Вы выбрали Кофейню Порт-Брю!")
    else:
        await callback.message.answer("Неизвестная кофейня!")
        
async def main():
    await dp.start_polling(bot)
    
    
if __name__ == "__main__":
    asyncio.run(main())
