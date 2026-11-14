from app.config import get_settings
from app.db.session import Database

_database = None


def database():
    global _database
    if _database is None:
        _database = Database(get_settings().database_url)
    return _database


async def close():
    global _database
    if _database is not None:
        await _database.close()
        _database = None
