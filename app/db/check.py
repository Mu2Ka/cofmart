"""Проверка подключения и версии схемы: python -m app.db.check."""

import asyncio
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.db.connection import engine
from app.db.model import Base


async def check_database():
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    head = ScriptDirectory.from_config(config).get_current_head()
    try:
        async with engine.connect() as connection:
            database, user = (await connection.execute(text("SELECT current_database(), current_user"))).one()
            tables = await connection.run_sync(lambda conn: inspect(conn).get_table_names(schema="public"))
            missing = set(Base.metadata.tables) - set(tables)
            if missing or "alembic_version" not in tables:
                raise RuntimeError("Схема не готова. Выполните: python -m alembic upgrade head")
            revisions = list((await connection.execute(text("SELECT version_num FROM public.alembic_version"))).scalars())
            if revisions != [head]:
                raise RuntimeError("Версия схемы устарела. Выполните: python -m alembic upgrade head")
            print(f"PostgreSQL: подключение успешно. База: {database}; роль: {user}.")
            print("Таблицы:", ", ".join(sorted(tables)))
            print("Версия схемы:", head)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_database())
