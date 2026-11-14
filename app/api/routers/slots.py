from fastapi import APIRouter, Depends

from app.api.dependencies import current_user, slots
from app.services.dto import SlotData
from app.services.slots import SlotService

router = APIRouter(dependencies=[Depends(current_user)])


@router.get("/cafes/{cafe_id}/slots", response_model=list[SlotData])
async def available(cafe_id: int, service: SlotService = Depends(slots)):
    return await service.available(cafe_id)
