import asyncio
from sqlalchemy.dialects.postgresql import insert
from app.db.ordering_connection import database, close
from app.db.ordering_models import Cafe
from app.ordering.catalog import CAFES


async def seed(sessions):
    async with sessions.begin() as session:
        await session.execute(insert(Cafe).values([
            {'id': key, 'name': name} for key, name in CAFES.items()
        ]).on_conflict_do_nothing(index_elements=[Cafe.id]))


async def main():
    try:
        await seed(database().sessions)
    finally:
        await close()


if __name__ == '__main__':
    asyncio.run(main())
