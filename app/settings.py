"""Настройки бота"""

# True — пауза за 5 минут до короткого перерыва и до его конца; False — тест без пауз.
FOLLOW_SCHEDULE = True
DEFAULT_SLOTS_PER_BREAK = 10
SLOT_RESERVATION_SECONDS = 120
# 0 отключает автоматическое удаление сообщений соответствующего типа.
SERVICE_MESSAGE_TTL_SECONDS = 60
NOTIFICATION_TTL_SECONDS = 300

# Username указываются без @. Сравнение нечувствительно к регистру.
BLOCKED_USERNAMES: set[str] = set()
# Если известны числовые ID, добавьте их сюда: это не зависит от смены username.
BLOCKED_USER_IDS: set[int] = set()

# Узнать свой ID: /myid. После изменения этих настроек перезапустите бота.
ADMIN_IDS: set[int] = set()
# Telegram ID баристы -> ID доступных ему кофеен (1 = CaVa, 2 = Порт-Брю).
BARISTA_CAFES: dict[int, set[str]] = {}
# Пример: BARISTA_CAFES = {123456789: {"1"}, 987654321: {"2"}}

# На конкретном компьютере права и персональные списки можно переопределить локально.
try:
    from app.local_settings import ADMIN_IDS, BARISTA_CAFES, BLOCKED_USERNAMES, BLOCKED_USER_IDS
except ModuleNotFoundError as error:
    if error.name != "app.local_settings":
        raise
