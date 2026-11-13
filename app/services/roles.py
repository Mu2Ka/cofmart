"""Права проверяются на сервере при каждом рабочем действии."""

from app import settings
from app.catalog import CAFES


class AccessError(ValueError):
    pass


class RoleService:
    def __init__(self):
        self.assignments: dict[int, set[str]] = {}

    def is_admin(self, user_id: int) -> bool:
        return user_id in settings.ADMIN_IDS

    def barista_cafes(self, user_id: int) -> set[str]:
        return set(self.assignments.get(user_id, settings.BARISTA_CAFES.get(user_id, set()))) & CAFES.keys()

    def cafes_for(self, user_id: int) -> set[str]:
        return set(CAFES) if self.is_admin(user_id) else self.barista_cafes(user_id)

    def require_admin(self, user_id: int):
        if not self.is_admin(user_id):
            raise AccessError("Эта функция доступна только администратору.")

    def require_cafe(self, user_id: int, cafe_id: str):
        if cafe_id not in self.cafes_for(user_id):
            raise AccessError("У вас нет доступа к этой кофейне.")

    def assign(self, admin_id: int, user_id: int, cafe_id: str, enabled: bool):
        self.require_admin(admin_id)
        if cafe_id not in CAFES or user_id <= 0:
            raise AccessError("Проверьте Telegram ID и ID кофейни.")
        cafes = self.barista_cafes(user_id)
        if enabled:
            cafes.add(cafe_id)
        else:
            cafes.discard(cafe_id)
        self.assignments[user_id] = cafes

    def staff_for(self, cafe_id: str) -> set[int]:
        candidates = set(settings.BARISTA_CAFES) | set(self.assignments) | settings.ADMIN_IDS
        return {user_id for user_id in candidates if cafe_id in self.cafes_for(user_id)}


roles = RoleService()
