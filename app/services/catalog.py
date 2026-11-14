from sqlalchemy import select

from app.db.models import Cafe, MenuItem
from app.services.dto import CafeData, MenuData
from app.services.errors import BusinessError


class CatalogService:
    def __init__(self, sessions):
        self.sessions = sessions

    async def cafes(self) -> list[CafeData]:
        async with self.sessions() as session:
            rows = (await session.scalars(select(Cafe).where(Cafe.active.is_(True)).order_by(Cafe.id))).all()
            return [CafeData(x.id, x.name, x.timezone) for x in rows]

    async def cafe(self, cafe_id: int) -> CafeData:
        async with self.sessions() as session:
            row = await session.get(Cafe, cafe_id)
            if row is None or not row.active:
                raise BusinessError("CAFE_NOT_FOUND", "Неизвестная кофейня!")
            return CafeData(row.id, row.name, row.timezone)

    async def menu(self, cafe_id: int) -> list[MenuData]:
        await self.cafe(cafe_id)
        async with self.sessions() as session:
            rows = (await session.scalars(select(MenuItem).where(
                MenuItem.cafe_id == cafe_id, MenuItem.active.is_(True)
            ).order_by(MenuItem.id))).all()
            return [MenuData(x.id, x.cafe_id, x.legacy_code, x.name, x.price_minor) for x in rows]

    async def legacy_drink(self, cafe_id: int, code: str) -> MenuData:
        for item in await self.menu(cafe_id):
            if item.legacy_code == code:
                return item
        raise BusinessError("ITEM_NOT_FOUND", "Такого напитка нет в меню.")
