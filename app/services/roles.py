"""Права проверяются на сервере при каждом рабочем действии."""

from app import settings
from app.catalog import CAFES
from app.services.bans import bans


class AccessError(ValueError):
    pass


class RoleService:
    def __init__(self):
        self.assignments: dict[int, set[str]] = {}

    def is_admin(self, user_id: int) -> bool:
        return not bans.is_blocked(user_id) and user_id in settings.ADMIN_IDS

    def validate_configuration(self):
        """Останавливаем запуск с понятной ошибкой, если настройки имеют неверный тип."""
        if type(settings.FOLLOW_SCHEDULE) is not bool:
            raise ValueError("FOLLOW_SCHEDULE должен быть True или False, без кавычек.")
        if type(settings.DEFAULT_SLOTS_PER_BREAK) is not int or not 0 <= settings.DEFAULT_SLOTS_PER_BREAK <= 999:
            raise ValueError("DEFAULT_SLOTS_PER_BREAK должен быть целым числом от 0 до 999.")
        if type(settings.SLOT_RESERVATION_SECONDS) is not int or settings.SLOT_RESERVATION_SECONDS <= 0:
            raise ValueError("SLOT_RESERVATION_SECONDS должен быть положительным целым числом.")
        for name in ("SERVICE_MESSAGE_TTL_SECONDS", "NOTIFICATION_TTL_SECONDS"):
            value = getattr(settings, name)
            if type(value) is not int or not 0 <= value <= 86400:
                raise ValueError(f"{name} должен быть целым числом от 0 до 86400 (секунды).")
        if not isinstance(settings.ADMIN_IDS, (set, frozenset)) or any(
            type(user_id) is not int or user_id <= 0 for user_id in settings.ADMIN_IDS
        ):
            raise ValueError("ADMIN_IDS должен быть множеством положительных чисел: {123456789}.")
        if not isinstance(settings.BARISTA_CAFES, dict):
            raise ValueError('BARISTA_CAFES должен быть словарём: {123456789: {"1"}}.')
        for user_id, cafe_ids in settings.BARISTA_CAFES.items():
            if type(user_id) is not int or user_id <= 0:
                raise ValueError("Ключ BARISTA_CAFES — положительный числовой Telegram ID человека.")
            if not isinstance(cafe_ids, (set, frozenset)) or not cafe_ids <= CAFES.keys():
                raise ValueError('Кофейни BARISTA_CAFES задаются множеством строк: {"1", "2"}.')

    def configuration_warnings(self, bot_id: int) -> list[str]:
        if bot_id in settings.ADMIN_IDS or bot_id in settings.BARISTA_CAFES:
            return [
                f"В настройках ролей указан ID самого бота ({bot_id}). "
                "Для ADMIN_IDS и BARISTA_CAFES нужен ID человека из команды /myid."
            ]
        return []

    def barista_cafes(self, user_id: int) -> set[str]:
        if bans.is_blocked(user_id):
            return set()
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
