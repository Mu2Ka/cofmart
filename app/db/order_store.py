"""Транзакционная граница между правилами заказа и PostgreSQL.

Для небольшого учебного бота загружаем состояние сервисов на одну операцию.
Сохраняем только изменённые строки. Правила остаются синхронными и тестируются
без базы; запросы к PostgreSQL выполняются асинхронно. Telegram вызывается уже
после commit. При росте истории загрузку следует заменить выборками по пользователю/точке.
"""

from dataclasses import asdict
from datetime import datetime
from contextlib import asynccontextmanager
from inspect import signature

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

from app.db.ordering_models import (
    Cafe, DraftRecord, FavoriteRecord, OrderRecord, RoleOverrideRecord,
    SessionRecord, SlotLimitRecord, StoppedProductRecord, User, MessageDeletionRecord,
)
from app.ordering.schedule import Break, LOCAL_TIMEZONE
from app.ordering.cafes import CafeService
from app.ordering.customer import CustomerService, Favorite
from app.ordering.orders import Draft, Order, OrderService, SlotEdit
from app.ordering.roles import RoleService

# Один и тот же lock для всех процессов бота, а не только для задач одного Python.
STATE_LOCK = 714031802


def pack_draft(draft: Draft) -> dict:
    value = asdict(draft)
    value["reserved_until"] = draft.reserved_until.isoformat()
    for name in ("opens_at", "starts_at", "ends_at"):
        value["pickup"][name] = getattr(draft.pickup, name).isoformat()
    return value


def unpack_draft(value: dict) -> Draft:
    data = dict(value)
    pickup = dict(data.pop("pickup"))
    for name in ("opens_at", "starts_at", "ends_at"):
        pickup[name] = datetime.fromisoformat(pickup[name]).astimezone(LOCAL_TIMEZONE)
    data["reserved_until"] = datetime.fromisoformat(data["reserved_until"]).astimezone(LOCAL_TIMEZONE)
    return Draft(**data, pickup=Break(**pickup))


class State:
    def __init__(self):
        self.roles = RoleService()
        self.cafes = CafeService(self.roles)
        self.orders = OrderService(self.roles, self.cafes)
        # Нулевая ревизия в БД стабильна между операциями и перезапусками.
        self.orders.slot_epoch = 0
        self.customer = CustomerService(self.orders)

    def rows(self) -> dict:
        orders = self.orders
        users = set(orders.sessions) | set(orders.waiting_comments) | set(orders.slot_edits)
        return {
            OrderRecord: {
                o.number: dict(number=o.number, token=o.draft.token, key=o.key,
                    user_id=o.draft.user_id, cafe_id=o.draft.cafe_id, break_id=o.draft.pickup.id,
                    draft=pack_draft(o.draft), status=o.status, revision=o.revision,
                    barista_id=o.barista_id, rating=o.rating,
                    created_at=o.created_at, updated_at=o.updated_at)
                for o in orders.confirmed.values()
            },
            DraftRecord: {
                uid: dict(user_id=uid, token=d.token, cafe_id=d.cafe_id, break_id=d.pickup.id,
                    reserved_until=d.reserved_until, draft=pack_draft(d))
                for uid, d in orders.drafts.items()
            },
            SlotLimitRecord: {
                (cid, bid): dict(cafe_id=cid, break_id=bid, limit=limit,
                    revision=orders.slot_revisions[(cid, bid)])
                for (cid, bid), limit in orders.slot_limits.items()
            },
            FavoriteRecord: {
                f.key: dict(user_id=uid, **asdict(f))
                for uid, items in self.customer.favorites.items() for f in items.values()
            },
            RoleOverrideRecord: {
                uid: dict(user_id=uid, cafe_ids=sorted(cids)) for uid, cids in self.roles.assignments.items()
            },
            StoppedProductRecord: {
                (cid, pid): dict(cafe_id=cid, product_id=pid) for cid, pid in self.cafes.stoplist
            },
            SessionRecord: {
                uid: dict(user_id=uid, token=orders.sessions.get(uid),
                    waiting_comment=orders.waiting_comments.get(uid),
                    slot_edit=asdict(orders.slot_edits[uid]) if uid in orders.slot_edits else None)
                for uid in users
            },
        }


async def load_state(session, service="orders") -> tuple[State, dict, list[Cafe]]:
    state = State()
    models = (OrderRecord, DraftRecord, SlotLimitRecord, FavoriteRecord,
              RoleOverrideRecord, StoppedProductRecord, SessionRecord)
    # Проверка прав и построение меню не требуют чтения истории заказов.
    needed = ({RoleOverrideRecord} if service == "roles" else
              {RoleOverrideRecord, StoppedProductRecord} if service == "cafes" else set(models))
    rows = {}
    for model in models:
        if model not in needed:
            rows[model] = []
            continue
        statement = select(model)
        if model is OrderRecord:
            statement = statement.order_by(OrderRecord.number)
        rows[model] = list((await session.scalars(statement)).all())
    cafe_rows = list((await session.scalars(select(Cafe))).all())
    state.cafes.paused = {row.id for row in cafe_rows if not row.accepts_orders}
    state.cafes.stoplist = {(row.cafe_id, row.product_id) for row in rows[StoppedProductRecord]}
    state.roles.assignments = {row.user_id: set(row.cafe_ids) for row in rows[RoleOverrideRecord]}
    orders = state.orders
    for row in rows[OrderRecord]:
        draft = unpack_draft(row.draft)
        order = Order(number=row.number, draft=draft, status=row.status, revision=row.revision,
            barista_id=row.barista_id, key=row.key, rating=row.rating,
            created_at=row.created_at.astimezone(LOCAL_TIMEZONE),
            updated_at=row.updated_at.astimezone(LOCAL_TIMEZONE))
        orders.confirmed[row.token] = order
        orders.order_tokens[row.number] = row.token
    orders.drafts = {row.user_id: unpack_draft(row.draft) for row in rows[DraftRecord]}
    for row in rows[SlotLimitRecord]:
        key = (row.cafe_id, row.break_id)
        orders.slot_limits[key] = row.limit
        orders.slot_revisions[key] = int(row.revision)
    for row in rows[FavoriteRecord]:
        item = Favorite(row.key, row.cafe_id, row.drink_id, row.cafe_name, row.drink_name)
        state.customer.favorites.setdefault(row.user_id, {})[row.key] = item
    for row in rows[SessionRecord]:
        if row.token:
            orders.sessions[row.user_id] = row.token
        if row.waiting_comment:
            orders.waiting_comments[row.user_id] = row.waiting_comment
        if row.slot_edit:
            orders.slot_edits[row.user_id] = SlotEdit(**row.slot_edit)
    # Идентифицируем загруженные ORM-строки, чтобы не перезаписывать историю целиком.
    identities = {}
    for model, items in rows.items():
        keys = [column.name for column in model.__table__.primary_key]
        identities[model] = {}
        for row in items:
            key = tuple(getattr(row, name) for name in keys)
            identities[model][key[0] if len(key) == 1 else key] = row
    return state, identities, cafe_rows


class PostgresStore:
    def __init__(self, session_factory, clock=None):
        self.session_factory = session_factory
        self.clock = clock

    async def schedule_deletion(self, bot_id, chat_id, message_id, delete_at):
        async with self.session_factory.begin() as session:
            statement = insert(MessageDeletionRecord).values(bot_id=bot_id, chat_id=chat_id,
                message_id=message_id, delete_at=delete_at)
            await session.execute(statement.on_conflict_do_update(
                index_elements=[MessageDeletionRecord.bot_id, MessageDeletionRecord.chat_id,
                                MessageDeletionRecord.message_id], set_={"delete_at": delete_at}))

    async def cancel_deletion(self, bot_id, chat_id, message_id):
        async with self.session_factory.begin() as session:
            await session.execute(delete(MessageDeletionRecord).where(
                MessageDeletionRecord.bot_id == bot_id, MessageDeletionRecord.chat_id == chat_id,
                MessageDeletionRecord.message_id == message_id))

    async def due_deletions(self, bot_id, now):
        async with self.session_factory() as session:
            statement = select(MessageDeletionRecord.chat_id, MessageDeletionRecord.message_id).where(
                MessageDeletionRecord.bot_id == bot_id, MessageDeletionRecord.delete_at <= now
            ).order_by(MessageDeletionRecord.delete_at).limit(50)
            return [tuple(row) for row in (await session.execute(statement)).all()]

    @asynccontextmanager
    async def locked_deletion(self, bot_id, chat_id, message_id, now):
        async with self.session_factory.begin() as session:
            statement = select(MessageDeletionRecord).where(
                MessageDeletionRecord.bot_id == bot_id, MessageDeletionRecord.chat_id == chat_id,
                MessageDeletionRecord.message_id == message_id, MessageDeletionRecord.delete_at <= now,
            ).with_for_update(skip_locked=True)
            row = await session.scalar(statement)
            yield session, row

    async def register(self, user):
        async with self.session_factory.begin() as session:
            statement = insert(User).values(id=user.id, first_name=user.first_name, username=user.username)
            await session.execute(statement.on_conflict_do_update(
                index_elements=[User.id],
                set_={"first_name": statement.excluded.first_name, "username": statement.excluded.username},
            ))

    async def call(self, service: str, method: str, *args, **kwargs):
        # И загрузка, и проверка свободных мест, и запись защищены одной транзакцией.
        async with self.session_factory.begin() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": STATE_LOCK})
            state, identities, cafe_rows = await load_state(session, service)
            before = state.rows()
            if service == "orders" and method in {"confirm", "confirm_once"}:
                token = args[1]
                if token not in state.orders.confirmed:
                    number = await session.scalar(text("SELECT nextval(pg_get_serial_sequence('flow_orders', 'number'))"))
                    state.orders.number_factory = lambda: number
            error = None
            try:
                target = getattr(state, service)
                if method == "view":
                    result = target
                else:
                    operation = getattr(target, method)
                    arguments = signature(operation).bind(*args, **kwargs)
                    if self.clock is not None and "now" in arguments.arguments:
                        # Запрос мог дождаться блокировки уже после начала паузы.
                        arguments.arguments["now"] = self.clock()
                    result = operation(*arguments.args, **arguments.kwargs)
            except ValueError as caught:
                # Некоторые отказы освобождают просроченный резерв. Это тоже сохраняем.
                error = caught
                result = None
            after = state.rows()
            for model, items in after.items():
                old = before[model]
                for key in old.keys() - items.keys():
                    await session.delete(identities[model][key])
                for key, values in items.items():
                    if key not in old:
                        session.add(model(**values))
                    elif old[key] != values:
                        row = identities[model][key]
                        for name, value in values.items():
                            setattr(row, name, value)
            for row in cafe_rows:
                row.accepts_orders = row.id not in state.cafes.paused
        # Возвращаем результат только после успешного commit, до уведомлений Telegram.
        if error is not None:
            raise error
        return result
