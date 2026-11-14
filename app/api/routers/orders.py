from fastapi import APIRouter, Depends, HTTPException, Path

from app.api.dependencies import current_user, orders
from app.api.schemas import OrderRequest, PreviewRequest
from app.services.dto import OrderData, PreviewData
from app.services.orders import OrderService

router = APIRouter(prefix="/orders")


@router.post("/preview", response_model=PreviewData, deprecated=True)
async def preview(body: PreviewRequest, user: int = Depends(current_user), service: OrderService = Depends(orders)):
    raise HTTPException(410, 'Оформление обновлено. Переоткройте Mini App; новые заказы используют /flow/action.')


@router.post("", response_model=OrderData, deprecated=True)
async def create(body: OrderRequest, user: int = Depends(current_user), service: OrderService = Depends(orders)):
    raise HTTPException(410, 'Оформление обновлено. Переоткройте Mini App; новые заказы используют /flow/action.')


@router.get("", response_model=list[OrderData])
async def history(user: int = Depends(current_user), service: OrderService = Depends(orders)):
    return await service.list(user)


@router.get("/{order_id}", response_model=OrderData)
async def detail(order_id: int = Path(gt=0, le=2**31-1), user: int = Depends(current_user), service: OrderService = Depends(orders)):
    return await service.get(user, order_id)
