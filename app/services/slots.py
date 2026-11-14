from sqlalchemy import func, select

from app.db.models import PickupSlot
from app.services.catalog import CatalogService
from app.services.dto import SlotData


class SlotService:
    def __init__(self, sessions):
        self.sessions = sessions

    async def available(self, cafe_id: int) -> list[SlotData]:
        await CatalogService(self.sessions).cafe(cafe_id)
        async with self.sessions() as session:
            rows = (await session.scalars(select(PickupSlot).where(
                PickupSlot.cafe_id == cafe_id,
                PickupSlot.starts_at > func.now(),
                PickupSlot.reserved < PickupSlot.capacity,
            ).order_by(PickupSlot.starts_at).limit(48))).all()
            return [SlotData(x.id, x.starts_at, x.capacity - x.reserved) for x in rows]
