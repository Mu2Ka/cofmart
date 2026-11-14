"""HTTP adapter to the unchanged ordering rules from main (ef9595f)."""
import json
import logging
from dataclasses import asdict
from types import SimpleNamespace
from urllib.parse import parse_qsl

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.exc import SQLAlchemyError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import current_user
from app.db.order_store import PostgresStore
from app.ordering import settings
from app.ordering.bans import bans, BLOCK_MESSAGE
from app.ordering.catalog import CAFES, CATEGORIES, PRODUCTS, get_drink
from app.ordering.orders import STATUSES, TRANSITIONS
from app.ordering.persistent import PersistentService
from app.ordering.roles import AccessError
from app.ordering.schedule import available_breaks, configurable_breaks, daily_breaks, closed_message, local_now

router = APIRouter(prefix='/flow', tags=['Full bot workflow'])


class Scope:
    def __init__(self, uid, store):
        self.uid = uid
        self.store = store
        self.orders = PersistentService('orders', store)
        self.customer = PersistentService('customer', store)
        self.cafes = PersistentService('cafes', store)
        self.roles = PersistentService('roles', store)


async def scope(request: Request, uid: int = Depends(current_user)):
    fields = dict(parse_qsl(request.headers['authorization'].partition(' ')[2]))
    user = json.loads(fields['user'])  # current_user has verified this exact initData.
    store = PostgresStore(request.app.state.db.sessions, clock=local_now)
    service = Scope(uid, store)
    if bans.is_blocked(uid, user.get('username')):
        await service.orders.cancel(uid)
        raise HTTPException(403, BLOCK_MESSAGE)
    await store.register(SimpleNamespace(id=uid, first_name=user.get('first_name', ''), username=user.get('username')))
    return service


def draft_data(draft):
    if draft is None:
        return None
    return {**asdict(draft), 'pickup_label': draft.pickup.label}


def order_data(order, actor_id=None, admin=False):
    return {**asdict(order), 'draft': draft_data(order.draft),
            'reference': order.reference, 'status_label': STATUSES[order.status],
            'transitions': sorted(TRANSITIONS[order.status]) if actor_id is not None and
              (admin or order.barista_id in {None, actor_id}) else []}


@router.get('/state')
async def state(service: Scope = Depends(scope)):
    view = await service.store.call('state', 'current', local_now())
    uid, now = service.uid, view.now
    roles, cafes, orders, customer = view.roles, view.cafes, view.orders, view.customer
    current = available_breaks(now)
    result = []
    summaries = {}
    for cid, name in CAFES.items():
        slots = orders.slots(cid, current[0].id, now) if current else None
        result.append({'id': cid, 'name': name, 'open': cafes.is_open(cid),
                       'slots': {**asdict(slots), 'free': slots.free} if slots else None,
                       'products': [{'id': pid, **asdict(product), 'available': cafes.is_available(cid, pid),
                         'variants': {sku: {'name': drink.name, 'price': drink.price}
                           for size in product.sizes for alt in ([False, True] if product.alternative_milk else [False])
                           for sku in [f'{pid}_{size}' + ('a' if alt else '')]
                           for drink in [get_drink(cid, sku)]}}
                                    for pid, product in PRODUCTS[cid].items()]})
        if roles.is_admin(uid):
            summaries[cid] = {label: len(orders.for_cafe(uid, cid, status))
                              for status, label in STATUSES.items()}
    return {'user_id': uid, 'admin': roles.is_admin(uid), 'staff_cafes': sorted(roles.cafes_for(uid)),
            'cafes': result, 'categories': CATEGORIES, 'follow_schedule': settings.FOLLOW_SCHEDULE,
            'service_message_ttl_seconds': settings.SERVICE_MESSAGE_TTL_SECONDS,
            'periods': [{'id': item.id, 'label': item.label} for item in current],
            'schedule_message': closed_message(now),
            'pauses': [f'{item.closes_at:%H:%M}–{item.ends_at:%H:%M}' for item in daily_breaks(now.date()) if item.id.endswith('s')],
            'session': orders.session(uid), 'draft': draft_data(orders.drafts.get(uid)),
            'orders': [order_data(order) for order in orders.for_user(uid)],
            'favorites': [asdict(item) for item in customer.list(uid)], 'summaries': summaries}


@router.get('/staff/{cafe_id}')
async def staff(cafe_id: str, service: Scope = Depends(scope)):
    view = await service.store.call('state', 'current', local_now())
    role_view, orders, now = view.roles, view.orders, view.now
    role_view.require_cafe(service.uid, cafe_id)
    counts, average = orders.rating_summary(service.uid, cafe_id)
    periods = []
    for item in configurable_breaks(now):
        summary = orders.slots(cafe_id, item.id, now)
        periods.append({'id': item.id, 'label': item.label, **asdict(summary), 'free': summary.free, 'active': summary.active})
    queue = []
    for status in STATUSES:
        queue.extend(order_data(order, service.uid, role_view.is_admin(service.uid))
                     for order in orders.for_cafe(service.uid, cafe_id, status))
    return {'orders': queue, 'periods': periods, 'rating_count': counts, 'rating_average': average,
            'baristas': sorted(uid for uid in role_view.staff_for(cafe_id) if cafe_id in role_view.barista_cafes(uid))}


class Action(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: str = Field(max_length=40)
    cafe_id: str = Field(default='', max_length=20)
    drink_id: str = Field(default='', max_length=32)
    product_id: str = Field(default='', max_length=20)
    break_id: str = Field(default='', max_length=20)
    token: str = Field(default='', max_length=16)
    session: str = Field(default='', max_length=8)
    reference: str = Field(default='', max_length=64)
    key: str = Field(default='', max_length=12)
    comment: str = Field(default='', max_length=300)
    value: int = Field(default=0, strict=True)
    revision: int = Field(default=0, ge=0, strict=True)
    target_id: int = Field(default=0, ge=0, le=2**63-1, strict=True)
    enabled: bool = Field(default=True, strict=True)
    status: str = Field(default='', max_length=16)


async def notification(kind, order, token, store):
    from app.bot.notifications import notify_staff, notify_student
    try:
        async with Bot(token) as bot:
            await (notify_staff(bot, order, store=store) if kind == 'staff' else notify_student(bot, order, store=store))
    except (TelegramAPIError, SQLAlchemyError, OSError, TimeoutError, ValueError):
        logging.getLogger(__name__).warning('Не удалось отправить уведомление после сохранения заказа.')


@router.post('/action')
async def action(body: Action, background: BackgroundTasks, request: Request, service: Scope = Depends(scope)):
    uid, now, operation = service.uid, local_now(), body.action
    value = None
    try:
        if operation == 'begin':
            value = await service.orders.begin(uid)
        elif operation == 'cancel':
            if not await service.orders.cancel_session(uid, body.session):
                raise ValueError('Оформление устарело. Обновите приложение.')
        elif operation == 'prepare':
            value = draft_data(await service.orders.prepare(uid, body.cafe_id, body.drink_id, body.break_id, now,
                comment=body.comment, session=body.session))
        elif operation == 'comment':
            value = draft_data(await service.orders.edit_comment(uid, body.token, body.comment, now))
        elif operation == 'confirm':
            order, created = await service.orders.confirm_once(uid, body.token, now)
            value = order_data(order)
            if created:
                background.add_task(notification, 'staff', order, request.app.state.settings.bot_token, service.orders.store)
        elif operation == 'favorite_draft':
            value = asdict(await service.customer.add_draft(uid, body.token, now))
        elif operation == 'favorite_order':
            value = asdict(await service.customer.add_order(uid, body.reference))
        elif operation == 'favorite_remove':
            await service.customer.remove(uid, body.key)
        elif operation in {'repeat', 'favorite_prepare'}:
            kind, key = ('r', body.reference) if operation == 'repeat' else ('f', body.key)
            value = draft_data(await service.customer.prepare_shortcut(uid, kind, key, now))
        elif operation == 'rate':
            value = order_data(await service.orders.rate(uid, body.reference, body.value))
        elif operation == 'transition':
            order = await service.orders.resolve_reference(body.reference)
            order = await service.orders.transition(uid, order.number, body.status, body.revision, now)
            value = order_data(order)
            background.add_task(notification, 'student', order, request.app.state.settings.bot_token, service.orders.store)
        elif operation == 'set_open':
            await service.cafes.set_open(uid, body.cafe_id, body.enabled)
        elif operation == 'set_available':
            await service.cafes.set_available(uid, body.cafe_id, body.product_id, body.enabled)
        elif operation in {'set_slots', 'add_slots'}:
            method = service.orders.set_slot_limit if operation == 'set_slots' else service.orders.add_slots
            value = asdict(await method(uid, body.cafe_id, body.break_id, body.value, now, body.revision))
        elif operation == 'assign':
            await service.roles.assign(uid, body.target_id, body.cafe_id, body.enabled)
        else:
            raise HTTPException(400, 'Неизвестное действие.')
    except AccessError as error:
        raise HTTPException(403, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {'result': value}
