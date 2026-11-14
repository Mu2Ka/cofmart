from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import settings
from app.catalog import CAFES, get_drink
from app.customer_keyboards import (
    FAVORITES_PAGE_SIZE, favorite_keyboard, favorites_keyboard,
    shortcut_breaks_keyboard, student_order_keyboard,
)
from app.handlers.student import show_draft
from app.schedule import available_breaks, closed_message, local_now
from app.services.cafes import CafeError, cafes
from app.services.customer import CustomerError, customer
from app.services.orders import OrderError, orders
from app.ui import order_text, show

router = Router()


async def show_favorites(target: Message | CallbackQuery, user_id: int, page: int = 0):
    items = customer.list(user_id)
    page = min(max(page, 0), max(0, (len(items) - 1) // FAVORITES_PAGE_SIZE))
    text = "<b>⭐ Избранные напитки</b>\n\n"
    text += (f"Сохранено: {len(items)}. Выберите напиток, чтобы заказать или удалить."
             if items else "Пока пусто. Нажмите «В избранное» в карточке напитка или заказа.")
    keyboard = favorites_keyboard(items, page)
    if isinstance(target, Message):
        await target.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await show(target, text, keyboard)


async def prepare_shortcut(callback: CallbackQuery, kind: str, key: str, break_id: str, session: str):
    draft = customer.prepare(callback.from_user.id, kind, key, break_id, local_now())
    await show_draft(callback, draft, session)


async def start_shortcut(callback: CallbackQuery, kind: str, key: str):
    user_id = callback.from_user.id
    selection = customer.selection(user_id, kind, key)
    drink = get_drink(selection.cafe_id, selection.drink_id)
    if drink is None:
        raise CustomerError("Напиток больше не представлен в меню. Выберите другой.")
    cafes.require_orderable(selection.cafe_id, selection.drink_id)
    now = local_now()
    available = available_breaks(now)
    if not available:
        raise CustomerError(closed_message(now))
    session = orders.begin(user_id)
    if not settings.FOLLOW_SCHEDULE:
        await prepare_shortcut(callback, kind, key, available[0].id, session)
        return
    pickups = []
    for pickup in available:
        summary = orders.slots(selection.cafe_id, pickup.id, now)
        pickups.append((pickup, summary.free, summary.limit))
    await show(callback, f"<b>{escape(CAFES[selection.cafe_id])}</b>\n{escape(drink.name)}\n"
               f"Текущая цена: <b>{drink.price} ₽</b>\n\nВыберите новую перемену:",
               shortcut_breaks_keyboard(kind, key, session, pickups))


@router.message(Command("favorites"))
async def favorites_command(message: Message):
    await show_favorites(message, message.from_user.id)


@router.message(Command("repeat"))
async def repeat_command(message: Message):
    recent = orders.for_user(message.from_user.id)
    if not recent:
        await message.answer("У вас пока нет заказов для повторения.")
        return
    # Кнопка оставляет пользователю явный выбор, не бронируя слот самой командой.
    await message.answer(order_text(recent[0]), parse_mode="HTML",
                         reply_markup=student_order_keyboard(recent[0]))


@router.callback_query(F.data.regexp(r"^(repeat_last$|repeat:|favorites:|favorite:|favorite_order:|favorite_remove:|favorite_add:|favorite_draft:|quick:|rate:)"))
async def customer_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    action, user_id = parts[0], callback.from_user.id
    if action in {"favorite_add", "favorite_draft"}:
        try:
            if len(parts) != 2:
                raise CustomerError("Кнопка устарела.")
            if action == "favorite_add":
                customer.add_order(user_id, parts[1])
            else:
                customer.add_draft(user_id, parts[1], local_now())
        except (CustomerError, OrderError) as error:
            await callback.answer(str(error), show_alert=True)
        else:
            await callback.answer("Напиток добавлен в избранное ⭐")
        return
    await callback.answer()
    try:
        expected = {"repeat_last": 1, "repeat": 2, "favorites": 2, "favorite": 2,
                    "favorite_order": 2, "favorite_remove": 2, "quick": 5, "rate": 3}
        if len(parts) != expected.get(action):
            raise CustomerError("Кнопка устарела. Откройте список заново.")
        if action == "repeat_last":
            recent = orders.for_user(user_id)
            if not recent:
                raise CustomerError("У вас пока нет заказов для повторения.")
            await start_shortcut(callback, "r", recent[0].reference)
        elif action == "repeat":
            await start_shortcut(callback, "r", parts[1])
        elif action == "favorites":
            await show_favorites(callback, user_id, int(parts[1]))
        elif action == "favorite":
            favorite = customer.get(user_id, parts[1])
            drink = get_drink(favorite.cafe_id, favorite.drink_id)
            text = f"<b>⭐ {escape(favorite.cafe_name)}</b>\n{escape(favorite.drink_name)}\n\n"
            text += f"Текущая цена: <b>{drink.price} ₽</b>" if drink else "Напиток больше не представлен в меню."
            await show(callback, text, favorite_keyboard(favorite))
        elif action == "favorite_order":
            await start_shortcut(callback, "f", parts[1])
        elif action == "favorite_remove":
            customer.remove(user_id, parts[1])
            await show_favorites(callback, user_id)
        elif action == "quick":
            _, kind, key, break_id, session = parts
            if not orders.valid_session(user_id, session):
                raise CustomerError("Оформление устарело. Начните новый заказ.")
            await prepare_shortcut(callback, kind, key, break_id, session)
        elif action == "rate":
            order = orders.rate(user_id, parts[1], int(parts[2]))
            await show(callback, order_text(order) + "\n\nСпасибо за оценку!", student_order_keyboard(order))
    except (CustomerError, OrderError, CafeError) as error:
        await show(callback, escape(str(error)))
    except ValueError:
        await show(callback, "Некорректная кнопка. Откройте список заново.")
