"""Тестовые заказы в памяти. При перезапуске они удаляются."""

from dataclasses import dataclass, replace
from datetime import datetime
from secrets import token_hex

from app.catalog import CAFES, get_drink
from app.schedule import Break, find_break
from app.services.cafes import CafeError, cafes
from app.services.roles import roles

MAX_COMMENT_LENGTH = 300
STATUSES = {"new": "Новый", "preparing": "Готовится", "ready": "Готов", "done": "Выдан", "cancelled": "Отменён"}
TRANSITIONS = {"new": {"preparing", "cancelled"}, "preparing": {"ready", "cancelled"},
               "ready": {"done", "cancelled"}, "done": set(), "cancelled": set()}


class OrderError(ValueError):
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
    comment: str = ""


@dataclass(frozen=True)
class Order:
    number: int
    draft: Draft
    status: str = "new"
    revision: int = 0
    barista_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OrderService:
    def __init__(self):
        self.drafts: dict[int, Draft] = {}
        self.confirmed: dict[str, Order] = {}
        self.sessions: dict[int, str] = {}
        self.waiting_comments: dict[int, str] = {}
        self.order_tokens: dict[int, str] = {}

    def begin(self, user_id: int) -> str:
        """Новое оформление делает прежние кнопки пользователя недействительными."""
        self.cancel(user_id)
        session = token_hex(4)
        self.sessions[user_id] = session
        return session

    def valid_session(self, user_id: int, session: str) -> bool:
        return self.sessions.get(user_id) == session

    def cancel(self, user_id: int) -> None:
        self.drafts.pop(user_id, None)
        self.sessions.pop(user_id, None)
        self.waiting_comments.pop(user_id, None)

    def prepare(self, user_id: int, cafe_id: str, drink_id: str,
                break_id: str, now: datetime) -> Draft:
        """Черновик фиксирует название и цену, но ещё не создаёт заказ."""
        drink = get_drink(cafe_id, drink_id)
        if cafe_id not in CAFES or drink is None:
            raise OrderError("Кофейня или напиток больше недоступны.")
        self.check_availability(cafe_id, drink_id)
        pickup = find_break(break_id, now)
        if pickup is None:
            raise OrderError("Приём на этот перерыв закрыт. Начните новый заказ.")
        draft = Draft(
            token=token_hex(8), user_id=user_id, cafe_id=cafe_id,
            drink_id=drink_id, pickup=pickup, price=drink.price,
            cafe_name=CAFES[cafe_id], drink_name=drink.name,
        )
        self.drafts[user_id] = draft
        self.waiting_comments.pop(user_id, None)
        return draft

    @staticmethod
    def check_availability(cafe_id: str, drink_id: str):
        try:
            cafes.require_orderable(cafe_id, drink_id)
        except CafeError as error:
            raise OrderError(str(error)) from error

    def get_draft(self, user_id: int, token: str, now: datetime) -> Draft:
        draft = self.drafts.get(user_id)
        if draft is None or draft.token != token:
            raise OrderError("Это оформление устарело. Начните новый заказ.")
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
        order = Order(len(self.confirmed) + 1, draft, created_at=now, updated_at=now)
        self.confirmed[token] = order
        self.order_tokens[order.number] = token
        self.cancel(user_id)
        return order

    def get_order(self, number: int) -> Order:
        token = self.order_tokens.get(number)
        if token is None:
            raise OrderError("Заказ не найден. Возможно, бот был перезапущен.")
        return self.confirmed[token]

    def for_user(self, user_id: int) -> list[Order]:
        return [order for order in reversed(list(self.confirmed.values())) if order.draft.user_id == user_id]

    def for_cafe(self, actor_id: int, cafe_id: str, status: str = "active") -> list[Order]:
        roles.require_cafe(actor_id, cafe_id)
        if status not in STATUSES and status != "active":
            raise OrderError("Неизвестный фильтр заказов.")
        result = [order for order in self.confirmed.values() if order.draft.cafe_id == cafe_id
                  and (order.status in {"new", "preparing", "ready"} if status == "active" else order.status == status)]
        return sorted(result, key=lambda order: (order.draft.pickup.starts_at, order.number))

    def for_staff(self, actor_id: int, number: int) -> Order:
        order = self.get_order(number)
        roles.require_cafe(actor_id, order.draft.cafe_id)
        return order

    def transition(self, actor_id: int, number: int, status: str, revision: int, now: datetime) -> Order:
        order = self.for_staff(actor_id, number)
        if revision != order.revision:
            raise OrderError("Карточка устарела. Откройте заказ заново.")
        if status not in TRANSITIONS[order.status]:
            raise OrderError("Этот переход статуса недоступен.")
        if order.barista_id not in {None, actor_id} and not roles.is_admin(actor_id):
            raise OrderError("Заказ уже взял другой бариста. Изменить его может он или администратор.")
        updated = replace(order, status=status, revision=order.revision + 1,
                          barista_id=order.barista_id or actor_id, updated_at=now)
        self.confirmed[self.order_tokens[number]] = updated
        return updated


orders = OrderService()
