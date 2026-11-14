from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.handlers.staff import admin_home, staff_home
from app.handlers.student import show_cafes
from app.services.persistent import orders
from app.services.roles import AccessError
from app.services.persistent import roles
from app.staff_keyboards import roles_keyboard
from app.message_cleanup import answer_notice
from app.ui import show

router = Router()


@router.message(CommandStart())
@router.message(Command("roles"))
async def entry(message: Message):
    await orders.cancel(message.from_user.id)
    await message.answer("<b>☕ Cofmart</b>\n\nВыберите, как продолжить.\nВаш Telegram ID: "
                         f"<code>{message.from_user.id}</code>", parse_mode="HTML",
                         reply_markup=await roles_keyboard(message.from_user.id))


@router.message(Command("myid"))
async def my_id(message: Message):
    user_id = message.from_user.id
    available = ["студент"]
    if await roles.cafes_for(user_id):
        available.append("бариста")
    if await roles.is_admin(user_id):
        available.append("администратор")
    await message.answer(f"Ваш Telegram ID: {user_id}\nДоступные роли: {', '.join(available)}")


@router.message(Command("barista"))
async def barista_entry(message: Message):
    await staff_home(message, message.from_user.id)


@router.message(Command("admin"))
async def admin_entry(message: Message):
    await admin_home(message, message.from_user.id)


@router.callback_query(F.data == "roles")
async def choose_role(callback: CallbackQuery):
    await callback.answer()
    await orders.cancel(callback.from_user.id)
    await show(callback, "<b>☕ Cofmart · Выберите роль</b>", await roles_keyboard(callback.from_user.id))


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
        await roles.require_admin(user_id)
        command, target_id, cafe_id = message.text.split()
        enabled = command.split('@')[0] == '/grant_barista'
        await roles.assign(user_id, int(target_id), cafe_id, enabled)
    except AccessError as error:
        await answer_notice(message, str(error))
        return
    except ValueError:
        await answer_notice(message, "Формат: /grant_barista Telegram_ID ID_кофейни или /revoke_barista Telegram_ID ID_кофейни")
        return
    await answer_notice(message, "Доступ назначен." if enabled else "Доступ снят.")
