"""Тестовые заказы в памяти. При перезапуске они удаляются."""

from dataclasses import dataclass
from datetime import datetime
from secrets import token_hex

from app.catalog import CAFES, MENU, PRICES
from app.schedule import Break, find_break


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


@dataclass(frozen=True)
class Order:
    number: int
    draft: Draft


class OrderService:
    def __init__(self):
        self.drafts: dict[int, Draft] = {}
        self.confirmed: dict[str, Order] = {}
        self.sessions: dict[int, str] = {}

    def begin(self, user_id: int) -> str:
        self.cancel(user_id)
        session = token_hex(4)
        self.sessions[user_id] = session
        return session

    def valid_session(self, user_id: int, session: str) -> bool:
        return self.sessions.get(user_id) == session

    def cancel(self, user_id: int) -> None:
        self.drafts.pop(user_id, None)
        self.sessions.pop(user_id, None)

    def prepare(self, user_id: int, cafe_id: str, drink_id: str,
                break_id: str, now: datetime) -> Draft:
        if cafe_id not in CAFES or drink_id not in MENU.get(cafe_id, {}):
            raise OrderError("Кофейня или напиток больше недоступны.")
        pickup = find_break(break_id, now)
        if pickup is None or not pickup.accepts_orders(now):
            raise OrderError("Приём на этот перерыв закрыт. Начните новый заказ.")
        draft = Draft(token_hex(8), user_id, cafe_id, drink_id, pickup,
                      PRICES[cafe_id][drink_id], CAFES[cafe_id], MENU[cafe_id][drink_id])
        self.drafts[user_id] = draft
        return draft

    def confirm(self, user_id: int, token: str, now: datetime) -> Order:
        # Повторное нажатие возвращает тот же заказ, даже после закрытия окна.
        existing = self.confirmed.get(token)
        if existing and existing.draft.user_id == user_id:
            return existing
        draft = self.drafts.get(user_id)
        if draft is None or draft.token != token:
            raise OrderError("Это подтверждение устарело. Начните новый заказ.")
        pickup = find_break(draft.pickup.id, now)
        if pickup is None or not pickup.accepts_orders(now):
            self.cancel(user_id)
            raise OrderError("Время заказа истекло: приём закрывается за 5 минут до перерыва.")
        if (draft.drink_id not in MENU.get(draft.cafe_id, {})
                or PRICES.get(draft.cafe_id, {}).get(draft.drink_id) != draft.price):
            self.cancel(user_id)
            raise OrderError("Меню или цена изменились. Начните новый заказ.")
        order = Order(len(self.confirmed) + 1, draft)
        self.confirmed[token] = order
        self.cancel(user_id)
        return order


orders = OrderService()
