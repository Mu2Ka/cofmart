from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class Database:
    def __init__(self, url: str, **engine_options):
        engine_options.setdefault('hide_parameters', True)
        engine_options.setdefault('connect_args', {})
        if url.startswith('postgresql'):
            engine_options['connect_args'].setdefault('timeout', 5)
        self.engine = create_async_engine(url, pool_pre_ping=True, **engine_options)
        if self.engine.dialect.name == "sqlite":
            # SQLite is supported for fast tests, not for production capacity guarantees.
            @event.listens_for(self.engine.sync_engine, "connect")
            def enable_foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def close(self):
        await self.engine.dispose()
