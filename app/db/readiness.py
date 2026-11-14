"""Fail before accepting requests or polling when schema does not match the release."""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.db.models import Base
from app.db import ordering_models
from app.db.import_main import MAIN_REVISION


async def ensure_schema(database):
    config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
    head = ScriptDirectory.from_config(config).get_current_head()
    async with database.engine.connect() as connection:
        tables = set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
        if 'alembic_version' in tables:
            revisions = list((await connection.execute(text('SELECT version_num FROM alembic_version'))).scalars())
            if revisions == [MAIN_REVISION]:
                raise RuntimeError('Нужен перенос базы main: остановите старые процессы и выполните python -m app.db.import_main')
        else:
            revisions = []
        if set(Base.metadata.tables) - tables or revisions != [head]:
            raise RuntimeError('Схема PostgreSQL не готова. Выполните python -m alembic upgrade head')
