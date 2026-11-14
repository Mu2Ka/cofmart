"""Правила избранного и повтора заказов; хранение подключается отдельно."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from secrets import token_hex

from app.ordering.catalog import CAFES, get_drink
from app.ordering.schedule import available_breaks, closed_message
from app.ordering.orders import Draft, OrderService, orders

MAX_FAVORITES = 30


class CustomerError(ValueError):
    pass


@dataclass(frozen=True)
class Favorite:
    key: str
    cafe_id: str
    drink_id: str
    cafe_name: str
    drink_name: str


@dataclass(frozen=True)
class Selection:
    cafe_id: str
    drink_id: str
    comment: str = ""


class CustomerService:
    def __init__(self, order_service: OrderService):
        self.orders = order_service
        self.favorites: dict[int, dict[str, Favorite]] = {}

    def add(self, user_id: int, cafe_id: str, drink_id: str) -> Favorite:
        drink = get_drink(cafe_id, drink_id)
        if drink is None or cafe_id not in CAFES:
            raise CustomerError("Напиток больше не представлен в меню.")
        items = self.favorites.setdefault(user_id, {})
        for favorite in items.values():
            if (favorite.cafe_id, favorite.drink_id) == (cafe_id, drink_id):
                return favorite
        if len(items) >= MAX_FAVORITES:
            raise CustomerError(f"В избранном уже {MAX_FAVORITES} напитков. Сначала удалите один из них.")
        favorite = Favorite(token_hex(6), cafe_id, drink_id, CAFES[cafe_id], drink.name)
        items[favorite.key] = favorite
        return favorite

    def add_order(self, user_id: int, reference: str) -> Favorite:
        order = self.orders.own_order(user_id, reference)
        return self.add(user_id, order.draft.cafe_id, order.draft.drink_id)

    def add_draft(self, user_id: int, token: str, now: datetime) -> Favorite:
        draft = self.orders.get_draft(user_id, token, now)
        return self.add(user_id, draft.cafe_id, draft.drink_id)

    def list(self, user_id: int) -> list[Favorite]:
        return list(self.favorites.get(user_id, {}).values())

    def get(self, user_id: int, key: str) -> Favorite:
        favorite = self.favorites.get(user_id, {}).get(key)
        if favorite is None:
            raise CustomerError("Избранный напиток не найден. Возможно, он удалён.")
        return favorite

    def remove(self, user_id: int, key: str):
        self.get(user_id, key)
        del self.favorites[user_id][key]

    def selection(self, user_id: int, kind: str, key: str) -> Selection:
        if kind == "r":
            order = self.orders.own_order(user_id, key)
            return Selection(order.draft.cafe_id, order.draft.drink_id, order.draft.comment)
        if kind == "f":
            favorite = self.get(user_id, key)
            return Selection(favorite.cafe_id, favorite.drink_id)
        raise CustomerError("Неизвестный способ повторения заказа.")

    def prepare(self, user_id: int, kind: str, key: str, break_id: str, now: datetime,
                session: str | None = None) -> Draft:
        selection = self.selection(user_id, kind, key)
        return self.orders.prepare(user_id, selection.cafe_id, selection.drink_id,
                                   break_id, now, comment=selection.comment, session=session)

    def prepare_shortcut(self, user_id: int, kind: str, key: str, now: datetime) -> Draft:
        selection = self.selection(user_id, kind, key)
        periods = available_breaks(now)
        if not periods:
            raise CustomerError(closed_message(now))
        return self.orders.prepare_new(user_id, selection.cafe_id, selection.drink_id,
                                       periods[0].id, now, comment=selection.comment)


customer = CustomerService(orders)
