"""Первоначальные кофейни: python -m app.db.seed. Существующие записи не меняются."""

import asyncio

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import CAFES
from app.db.connection import engine, session_factory
from app.db.model import Cafe


async def seed_cafes(session: AsyncSession) -> list[str]:
    statement = insert(Cafe).values([{"id": cafe_id, "name": name} for cafe_id, name in CAFES.items()])
    statement = statement.on_conflict_do_nothing(index_elements=[Cafe.id]).returning(Cafe.id)
    return list((await session.execute(statement)).scalars())


async def main():
    try:
        async with session_factory.begin() as session:
            added = await seed_cafes(session)
        print(f"Первоначальные кофейни загружены. Добавлено: {len(added)}.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
