from fastapi import Header, HTTPException, Request
import json
import logging
from urllib.parse import parse_qsl
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import InvalidInitData, validate_init_data
from app.services.catalog import CatalogService
from app.services.orders import OrderService
from app.services.slots import SlotService


async def current_user(request: Request, authorization: str = Header(default="")) -> int:
    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != "tma":
        raise HTTPException(401, detail="Откройте приложение внутри Telegram.")
    settings = request.app.state.settings
    try:
        uid = validate_init_data(raw, settings.bot_token, settings.init_data_max_age_seconds)
    except InvalidInitData:
        raise HTTPException(401, detail="Сессия истекла. Откройте приложение заново.") from None
    from app.ordering.bans import bans, BLOCK_MESSAGE
    fields = dict(parse_qsl(raw))
    if bans.is_blocked(uid, json.loads(fields['user']).get('username')):
        from app.db.order_store import PostgresStore
        try:
            await PostgresStore(request.app.state.db.sessions).call('orders', 'cancel', uid)
        except (SQLAlchemyError, OSError, TimeoutError):
            logging.getLogger(__name__).warning('Не удалось освободить резерв недоступного аккаунта.')
        raise HTTPException(403, detail=BLOCK_MESSAGE)
    return uid


def catalog(request: Request) -> CatalogService:
    return CatalogService(request.app.state.db.sessions)


def slots(request: Request) -> SlotService:
    return SlotService(request.app.state.db.sessions)


def orders(request: Request) -> OrderService:
    return OrderService(request.app.state.db.sessions)
