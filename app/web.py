"""Local entry point serving the built Mini App and API through one HTTPS tunnel."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.main import create_app
from app.config import Settings
from app.db.session import Database


def create_web_app(settings: Settings | None = None, database: Database | None = None, frontend_dir: Path | None = None) -> FastAPI:
    frontend = frontend_dir or Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
    if not (frontend / 'index.html').is_file():
        raise RuntimeError('Build frontend before starting: start-local.cmd does this automatically.')
    api = create_app(settings, database)

    @asynccontextmanager
    async def lifespan(app):
        async with api.router.lifespan_context(api):
            yield

    application = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    application.mount('/api', api)
    application.mount('/', StaticFiles(directory=frontend, html=True), name='mini-app')
    return application
