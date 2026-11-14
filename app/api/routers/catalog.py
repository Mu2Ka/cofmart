from fastapi import APIRouter, Depends, Path

from app.api.dependencies import catalog, current_user
from app.services.catalog import CatalogService
from app.services.dto import CafeData, MenuData

router = APIRouter(dependencies=[Depends(current_user)])


@router.get("/cafes", response_model=list[CafeData])
async def cafes(service: CatalogService = Depends(catalog)):
    return await service.cafes()


@router.get("/cafes/{cafe_id}/menu", response_model=list[MenuData])
async def menu(cafe_id: int = Path(gt=0, le=2**31-1), service: CatalogService = Depends(catalog)):
    return await service.menu(cafe_id)
