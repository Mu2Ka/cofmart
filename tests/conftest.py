from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Base, PickupSlot
from app.db.seed import seed
from app.db.session import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await seed(database.sessions)
    async with database.sessions() as session, session.begin():
        session.add(PickupSlot(id=1, cafe_id=1, starts_at=datetime.now(timezone.utc) + timedelta(hours=2), capacity=2))
        session.add(PickupSlot(id=2, cafe_id=2, starts_at=datetime.now(timezone.utc) + timedelta(hours=2), capacity=2))
    yield database
    await database.close()
