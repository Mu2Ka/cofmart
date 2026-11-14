"""Правила заказов и слотов. PostgreSQL подключён через services.persistent."""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from secrets import token_hex

from app.catalog import CAFES, get_drink
from app import settings
from app.schedule import Break, find_break, find_configurable_break
from app.services.cafes import CafeError, cafes
from app.services.roles import AccessError, roles

MAX_COMMENT_LENGTH = 300
MAX_SLOT_LIMIT = 999
STATUSES = {"new": "Новый", "preparing": "Готовится", "ready": "Готов", "done": "Выдан", "cancelled": "Отменён"}
TRANSITIONS = {"new": {"preparing", "cancelled"}, "preparing": {"ready", "cancelled"},
               "ready": {"done", "cancelled"}, "done": set(), "cancelled": set()}


class OrderError(ValueError):
    pass


class SlotEditExpired(OrderError):
    pass


@dataclass(frozen=True)
class Draft:
    token: str
    user_id: int
    cafe_id: str
    drink_id: str
    pickup: Break
    price: int
    cafe_name: str
    drink_name: str
    reserved_until: datetime
    comment: str = ""


@dataclass(frozen=True)
class SlotSummary:
    limit: int
    confirmed: int
    reserved: int
    revision: int
    completed: int = 0

    @property
    def active(self) -> int:
        return self.confirmed - self.completed

    @property
    def free(self) -> int:
        return max(0, self.limit - self.confirmed - self.reserved)


@dataclass(frozen=True)
class SlotEdit:
    cafe_id: str
    break_id: str
    revision: int


@dataclass(frozen=True)
class Order:
    number: int
    draft: Draft
    status: str = "new"
    revision: int = 0
    barista_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    key: str = field(default_factory=lambda: token_hex(8))
    rating: int | None = None

    @property
    def reference(self) -> str:
        # Номер удобен человеку, случайная часть не даёт открыть заказ по одному номеру.
        return f"{self.number}-{self.key}"


class OrderService:
    def __init__(self, role_service=roles, cafe_service=cafes, number_factory=None):
        self.roles = role_service
        self.cafes = cafe_service
        self.number_factory = number_factory
        self.drafts: dict[int, Draft] = {}
        self.confirmed: dict[str, Order] = {}
        self.sessions: dict[int, str] = {}
        self.waiting_comments: dict[int, str] = {}
        self.order_tokens: dict[int, str] = {}
        self.slot_limits: dict[tuple[str, str], int] = {}
        self.slot_revisions: dict[tuple[str, str], int] = {}
        # Старые кнопки изменения лимита не должны применяться после перезапуска.
        self.slot_epoch = int(token_hex(8), 16)
        self.slot_edits: dict[int, SlotEdit] = {}

    def begin(self, user_id: int) -> str:
        """Новое оформление делает прежние кнопки пользователя недействительными."""
        self.cancel(user_id)
        session = token_hex(4)
        self.sessions[user_id] = session
        return session

    def valid_session(self, user_id: int, session: str) -> bool:
        return self.sessions.get(user_id) == session

    def navigate(self, user_id: int, session: str) -> bool:
        if not self.valid_session(user_id, session):
            return False
        self.discard_draft(user_id)
        return True

    def cancel_session(self, user_id: int, session: str) -> bool:
        if not self.valid_session(user_id, session):
            return False
        self.cancel(user_id)
        return True

    def cancel(self, user_id: int) -> None:
        self.discard_draft(user_id)
        self.sessions.pop(user_id, None)
        self.slot_edits.pop(user_id, None)

    def discard_draft(self, user_id: int) -> None:
        """Смена выбора закрывает старый черновик, сохраняя текущую сессию меню."""
        self.drafts.pop(user_id, None)
        self.waiting_comments.pop(user_id, None)

    def prepare(self, user_id: int, cafe_id: str, drink_id: str,
                break_id: str, now: datetime, comment: str = "", session: str | None = None) -> Draft:
        """Черновик фиксирует название и цену, но ещё не создаёт заказ."""
        if session is not None and not self.valid_session(user_id, session):
            raise OrderError("Оформление устарело. Начните новый заказ.")
        drink = get_drink(cafe_id, drink_id)
        if not isinstance(comment, str) or len(comment.strip()) > MAX_COMMENT_LENGTH:
            raise OrderError(f"Комментарий должен быть текстом до {MAX_COMMENT_LENGTH} символов.")
        if cafe_id not in CAFES or drink is None:
            raise OrderError("Кофейня или напиток больше недоступны.")
        self.check_availability(cafe_id, drink_id)
        pickup = find_break(break_id, now)
        if pickup is None:
            raise OrderError("Этот период приёма закрыт. Начните новый заказ.")
        if self.slots(cafe_id, pickup.id, now, exclude_user=user_id).free < 1:
            raise OrderError("На этот перерыв свободных слотов нет. Выберите другую кофейню.")
        deadline = pickup.ends_at if pickup.is_test else pickup.closes_at
        draft = Draft(
            token=token_hex(8), user_id=user_id, cafe_id=cafe_id,
            drink_id=drink_id, pickup=pickup, price=drink.price,
            cafe_name=CAFES[cafe_id], drink_name=drink.name,
            reserved_until=min(now + timedelta(seconds=settings.SLOT_RESERVATION_SECONDS), deadline),
            comment=comment.strip(),
        )
        self.drafts[user_id] = draft
        self.waiting_comments.pop(user_id, None)
        return draft

    def check_availability(self, cafe_id: str, drink_id: str):
        try:
            self.cafes.require_orderable(cafe_id, drink_id)
        except CafeError as error:
            raise OrderError(str(error)) from error

    def get_draft(self, user_id: int, token: str, now: datetime) -> Draft:
        draft = self.drafts.get(user_id)
        if draft is None or draft.token != token:
            raise OrderError("Это оформление устарело. Начните новый заказ.")
        if now >= draft.reserved_until:
            self.discard_draft(user_id)
            raise OrderError("Резерв слота истёк. Начните новый заказ.")
        if find_break(draft.pickup.id, now) is None:
            self.cancel(user_id)
            raise OrderError("Время заказа истекло: приём закрывается за 5 минут до перерыва.")
        return draft

    def start_comment(self, user_id: int, token: str, now: datetime) -> Draft:
        draft = self.get_draft(user_id, token, now)
        self.waiting_comments[user_id] = token
        return draft

    def save_comment(self, user_id: int, token: str, text: str | None, now: datetime) -> Draft:
        draft = self.get_draft(user_id, token, now)
        if self.waiting_comments.get(user_id) != token:
            raise OrderError("Ввод комментария уже завершён. Используйте карточку заказа.")
        # None — пользователь нажал «Оставить как есть».
        comment = draft.comment if text is None else text.strip()
        if text is not None and not comment:
            raise OrderError("Напишите комментарий текстом или нажмите «Оставить как есть».")
        if len(comment) > MAX_COMMENT_LENGTH:
            raise OrderError(f"Комментарий слишком длинный. Максимум {MAX_COMMENT_LENGTH} символов.")
        # Новая карточка получает новый токен: старое подтверждение больше не действует.
        updated = replace(draft, token=token_hex(8), comment=comment)
        self.drafts[user_id] = updated
        self.waiting_comments.pop(user_id, None)
        return updated

    def confirm(self, user_id: int, token: str, now: datetime) -> Order:
        # Повторное нажатие возвращает тот же заказ, даже после закрытия окна.
        existing = self.confirmed.get(token)
        if existing and existing.draft.user_id == user_id:
            return existing
        draft = self.get_draft(user_id, token, now)
        if user_id in self.waiting_comments:
            raise OrderError("Сначала отправьте комментарий или нажмите «Оставить как есть».")
        drink = get_drink(draft.cafe_id, draft.drink_id)
        if draft.cafe_id not in CAFES or drink is None or drink.price != draft.price:
            self.cancel(user_id)
            raise OrderError("Меню или цена изменились. Начните новый заказ.")
        self.check_availability(draft.cafe_id, draft.drink_id)
        if self.slots(draft.cafe_id, draft.pickup.id, now, exclude_user=user_id).free < 1:
            self.discard_draft(user_id)
            raise OrderError("Свободных слотов больше нет. Начните новый заказ.")
        number = self.number_factory() if self.number_factory else max(self.order_tokens, default=0) + 1
        order = Order(number, draft, created_at=now, updated_at=now)
        self.confirmed[token] = order
        self.order_tokens[order.number] = token
        self.cancel(user_id)
        return order

    def confirm_once(self, user_id: int, token: str, now: datetime) -> tuple[Order, bool]:
        existing = token in self.confirmed
        return self.confirm(user_id, token, now), not existing

    def session(self, user_id: int) -> str:
        return self.sessions.get(user_id, "")

    def waiting_comment(self, user_id: int) -> str | None:
        return self.waiting_comments.get(user_id)

    def slot_edit(self, user_id: int) -> SlotEdit | None:
        return self.slot_edits.get(user_id)

    def clear_slot_edit(self, user_id: int):
        self.slot_edits.pop(user_id, None)

    def save_slot_edit(self, actor_id: int, limit: int, now: datetime) -> SlotEdit:
        edit = self.slot_edits.get(actor_id)
        if edit is None:
            raise SlotEditExpired("Ввод лимита уже завершён. Откройте перемену заново.")
        try:
            self.set_slot_limit(actor_id, edit.cafe_id, edit.break_id, limit, now, edit.revision)
        except (AccessError, SlotEditExpired):
            self.clear_slot_edit(actor_id)
            raise
        self.clear_slot_edit(actor_id)
        return edit

    def expire_reservations(self, now: datetime):
        for user_id, draft in list(self.drafts.items()):
            if now >= draft.reserved_until or find_break(draft.pickup.id, now) is None:
                self.discard_draft(user_id)

    def slots(self, cafe_id: str, break_id: str, now: datetime,
              exclude_user: int | None = None) -> SlotSummary:
        self.expire_reservations(now)
        confirmed = sum(order.draft.cafe_id == cafe_id and order.draft.pickup.id == break_id
                        and order.status != "cancelled" for order in self.confirmed.values())
        reserved = sum(draft.cafe_id == cafe_id and draft.pickup.id == break_id
                       and user_id != exclude_user for user_id, draft in self.drafts.items())
        key = (cafe_id, break_id)
        completed = sum(order.draft.cafe_id == cafe_id and order.draft.pickup.id == break_id
                        and order.status == "done" for order in self.confirmed.values())
        return SlotSummary(self.slot_limits.get(key, settings.DEFAULT_SLOTS_PER_BREAK),
                           confirmed, reserved, self.slot_revisions.get(key, self.slot_epoch), completed)

    def add_slots(self, actor_id: int, cafe_id: str, break_id: str, count: int,
                  now: datetime, revision: int) -> SlotSummary:
        self.roles.require_cafe(actor_id, cafe_id)
        if type(count) is not int or not 1 <= count <= MAX_SLOT_LIMIT:
            raise OrderError("Число добавляемых слотов должно быть положительным целым числом.")
        current = self.slots(cafe_id, break_id, now)
        # Общий лимит растёт, выданные заказы продолжают расходовать свою часть квоты.
        return self.set_slot_limit(actor_id, cafe_id, break_id, current.limit + count, now, revision)

    def set_slot_limit(self, actor_id: int, cafe_id: str, break_id: str, limit: int,
                       now: datetime, revision: int | None = None) -> SlotSummary:
        self.roles.require_cafe(actor_id, cafe_id)
        if find_configurable_break(break_id, now) is None:
            raise SlotEditExpired("Этот период приёма уже закрыт. Обновите список.")
        if type(limit) is not int or not 0 <= limit <= MAX_SLOT_LIMIT:
            raise OrderError(f"Лимит должен быть целым числом от 0 до {MAX_SLOT_LIMIT}.")
        current = self.slots(cafe_id, break_id, now)
        if revision is not None and current.revision != revision:
            raise SlotEditExpired("Лимит уже изменён другим сотрудником. Обновите карточку.")
        if limit < current.confirmed + current.reserved:
            raise OrderError(f"Уже занято {current.confirmed + current.reserved} слотов "
                             "(заказы и резервы). Нельзя поставить лимит ниже этого числа.")
        key = (cafe_id, break_id)
        self.slot_limits[key] = limit
        self.slot_revisions[key] = current.revision + 1
        return self.slots(cafe_id, break_id, now)

    def start_slot_edit(self, actor_id: int, cafe_id: str, break_id: str, now: datetime):
        self.roles.require_cafe(actor_id, cafe_id)
        if find_configurable_break(break_id, now) is None:
            raise OrderError("Этот период приёма уже закрыт. Обновите список.")
        revision = self.slots(cafe_id, break_id, now).revision
        self.cancel(actor_id)
        self.slot_edits[actor_id] = SlotEdit(cafe_id, break_id, revision)

    def get_order(self, number: int) -> Order:
        token = self.order_tokens.get(number)
        if token is None:
            raise OrderError("Заказ не найден. Обновите список заказов.")
        return self.confirmed[token]

    def resolve_reference(self, reference: str) -> Order:
        number, separator, key = reference.partition("-")
        if not separator or not number.isdecimal():
            raise OrderError("Кнопка заказа устарела. Откройте список заказов заново.")
        order = self.get_order(int(number))
        if key != order.key:
            raise OrderError("Кнопка заказа устарела. Откройте список заказов заново.")
        return order

    def for_user(self, user_id: int) -> list[Order]:
        return [order for order in reversed(list(self.confirmed.values())) if order.draft.user_id == user_id]

    def own_order(self, user_id: int, reference: str) -> Order:
        order = self.resolve_reference(reference)
        if order.draft.user_id != user_id:
            raise OrderError("Этот заказ принадлежит другому пользователю.")
        return order

    def rate(self, user_id: int, reference: str, rating: int) -> Order:
        order = self.own_order(user_id, reference)
        if order.status != "done":
            raise OrderError("Оценить можно только выданный заказ.")
        if type(rating) is not int or not 1 <= rating <= 5:
            raise OrderError("Выберите оценку от 1 до 5.")
        updated = replace(order, rating=rating)
        self.confirmed[self.order_tokens[order.number]] = updated
        return updated

    def for_cafe(self, actor_id: int, cafe_id: str, status: str = "active") -> list[Order]:
        self.roles.require_cafe(actor_id, cafe_id)
        if status not in STATUSES and status != "active":
            raise OrderError("Неизвестный фильтр заказов.")
        result = [order for order in self.confirmed.values() if order.draft.cafe_id == cafe_id
                  and (order.status in {"new", "preparing", "ready"} if status == "active" else order.status == status)]
        return sorted(result, key=lambda order: (order.draft.pickup.starts_at, order.number))

    def for_staff(self, actor_id: int, number: int) -> Order:
        order = self.get_order(number)
        self.roles.require_cafe(actor_id, order.draft.cafe_id)
        return order

    def rating_summary(self, actor_id: int, cafe_id: str) -> tuple[int, float | None]:
        ratings = [order.rating for order in self.for_cafe(actor_id, cafe_id, "done")
                   if order.rating is not None]
        return len(ratings), sum(ratings) / len(ratings) if ratings else None

    def transition(self, actor_id: int, number: int, status: str, revision: int, now: datetime) -> Order:
        order = self.for_staff(actor_id, number)
        if revision != order.revision:
            raise OrderError("Карточка устарела. Откройте заказ заново.")
        if status not in TRANSITIONS[order.status]:
            raise OrderError("Этот переход статуса недоступен.")
        if order.barista_id not in {None, actor_id} and not self.roles.is_admin(actor_id):
            raise OrderError("Заказ уже взял другой бариста. Изменить его может он или администратор.")
        updated = replace(order, status=status, revision=order.revision + 1,
                          barista_id=order.barista_id or actor_id, updated_at=now)
        self.confirmed[self.order_tokens[number]] = updated
        return updated


orders = OrderService()
