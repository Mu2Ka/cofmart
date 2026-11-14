import hashlib
import json
from dataclasses import asdict

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.db.models import Cafe, MenuItem, Order, OrderItem, PickupSlot, User
from app.services.dto import ItemData, ItemInput, OrderCommand, OrderData, PreviewData
from app.services.errors import BusinessError


class OrderService:
    def __init__(self, sessions):
        self.sessions = sessions

    @staticmethod
    def normalize(items: list[ItemInput]) -> list[ItemInput]:
        if not items or len(items) > 20:
            raise BusinessError("INVALID_ITEMS", "В заказе должно быть от 1 до 20 позиций.")
        quantities: dict[int, int] = {}
        for item in items:
            if type(item.menu_item_id) is not int or item.menu_item_id <= 0 or type(item.quantity) is not int or not 1 <= item.quantity <= 20:
                raise BusinessError("INVALID_ITEMS", "Количество напитков должно быть от 1 до 20.")
            quantities[item.menu_item_id] = quantities.get(item.menu_item_id, 0) + item.quantity
        if any(q > 20 for q in quantities.values()) or sum(quantities.values()) > 20:
            raise BusinessError("INVALID_ITEMS", "В заказе может быть не более 20 напитков.")
        return [ItemInput(k, v) for k, v in sorted(quantities.items())]

    async def _preview(self, session, cafe_id, items, *, lock=False) -> PreviewData:
        cafe_query = select(Cafe).where(Cafe.id == cafe_id, Cafe.active.is_(True))
        if lock:
            cafe_query = cafe_query.with_for_update(read=True)
        if await session.scalar(cafe_query) is None:
            raise BusinessError("CAFE_NOT_FOUND", "Неизвестная кофейня!")
        query = select(MenuItem).where(
            MenuItem.id.in_([x.menu_item_id for x in items]),
            MenuItem.cafe_id == cafe_id, MenuItem.active.is_(True),
        ).order_by(MenuItem.id)
        if lock:
            query = query.with_for_update(read=True)
        menu = {x.id: x for x in (await session.scalars(query)).all()}
        if len(menu) != len(items):
            raise BusinessError("ITEM_NOT_FOUND", "Напиток недоступен или относится к другой кофейне.")
        lines = [ItemData(x.menu_item_id, menu[x.menu_item_id].name, x.quantity, menu[x.menu_item_id].price_minor) for x in items]
        return PreviewData(cafe_id, lines, sum(x.quantity * x.price_minor for x in lines))

    async def preview(self, cafe_id: int, items: list[ItemInput]) -> PreviewData:
        items = self.normalize(items)
        async with self.sessions() as session:
            return await self._preview(session, cafe_id, items)

    async def _existing(self, session, telegram_id, key):
        return await session.scalar(select(Order).join(User).where(
            User.telegram_id == telegram_id, Order.idempotency_key == key,
        ))

    @staticmethod
    def _check_hash(order, request_hash):
        if order.request_hash != request_hash:
            raise BusinessError("IDEMPOTENCY_CONFLICT", "Этот ключ уже использован для другого заказа.")

    async def _data(self, session, order) -> OrderData:
        slot = await session.get(PickupSlot, order.slot_id)
        cafe = await session.get(Cafe, order.cafe_id)
        items = (await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id))).all()
        return OrderData(
            order.id, order.cafe_id, cafe.name, cafe.timezone, slot.id, slot.starts_at,
            order.status, order.total_minor, order.created_at,
            [ItemData(x.menu_item_id, x.name, x.quantity, x.price_minor) for x in items],
        )

    async def create(self, telegram_id: int, command: OrderCommand) -> OrderData:
        if type(telegram_id) is not int or telegram_id <= 0:
            raise BusinessError("INVALID_USER", "Не удалось определить пользователя.")
        if not 1 <= len(command.idempotency_key) <= 64:
            raise BusinessError("INVALID_KEY", "Некорректный ключ оформления.")
        items = self.normalize(command.items)
        payload = {
            "cafe_id": command.cafe_id, "slot_id": command.slot_id,
            "items": [asdict(x) for x in items], "expected_total_minor": command.expected_total_minor,
        }
        request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        # Unique user/key constraints arbitrate duplicate requests across processes.
        # A losing transaction rolls back its slot update before returning the winner.
        for attempt in range(3):
            try:
                async with self.sessions() as session, session.begin():
                    existing = await self._existing(session, telegram_id, command.idempotency_key)
                    if existing:
                        self._check_hash(existing, request_hash)
                        return await self._data(session, existing)
                    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
                    if user is None:
                        user = User(telegram_id=telegram_id)
                        session.add(user)
                        await session.flush()
                    preview = await self._preview(session, command.cafe_id, items, lock=True)
                    if preview.total_minor != command.expected_total_minor:
                        raise BusinessError("PRICE_CHANGED", "Цена изменилась. Обновите расчёт и подтвердите заказ снова.")
                    reserved_id = await session.scalar(update(PickupSlot).where(
                        PickupSlot.id == command.slot_id, PickupSlot.cafe_id == command.cafe_id,
                        PickupSlot.starts_at > func.now(), PickupSlot.reserved < PickupSlot.capacity,
                    ).values(reserved=PickupSlot.reserved + 1).returning(PickupSlot.id))
                    if reserved_id is None:
                        # Another identical request may have consumed the last place.
                        existing = await self._existing(session, telegram_id, command.idempotency_key)
                        if existing:
                            self._check_hash(existing, request_hash)
                            return await self._data(session, existing)
                        raise BusinessError("SLOT_UNAVAILABLE", "Это время уже недоступно. Выберите другое.")
                    order = Order(
                        user_id=user.id, cafe_id=command.cafe_id, slot_id=command.slot_id,
                        total_minor=preview.total_minor, idempotency_key=command.idempotency_key,
                        request_hash=request_hash,
                    )
                    session.add(order)
                    await session.flush()
                    session.add_all([OrderItem(
                        order_id=order.id, cafe_id=command.cafe_id, menu_item_id=x.menu_item_id,
                        name=x.name, quantity=x.quantity, price_minor=x.price_minor,
                    ) for x in preview.items])
                    await session.flush()
                    return await self._data(session, order)
            except IntegrityError:
                async with self.sessions() as session:
                    existing = await self._existing(session, telegram_id, command.idempotency_key)
                    if existing:
                        self._check_hash(existing, request_hash)
                        return await self._data(session, existing)
                if attempt == 2:
                    raise
        raise RuntimeError("Unreachable")

    async def list(self, telegram_id: int, limit: int = 50) -> list[OrderData]:
        async with self.sessions() as session:
            orders = (await session.scalars(select(Order).join(User).where(
                User.telegram_id == telegram_id,
            ).order_by(Order.id.desc()).limit(limit))).all()
            return [await self._data(session, x) for x in orders]

    async def get(self, telegram_id: int, order_id: int) -> OrderData:
        async with self.sessions() as session:
            order = await session.scalar(select(Order).join(User).where(
                Order.id == order_id, User.telegram_id == telegram_id,
            ))
            if order is None:
                raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден.")
            return await self._data(session, order)
