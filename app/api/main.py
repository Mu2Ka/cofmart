from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routers import catalog, orders, slots
from app.api.routers import flow
from app.config import Settings, get_settings
from app.db.session import Database
from app.services.errors import BusinessError


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        config = settings or get_settings()
        if not config.bot_token:
            raise RuntimeError("Добавьте API_BOT для проверки Telegram initData")
        from app.ordering.roles import roles
        from app.ordering.bans import bans
        roles.validate_configuration()
        bans.validate_configuration()
        app.state.settings = config
        app.state.db = database or Database(config.database_url)
        try:
            if app.state.db.engine.dialect.name == 'postgresql':
                from app.db.readiness import ensure_schema
                await ensure_schema(app.state.db)
                from app.ordering.seed import seed
                await seed(app.state.db.sessions)
            yield
        finally:
            if database is None:
                await app.state.db.close()

    application = FastAPI(title="Cofmart API", lifespan=lifespan)

    @application.middleware('http')
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response
    # Origins are read at factory invocation for explicit, predictable CORS configuration.
    config = settings or get_settings()
    application.add_middleware(
        CORSMiddleware, allow_origins=list(config.cors_origins),
        allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"],
    )

    @application.exception_handler(BusinessError)
    async def business_error(request, exc):
        status = 404 if exc.code in {"CAFE_NOT_FOUND", "ITEM_NOT_FOUND", "ORDER_NOT_FOUND"} else 409
        return JSONResponse(status_code=status, content={"code": exc.code, "message": exc.message})

    @application.get("/health")
    async def health():
        async with application.state.db.sessions() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}

    application.include_router(catalog.router)
    application.include_router(slots.router)
    application.include_router(orders.router)
    application.include_router(flow.router)

    @application.exception_handler(ValueError)
    async def workflow_error(request, exc):
        from app.ordering.roles import AccessError
        return JSONResponse(status_code=403 if isinstance(exc, AccessError) else 409, content={'detail': str(exc)})
    return application
