"""Асинхронные точки входа в сервисы, работающие с PostgreSQL.

Каждый метод выполняет одну законченную операцию в PostgresStore. Чистые классы
OrderService / CustomerService / RoleService содержат сами правила и не знают SQL.
Подключение создаётся лениво: импорт обработчиков не требует работающей базы.
"""


def get_store():
    from app.db.connection import session_factory
    from app.db.store import PostgresStore
    from app.schedule import local_now
    return PostgresStore(session_factory, clock=local_now)


class PersistentService:
    def __init__(self, name, store=None):
        self.name = name
        self.store = store

    def __getattr__(self, method):
        if method.startswith("_"):
            raise AttributeError(method)

        async def execute(*args, **kwargs):
            store = self.store
            if store is None:
                store = get_store()
            return await store.call(self.name, method, *args, **kwargs)

        return execute


orders = PersistentService("orders")
customer = PersistentService("customer")
cafes = PersistentService("cafes")
roles = PersistentService("roles")
