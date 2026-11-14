import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.db.models import Base, Cafe, Order, PickupSlot
from app.db.seed import seed
from app.db.session import Database
from app.services.dto import ItemInput, OrderCommand
from app.services.errors import BusinessError
from app.services.orders import OrderService

pytestmark = pytest.mark.postgres


@pytest.fixture
async def pgdb():
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.skip("Set TEST_DATABASE_URL for real PostgreSQL concurrency tests")
    # Unique schema isolates tests from all pre-existing tables, including the catalogue.
    schema = "test_" + uuid4().hex
    admin = Database(url)
    async with admin.engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    db = Database(url, connect_args={"server_settings": {"search_path": schema}}, pool_size=10, max_overflow=10)
    try:
        async with db.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await seed(db.sessions)
        async with db.sessions() as session, session.begin():
            session.add(PickupSlot(id=1, cafe_id=1, starts_at=datetime.now(timezone.utc) + timedelta(hours=1), capacity=1))
        yield db
    finally:
        await db.close()
        async with admin.engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.close()


def checkout(key):
    return OrderCommand(1, 1, [ItemInput(1, 1)], 28500, key)


async def test_only_one_customer_gets_last_place(pgdb):
    # Separate services/pools represent independent bot and API processes.
    api_db = Database(os.environ["TEST_DATABASE_URL"], connect_args={
        "server_settings": {"search_path": (await _schema(pgdb))},
    })
    try:
        bot = OrderService(pgdb.sessions)
        api = OrderService(api_db.sessions)
        results = await asyncio.gather(*[
            (bot if i % 2 else api).create(1000 + i, checkout(f"request-{i}")) for i in range(12)
        ], return_exceptions=True)
        assert sum(not isinstance(x, Exception) for x in results) == 1, results
        assert all(not isinstance(x, Exception) or isinstance(x, BusinessError) and x.code == "SLOT_UNAVAILABLE" for x in results)
        async with pgdb.sessions() as session:
            assert (await session.get(PickupSlot, 1)).reserved == 1
            assert await session.scalar(select(func.count()).select_from(Order)) == 1
    finally:
        await api_db.close()


async def _schema(db):
    async with db.sessions() as session:
        return await session.scalar(text("SELECT current_schema()"))


@pytest.mark.parametrize("capacity", [1, 8])
async def test_duplicate_concurrent_checkout_reserves_once(pgdb, capacity):
    async with pgdb.sessions() as session, session.begin():
        (await session.get(PickupSlot, 1)).capacity = capacity
    service = OrderService(pgdb.sessions)
    results = await asyncio.gather(*[service.create(1001, checkout("same-key")) for _ in range(8)])
    assert len({x.id for x in results}) == 1
    async with pgdb.sessions() as session:
        assert (await session.get(PickupSlot, 1)).reserved == 1
        cafe = Cafe(name="Третья кофейня")
        session.add(cafe)
        await session.flush()
        assert cafe.id > 2
