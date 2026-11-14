from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.ordering.catalog import CAFES, PRODUCTS
from app.bot.notifications import notify_student
from app.ordering.schedule import configurable_breaks, find_configurable_break, local_now
from app.ordering.cafes import CafeError
from app.ordering.persistent import cafes
from app.ordering.orders import MAX_SLOT_LIMIT, OrderError, SlotEditExpired, STATUSES
from app.ordering.persistent import orders
from app.ordering.roles import AccessError
from app.ordering.persistent import roles
from app.bot.staff_keyboards import (
    PAGE_SIZE, availability_keyboard, cafe_keyboard, queue_keyboard,
    roles_keyboard, staff_home_keyboard, staff_order_keyboard,
    slot_breaks_keyboard, slot_limit_keyboard,
)
from app.bot.message_cleanup import answer_notice
from app.bot.ui import order_text, show, show_notice

router = Router()


async def respond(target: Message | CallbackQuery, text: str, keyboard, *, temporary=False):
    if isinstance(target, Message):
        if temporary:
            await answer_notice(target, text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await target.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await show(target, text, keyboard, temporary=temporary)


async def staff_home(target: Message | CallbackQuery, user_id: int):
    if not await roles.cafes_for(user_id):
        await respond(target, "Доступ баристы ещё не назначен. Сообщите администратору свой ID из /myid.",
                      await roles_keyboard(user_id), temporary=True)
        return
    await orders.cancel(user_id)
    await respond(target, "<b>☕ Рабочая панель баристы</b>\n\nВыберите кофейню:", await staff_home_keyboard(user_id))


async def admin_home(target: Message | CallbackQuery, user_id: int):
    if not await roles.is_admin(user_id):
        await respond(target, "Доступ администратора не назначен.", await roles_keyboard(user_id), temporary=True)
        return
    await orders.cancel(user_id)
    lines = ["<b>⚙ Панель администратора</b>", ""]
    for cafe_id, name in CAFES.items():
        counts = [f"{STATUSES[status]}: {len(await orders.for_cafe(user_id, cafe_id, status))}" for status in STATUSES]
        lines += [f"<b>{escape(name)}</b> · {'приём открыт' if await cafes.is_open(cafe_id) else 'приём остановлен'}",
                  " · ".join(counts), ""]
        role_view = await roles.view()
        baristas = sorted(uid for uid in role_view.staff_for(cafe_id) if cafe_id in role_view.barista_cafes(uid))
        lines.append("Баристы: " + (", ".join(map(str, baristas)) or "не назначены"))
        count, average = await orders.rating_summary(user_id, cafe_id)
        lines.append(f"⭐ Средняя оценка: {average:.1f}/5 ({count})" if count else "⭐ Оценок пока нет")
    lines += ["", "Назначить баристу: <code>/grant_barista Telegram_ID ID_кофейни</code>",
              "Снять доступ: <code>/revoke_barista Telegram_ID ID_кофейни</code>",
              "Кофейни: " + ", ".join(f"{cid} — {escape(name)}" for cid, name in CAFES.items()),
              "Назначения сохраняются в базе данных."]
    await respond(target, "\n".join(lines), await staff_home_keyboard(user_id))


async def show_cafe(callback: CallbackQuery, cafe_id: str):
    active = await orders.for_cafe(callback.from_user.id, cafe_id)
    count, average = await orders.rating_summary(callback.from_user.id, cafe_id)
    rating = f"\n⭐ {average:.1f}/5 · оценок: {count}" if count else "\n⭐ Оценок пока нет"
    await show(callback, f"<b>☕ {escape(CAFES[cafe_id])}</b>\n"
               f"{'🟢 Приём открыт' if await cafes.is_open(cafe_id) else '⏸ Приём остановлен'}\n"
               f"Активных заказов: {len(active)}{rating}", await cafe_keyboard(cafe_id))


async def show_availability(callback: CallbackQuery, cafe_id: str, page: int):
    page = min(page, max(0, (len(PRODUCTS[cafe_id]) - 1) // PAGE_SIZE))
    await show(callback, f"<b>{escape(CAFES[cafe_id])} · Наличие напитков</b>\n\n"
               "✅ — доступен, ⛔ — закончился. Нажмите на напиток для изменения.\n"
               "Изменение действует на все его объёмы и варианты молока.", await availability_keyboard(cafe_id, page))


async def show_slot_breaks(callback: CallbackQuery, cafe_id: str):
    now = local_now()
    items = [(pickup, await orders.slots(cafe_id, pickup.id, now)) for pickup in configurable_breaks(now)]
    await show(callback, f"<b>🎟 {escape(CAFES[cafe_id])} · Слоты</b>\n\n"
               "Выберите период приёма. Число справа — свободные слоты / общий лимит.\n"
               "Лимит учитывает заказы и временные резервы.", slot_breaks_keyboard(cafe_id, items))


async def show_slot_limit(target: Message | CallbackQuery, cafe_id: str, break_id: str):
    now = local_now()
    pickup = find_configurable_break(break_id, now)
    if pickup is None:
        raise OrderError("Этот период приёма уже закрыт. Обновите список.")
    summary = await orders.slots(cafe_id, break_id, now)
    await respond(target, f"<b>🎟 {escape(CAFES[cafe_id])}</b>\n{pickup.label}\n\n"
                  f"Общий лимит периода приёма: <b>{summary.limit}</b>\n"
                  f"Заказов в работе: {summary.active}\nВыдано (квота потрачена): {summary.completed}\n"
                  f"Временные резервы: {summary.reserved}\n<b>Свободно: {summary.free}</b>\n\n"
                  "Выдача заказа не возвращает слот. Чтобы принять больше заказов, добавьте слоты.\n"
                  "Числа ниже задают общий лимит; 0 закрывает новые заказы.",
                  slot_limit_keyboard(cafe_id, pickup, summary))


async def editing_slots(message: Message) -> bool:
    return bool(message.from_user and await orders.slot_edit(message.from_user.id))


@router.message(editing_slots,
                F.text & ~F.text.startswith("/"))
async def slot_limit_input(message: Message):
    user_id = message.from_user.id
    edit = await orders.slot_edit(user_id)
    if edit is None:
        return
    try:
        try:
            value = int(message.text.strip())
        except ValueError:
            raise OrderError(f"Введите целое число от 0 до {MAX_SLOT_LIMIT}.")
        edit = await orders.save_slot_edit(user_id, value, local_now())
        await show_slot_limit(message, edit.cafe_id, edit.break_id)
    except (AccessError, SlotEditExpired) as error:
        await orders.clear_slot_edit(user_id)
        await answer_notice(message, str(error), reply_markup=await staff_home_keyboard(user_id))
    except OrderError as error:
        await answer_notice(message, str(error), reply_markup=await staff_home_keyboard(user_id))


@router.message(editing_slots, ~F.text)
async def slot_limit_nontext(message: Message):
    await answer_notice(message, f"Отправьте число слотов текстом: от 0 до {MAX_SLOT_LIMIT}.")


@router.callback_query(F.data.startswith("staff_"))
async def staff_callback(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    action = parts[0]
    sizes = {"staff_cafe": 2, "staff_queue": 4, "staff_order": 2,
             "staff_status": 4, "staff_accept": 3, "staff_menu": 3, "staff_item": 5,
             "staff_slots": 2, "staff_slot": 3, "staff_setslots": 5, "staff_addslots": 5, "staff_editslots": 3}
    try:
        if len(parts) != sizes.get(action):
            raise OrderError("Кнопка устарела. Откройте рабочую панель заново.")
        user_id = callback.from_user.id
        await orders.clear_slot_edit(user_id)
        if action in {"staff_order", "staff_status"}:
            order = await orders.resolve_reference(parts[1])
            order = await orders.for_staff(user_id, order.number)
            if action == "staff_status":
                order = await orders.transition(user_id, order.number, parts[2], int(parts[3]), local_now())
                await notify_student(callback.bot, order)
            await show(callback, order_text(order, staff=True), await staff_order_keyboard(order, user_id))
            return
        cafe_id = parts[1]
        await roles.require_cafe(user_id, cafe_id)
        if action == "staff_cafe":
            await show_cafe(callback, cafe_id)
        elif action == "staff_slots":
            await show_slot_breaks(callback, cafe_id)
        elif action == "staff_slot":
            await show_slot_limit(callback, cafe_id, parts[2])
        elif action == "staff_setslots":
            await orders.set_slot_limit(user_id, cafe_id, parts[2], int(parts[3]), local_now(), int(parts[4]))
            await show_slot_limit(callback, cafe_id, parts[2])
        elif action == "staff_addslots":
            await orders.add_slots(user_id, cafe_id, parts[2], int(parts[3]), local_now(), int(parts[4]))
            await show_slot_limit(callback, cafe_id, parts[2])
        elif action == "staff_editslots":
            await orders.start_slot_edit(user_id, cafe_id, parts[2], local_now())
            pickup = find_configurable_break(parts[2], local_now())
            await show(callback, f"<b>Новый лимит · {escape(CAFES[cafe_id])}</b>\n{pickup.label}\n\n"
                       f"Отправьте целое число от 0 до {MAX_SLOT_LIMIT} обычным сообщением.",
                       slot_limit_keyboard(cafe_id, pickup, await orders.slots(cafe_id, pickup.id, local_now())),
                       temporary=True)
        elif action == "staff_accept":
            if parts[2] not in {"0", "1"}:
                raise ValueError
            await cafes.set_open(user_id, cafe_id, parts[2] == "1")
            await show_cafe(callback, cafe_id)
        elif action == "staff_queue":
            status, page = parts[2], int(parts[3])
            if page < 0:
                raise ValueError
            queue = await orders.for_cafe(user_id, cafe_id, status)
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
                await cafes.set_available(user_id, cafe_id, parts[2], parts[3] == "1")
            await show_availability(callback, cafe_id, page)
    except (AccessError, CafeError, OrderError) as error:
        await show_notice(callback, escape(str(error)), await staff_home_keyboard(callback.from_user.id))
    except ValueError:
        await show_notice(callback, "Некорректная кнопка. Откройте панель заново.", await staff_home_keyboard(callback.from_user.id))
