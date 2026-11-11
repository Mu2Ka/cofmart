from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.config import Settings
from app.keyboards import order_keyboard

router = Router()


@router.message(CommandStart())
async def start(message: Message, settings: Settings) -> None:
    if message.chat.type != "private":
        await message.answer("Чтобы заказать кофе, откройте личный чат с ботом и нажмите /start.")
        return
    await message.answer(
        "Привет! Это Cofmart ☕\n\n"
        "Кофе к твоему перерыву. Нажми кнопку, чтобы открыть приложение.",
        reply_markup=order_keyboard(settings.mini_app_url),
    )
