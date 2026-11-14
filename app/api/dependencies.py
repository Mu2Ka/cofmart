from fastapi import Header, HTTPException, Request

from app.api.auth import InvalidInitData, validate_init_data
from app.services.catalog import CatalogService
from app.services.orders import OrderService
from app.services.slots import SlotService


def current_user(request: Request, authorization: str = Header(default="")) -> int:
    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != "tma":
        raise HTTPException(401, detail="Откройте приложение внутри Telegram.")
    settings = request.app.state.settings
    try:
        return validate_init_data(raw, settings.bot_token, settings.init_data_max_age_seconds)
    except InvalidInitData:
        raise HTTPException(401, detail="Сессия истекла. Откройте приложение заново.") from None


def catalog(request: Request) -> CatalogService:
    return CatalogService(request.app.state.db.sessions)


def slots(request: Request) -> SlotService:
    return SlotService(request.app.state.db.sessions)


def orders(request: Request) -> OrderService:
    return OrderService(request.app.state.db.sessions)
