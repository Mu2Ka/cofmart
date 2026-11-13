from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.catalog import CAFES, PRODUCTS
from app.notifications import notify_student
from app.schedule import local_now
from app.services.cafes import CafeError, cafes
from app.services.orders import OrderError, STATUSES, orders
from app.services.roles import AccessError, roles
from app.staff_keyboards import (
    PAGE_SIZE, availability_keyboard, cafe_keyboard, queue_keyboard,
    roles_keyboard, staff_home_keyboard, staff_order_keyboard,
)
from app.ui import order_text, show

router = Router()


async def respond(target: Message | CallbackQuery, text: str, keyboard):
    if isinstance(target, Message):
        await target.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await show(target, text, keyboard)


async def staff_home(target: Message | CallbackQuery, user_id: int):
    if not roles.cafes_for(user_id):
        await respond(target, "Доступ баристы ещё не назначен. Сообщите администратору свой ID из /myid.",
                      roles_keyboard(user_id))
        return
    orders.cancel(user_id)
    await respond(target, "<b>☕ Рабочая панель баристы</b>\n\nВыберите кофейню:", staff_home_keyboard(user_id))


async def admin_home(target: Message | CallbackQuery, user_id: int):
    if not roles.is_admin(user_id):
        await respond(target, "Доступ администратора не назначен.", roles_keyboard(user_id))
        return
    orders.cancel(user_id)
    lines = ["<b>⚙ Панель администратора</b>", ""]
    for cafe_id, name in CAFES.items():
        counts = [f"{STATUSES[status]}: {len(orders.for_cafe(user_id, cafe_id, status))}" for status in STATUSES]
        lines += [f"<b>{escape(name)}</b> · {'приём открыт' if cafes.is_open(cafe_id) else 'приём остановлен'}",
                  " · ".join(counts), ""]
        baristas = sorted(uid for uid in roles.staff_for(cafe_id) if cafe_id in roles.barista_cafes(uid))
        lines.append("Баристы: " + (", ".join(map(str, baristas)) or "не назначены"))
    lines += ["", "Назначить баристу: <code>/grant_barista Telegram_ID ID_кофейни</code>",
              "Снять доступ: <code>/revoke_barista Telegram_ID ID_кофейни</code>",
              "Кофейни: " + ", ".join(f"{cid} — {escape(name)}" for cid, name in CAFES.items()),
              "Назначения через команды действуют до перезапуска."]
    await respond(target, "\n".join(lines), staff_home_keyboard(user_id))


async def show_cafe(callback: CallbackQuery, cafe_id: str):
    active = orders.for_cafe(callback.from_user.id, cafe_id)
    await show(callback, f"<b>☕ {escape(CAFES[cafe_id])}</b>\n"
               f"{'🟢 Приём открыт' if cafes.is_open(cafe_id) else '⏸ Приём остановлен'}\n"
               f"Активных заказов: {len(active)}", cafe_keyboard(cafe_id))


async def show_availability(callback: CallbackQuery, cafe_id: str, page: int):
    page = min(page, max(0, (len(PRODUCTS[cafe_id]) - 1) // PAGE_SIZE))
    await show(callback, f"<b>{escape(CAFES[cafe_id])} · Наличие напитков</b>\n\n"
               "✅ — доступен, ⛔ — закончился. Нажмите на напиток для изменения.\n"
               "Изменение действует на все его объёмы и варианты молока.", availability_keyboard(cafe_id, page))


@router.callback_query(F.data.startswith("staff_"))
async def staff_callback(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    action = parts[0]
    sizes = {"staff_cafe": 2, "staff_queue": 4, "staff_order": 2,
             "staff_status": 4, "staff_accept": 3, "staff_menu": 3, "staff_item": 5}
    try:
        if len(parts) != sizes.get(action):
            raise OrderError("Кнопка устарела. Откройте рабочую панель заново.")
        user_id = callback.from_user.id
        if action in {"staff_order", "staff_status"}:
            number = int(parts[1])
            order = orders.for_staff(user_id, number)
            if action == "staff_status":
                order = orders.transition(user_id, number, parts[2], int(parts[3]), local_now())
                await notify_student(callback.bot, order)
            await show(callback, order_text(order, staff=True), staff_order_keyboard(order, user_id))
            return
        cafe_id = parts[1]
        roles.require_cafe(user_id, cafe_id)
        if action == "staff_cafe":
            await show_cafe(callback, cafe_id)
        elif action == "staff_accept":
            if parts[2] not in {"0", "1"}:
                raise ValueError
            cafes.set_open(user_id, cafe_id, parts[2] == "1")
            await show_cafe(callback, cafe_id)
        elif action == "staff_queue":
            status, page = parts[2], int(parts[3])
            if page < 0:
                raise ValueError
            queue = orders.for_cafe(user_id, cafe_id, status)
            page = min(page, max(0, (len(queue) - 1) // PAGE_SIZE))
            lines = [f"<b>{escape(CAFES[cafe_id])} · {STATUSES.get(status, 'Активные заказы')}</b>", ""]
            for order in queue[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
                lines.append(f"№{order.number} · {escape(order.draft.drink_name)} · {STATUSES[order.status]}")
            lines.append(f"\nВсего: {len(queue)} · страница {page + 1}" if queue else "Заказов пока нет.")
            await show(callback, "\n".join(lines), queue_keyboard(cafe_id, status, page, queue))
        elif action in {"staff_menu", "staff_item"}:
            page = int(parts[-1])
            if page < 0:
                raise ValueError
            if action == "staff_item":
                if parts[3] not in {"0", "1"}:
                    raise ValueError
                cafes.set_available(user_id, cafe_id, parts[2], parts[3] == "1")
            await show_availability(callback, cafe_id, page)
    except (AccessError, CafeError, OrderError) as error:
        await show(callback, escape(str(error)), staff_home_keyboard(callback.from_user.id))
    except ValueError:
        await show(callback, "Некорректная кнопка. Откройте панель заново.", staff_home_keyboard(callback.from_user.id))
