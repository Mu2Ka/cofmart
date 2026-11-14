"""Idempotent initial catalogue import. Never overwrites an edited price."""
import asyncio

from sqlalchemy import select, text

from app.catalog import CAFES, MENU, PRICES
from app.config import get_settings
from app.db.models import Cafe, MenuItem
from app.db.session import Database


async def seed(sessions):
    async with sessions() as session, session.begin():
        for cafe_id, name in CAFES.items():
            if await session.get(Cafe, int(cafe_id)) is None:
                session.add(Cafe(id=int(cafe_id), name=name))
                await session.flush()
            for code, drink_name in MENU[cafe_id].items():
                item = await session.scalar(select(MenuItem).where(
                    MenuItem.cafe_id == int(cafe_id), MenuItem.legacy_code == code,
                ))
                if item is None:
                    session.add(MenuItem(
                        cafe_id=int(cafe_id), legacy_code=code, name=drink_name,
                        price_minor=PRICES[cafe_id][code] * 100,
                    ))
        await session.flush()
        if session.bind.dialect.name == "postgresql":
            # Explicit legacy cafe IDs must not leave the SERIAL sequence at 1.
            await session.execute(text(
                "SELECT setval(pg_get_serial_sequence('cafes', 'id'), "
                "GREATEST((SELECT MAX(id) FROM cafes), 1))"
            ))


async def main():
    db = Database(get_settings().database_url)
    try:
        await seed(db.sessions)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
