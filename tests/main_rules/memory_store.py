"""Подмена хранения для быстрых тестов обработчиков без PostgreSQL."""

from app.ordering.cafes import cafes
from app.ordering.customer import CustomerService
from app.ordering.orders import orders
from app.ordering.roles import roles


class MemoryStore:
    def __init__(self, order_service=orders, customer_service=None):
        self.services = {"orders": order_service, "roles": roles, "cafes": cafes,
                         "customer": customer_service or CustomerService(order_service)}

    async def call(self, service, method, *args, **kwargs):
        target = self.services[service]
        return target if method == "view" else getattr(target, method)(*args, **kwargs)

    async def schedule_deletion(self, *args):
        pass

    async def cancel_deletion(self, *args):
        pass


class AsyncService:
    def __init__(self, target):
        self.target = target

    def __getattr__(self, name):
        async def execute(*args, **kwargs):
            return self.target if name == "view" else getattr(self.target, name)(*args, **kwargs)
        return execute
