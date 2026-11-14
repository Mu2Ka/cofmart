import asyncio

from alembic import context

from app.config import get_settings
from app.db.models import Base
from app.db.session import Database


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    db = Database(get_settings().database_url)
    try:
        async with db.engine.connect() as connection:
            await connection.run_sync(run)
    finally:
        await db.close()


if context.is_offline_mode():
    context.configure(url=get_settings().database_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
