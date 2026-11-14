from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CafeData:
    id: int
    name: str
    timezone: str


@dataclass(frozen=True)
class MenuData:
    id: int
    cafe_id: int
    legacy_code: str
    name: str
    price_minor: int


@dataclass(frozen=True)
class SlotData:
    id: int
    starts_at: datetime
    available: int


@dataclass(frozen=True)
class ItemInput:
    menu_item_id: int
    quantity: int


@dataclass(frozen=True)
class ItemData:
    menu_item_id: int
    name: str
    quantity: int
    price_minor: int


@dataclass(frozen=True)
class PreviewData:
    cafe_id: int
    items: list[ItemData]
    total_minor: int


@dataclass(frozen=True)
class OrderCommand:
    cafe_id: int
    slot_id: int
    items: list[ItemInput]
    expected_total_minor: int
    idempotency_key: str


@dataclass(frozen=True)
class OrderData:
    id: int
    cafe_id: int
    cafe_name: str
    timezone: str
    slot_id: int
    starts_at: datetime
    status: str
    total_minor: int
    created_at: datetime
    items: list[ItemData]
