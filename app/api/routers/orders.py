from fastapi import APIRouter, Depends

from app.api.dependencies import current_user, orders
from app.api.schemas import OrderRequest, PreviewRequest
from app.services.dto import OrderData, PreviewData
from app.services.orders import OrderService

router = APIRouter(prefix="/orders")


@router.post("/preview", response_model=PreviewData)
async def preview(body: PreviewRequest, user: int = Depends(current_user), service: OrderService = Depends(orders)):
    return await service.preview(body.cafe_id, body.item_inputs())


@router.post("", response_model=OrderData)
async def create(body: OrderRequest, user: int = Depends(current_user), service: OrderService = Depends(orders)):
    return await service.create(user, body.command())


@router.get("", response_model=list[OrderData])
async def history(user: int = Depends(current_user), service: OrderService = Depends(orders)):
    return await service.list(user)


@router.get("/{order_id}", response_model=OrderData)
async def detail(order_id: int, user: int = Depends(current_user), service: OrderService = Depends(orders)):
    return await service.get(user, order_id)
