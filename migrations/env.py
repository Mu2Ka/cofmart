import asyncio

from alembic import context

from app.db.connection import engine
from app.db.model import Base


def run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_online():
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


def run_offline():
    context.configure(
        url=engine.url,
        target_metadata=Base.metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


existing_connection = context.config.attributes.get("connection")
if existing_connection is not None:
    run_migrations(existing_connection)
elif context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
