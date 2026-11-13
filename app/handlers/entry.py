from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.handlers.staff import admin_home, staff_home
from app.handlers.student import show_cafes
from app.services.orders import orders
from app.services.roles import AccessError, roles
from app.staff_keyboards import roles_keyboard
from app.ui import show

router = Router()


@router.message(CommandStart())
@router.message(Command("roles"))
async def entry(message: Message):
    orders.cancel(message.from_user.id)
    await message.answer("<b>☕ Cofmart</b>\n\nВыберите, как продолжить.\nВаш Telegram ID: "
                         f"<code>{message.from_user.id}</code>", parse_mode="HTML",
                         reply_markup=roles_keyboard(message.from_user.id))


@router.message(Command("myid"))
async def my_id(message: Message):
    await message.answer(f"Ваш Telegram ID: {message.from_user.id}")


@router.message(Command("barista"))
async def barista_entry(message: Message):
    await staff_home(message, message.from_user.id)


@router.message(Command("admin"))
async def admin_entry(message: Message):
    await admin_home(message, message.from_user.id)


@router.callback_query(F.data == "roles")
async def choose_role(callback: CallbackQuery):
    await callback.answer()
    orders.cancel(callback.from_user.id)
    await show(callback, "<b>☕ Cofmart · Выберите роль</b>", roles_keyboard(callback.from_user.id))


@router.callback_query(F.data.startswith("role:"))
async def enter_role(callback: CallbackQuery):
    await callback.answer()
    role = callback.data.split(":", 1)[1]
    if role == "student" and isinstance(callback.message, Message):
        await show_cafes(callback.message, callback.from_user.id)
    elif role == "barista":
        await staff_home(callback, callback.from_user.id)
    elif role == "admin":
        await admin_home(callback, callback.from_user.id)


@router.message(Command("grant_barista", "revoke_barista"))
async def assign_barista(message: Message):
    user_id = message.from_user.id
    try:
        roles.require_admin(user_id)
        command, target_id, cafe_id = message.text.split()
        enabled = command.split('@')[0] == '/grant_barista'
        roles.assign(user_id, int(target_id), cafe_id, enabled)
    except AccessError as error:
        await message.answer(str(error))
        return
    except ValueError:
        await message.answer("Формат: /grant_barista Telegram_ID ID_кофейни или /revoke_barista Telegram_ID ID_кофейни")
        return
    await message.answer("Доступ назначен." if enabled else "Доступ снят.")
