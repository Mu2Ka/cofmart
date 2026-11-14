from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import Cafe, MenuItem, Order, OrderItem, PickupSlot
from app.db.seed import seed
from app.services.catalog import CatalogService
from app.services.dto import ItemInput, OrderCommand
from app.services.errors import BusinessError
from app.services.orders import OrderService


def command(**changes):
    return replace(OrderCommand(1, 1, [ItemInput(1, 2)], 57000, "checkout-1"), **changes)


async def test_seed_and_legacy_catalog(db):
    await seed(db.sessions)
    catalog = CatalogService(db.sessions)
    assert [x.name for x in await catalog.cafes()] == ["CaVa", "Порт-Брю"]
    assert (await catalog.legacy_drink(1, "1")).price_minor == 28500
    assert (await catalog.legacy_drink(2, "1")).name == "Американо"
    async with db.sessions() as session, session.begin():
        cafe = Cafe(name="Новая кофейня")
        session.add(cafe)
        await session.flush()
        session.add(MenuItem(cafe_id=cafe.id, legacy_code="1", name="Эспрессо", price_minor=15000))
    assert len(await catalog.cafes()) == 3


async def test_idempotency_history_and_snapshot(db):
    service = OrderService(db.sessions)
    first = await service.create(1001, command())
    second = await service.create(1001, command())
    assert first.id == second.id
    async with db.sessions() as session, session.begin():
        slot = await session.get(PickupSlot, 1)
        assert slot.reserved == 1
        item = await session.get(MenuItem, 1)
        item.price_minor = 30000
        item.name = "Новое название"
    snapshot = await service.get(1001, first.id)
    assert snapshot.items[0].name == "Бамбл"
    assert snapshot.total_minor == 57000
    assert len(await service.list(1001)) == 1
    assert not await service.list(1002)
    with pytest.raises(BusinessError, match="Заказ не найден"):
        await service.get(1002, first.id)
    assert (await service.create(1001, command())).id == first.id
    with pytest.raises(BusinessError) as error:
        await service.create(1001, command(items=[ItemInput(1, 1)], expected_total_minor=30000))
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("changes,code", [
    ({"slot_id": 2}, "SLOT_UNAVAILABLE"),
    ({"expected_total_minor": 1}, "PRICE_CHANGED"),
    ({"items": [ItemInput(3, 1)]}, "ITEM_NOT_FOUND"),
    ({"items": []}, "INVALID_ITEMS"),
    ({"items": [ItemInput(1, 21)]}, "INVALID_ITEMS"),
    ({"items": [ItemInput(1, 11), ItemInput(1, 10)]}, "INVALID_ITEMS"),
])
async def test_invalid_order_does_not_reserve(db, changes, code):
    with pytest.raises(BusinessError) as error:
        await OrderService(db.sessions).create(1001, command(**changes))
    assert error.value.code == code
    async with db.sessions() as session:
        assert (await session.get(PickupSlot, 1)).reserved == 0
        assert await session.scalar(select(func.count()).select_from(Order)) == 0


async def test_expired_and_inactive(db):
    async with db.sessions() as session, session.begin():
        (await session.get(PickupSlot, 1)).starts_at = datetime.now(timezone.utc) - timedelta(hours=1)
    with pytest.raises(BusinessError) as error:
        await OrderService(db.sessions).create(1001, command())
    assert error.value.code == "SLOT_UNAVAILABLE"
    async with db.sessions() as session, session.begin():
        (await session.get(Cafe, 1)).active = False
    with pytest.raises(BusinessError) as error:
        await OrderService(db.sessions).preview(1, [ItemInput(1, 1)])
    assert error.value.code == "CAFE_NOT_FOUND"


async def test_failed_item_insert_rolls_back_reservation(db, monkeypatch):
    original = OrderItem.__init__
    def broken_item(self, **values):
        values["quantity"] = 0
        original(self, **values)
    monkeypatch.setattr(OrderItem, "__init__", broken_item)
    with pytest.raises(IntegrityError):
        await OrderService(db.sessions).create(1001, command())
    async with db.sessions() as session:
        assert (await session.get(PickupSlot, 1)).reserved == 0
        assert await session.scalar(select(func.count()).select_from(Order)) == 0
