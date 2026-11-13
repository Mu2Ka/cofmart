from app.catalog import CAFES, PRODUCTS
from app.services.roles import roles


class CafeError(ValueError):
    pass


class CafeService:
    def __init__(self):
        self.paused: set[str] = set()
        self.stoplist: set[tuple[str, str]] = set()

    def is_open(self, cafe_id: str) -> bool:
        return cafe_id in CAFES and cafe_id not in self.paused

    def is_available(self, cafe_id: str, product_id: str) -> bool:
        return product_id in PRODUCTS.get(cafe_id, {}) and (cafe_id, product_id) not in self.stoplist

    def require_orderable(self, cafe_id: str, sku: str):
        if not self.is_open(cafe_id):
            raise CafeError("Кофейня временно остановила приём. Выберите другую кофейню.")
        if not self.is_available(cafe_id, sku.split("_", 1)[0]):
            raise CafeError("Напиток закончился. Выберите другой напиток.")

    def set_open(self, actor_id: int, cafe_id: str, enabled: bool):
        roles.require_cafe(actor_id, cafe_id)
        if enabled:
            self.paused.discard(cafe_id)
        else:
            self.paused.add(cafe_id)

    def set_available(self, actor_id: int, cafe_id: str, product_id: str, enabled: bool):
        roles.require_cafe(actor_id, cafe_id)
        if product_id not in PRODUCTS.get(cafe_id, {}):
            raise CafeError("Позиция меню не найдена.")
        key = (cafe_id, product_id)
        if enabled:
            self.stoplist.discard(key)
        else:
            self.stoplist.add(key)


cafes = CafeService()
