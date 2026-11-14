"""Small operational CLI; all IDs are data, never hard-coded routing rules."""
import argparse
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Cafe, MenuItem, PickupSlot
from app.db.session import Database


async def execute(args):
    db = Database(get_settings().database_url)
    try:
        async with db.sessions() as session, session.begin():
            if args.command == "add-cafe":
                ZoneInfo(args.timezone)
                cafe = Cafe(name=args.name, timezone=args.timezone)
                session.add(cafe)
                await session.flush()
                print(f"Cafe ID: {cafe.id}")
                return
            cafe = await session.get(Cafe, args.cafe_id)
            if cafe is None:
                raise ValueError("Кофейня не найдена")
            if args.command == "add-drink":
                if args.price_minor <= 0 or not args.code or len(args.code.encode()) > 20 or ":" in args.code:
                    raise ValueError("Нужны положительная цена и код до 20 байт без двоеточия")
                item = MenuItem(cafe_id=cafe.id, legacy_code=args.code, name=args.name, price_minor=args.price_minor)
                session.add(item)
                await session.flush()
                print(f"Menu item ID: {item.id}")
                return
            start = datetime.fromisoformat(args.start)
            if start.tzinfo is None:
                start = start.replace(tzinfo=ZoneInfo(cafe.timezone))
            if not 1 <= args.count <= 500 or args.interval <= 0 or args.capacity <= 0:
                raise ValueError("Проверьте count (1..500), interval и capacity (>0)")
            added = 0
            for index in range(args.count):
                timestamp = start + timedelta(minutes=index * args.interval)
                exists = await session.scalar(select(PickupSlot.id).where(
                    PickupSlot.cafe_id == cafe.id, PickupSlot.starts_at == timestamp,
                ))
                if exists is None:
                    session.add(PickupSlot(cafe_id=cafe.id, starts_at=timestamp, capacity=args.capacity))
                    added += 1
            print(f"Slots added: {added}")
    finally:
        await db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    cafe = commands.add_parser("add-cafe")
    cafe.add_argument("--name", required=True)
    cafe.add_argument("--timezone", default="Asia/Novosibirsk")
    drink = commands.add_parser("add-drink")
    drink.add_argument("--cafe-id", type=int, required=True)
    drink.add_argument("--code", required=True)
    drink.add_argument("--name", required=True)
    drink.add_argument("--price-minor", type=int, required=True)
    slots = commands.add_parser("add-slots")
    slots.add_argument("--cafe-id", type=int, required=True)
    slots.add_argument("--start", required=True, help="ISO datetime; without offset uses cafe timezone")
    slots.add_argument("--count", type=int, default=12)
    slots.add_argument("--interval", type=int, default=15, help="Minutes")
    slots.add_argument("--capacity", type=int, default=5)
    asyncio.run(execute(parser.parse_args()))


if __name__ == "__main__":
    main()
