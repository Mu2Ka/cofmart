from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from app.config import get_database_url

database_url = get_database_url()

engine = create_async_engine(
    database_url,
    pool_pre_ping=True,
    hide_parameters=True,
    connect_args={"timeout": 5},
)
session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,
)
