from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
    Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Cafe(Base):
    __tablename__ = "cafes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Novosibirsk")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        UniqueConstraint("cafe_id", "legacy_code"),
        UniqueConstraint("id", "cafe_id"),
        CheckConstraint("price_minor > 0", name="positive_menu_price"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cafe_id: Mapped[int] = mapped_column(ForeignKey("cafes.id"), index=True)
    legacy_code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    price_minor: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)


class PickupSlot(Base):
    __tablename__ = "pickup_slots"
    __table_args__ = (
        UniqueConstraint("cafe_id", "starts_at"),
        UniqueConstraint("id", "cafe_id"),
        CheckConstraint("capacity > 0", name="positive_capacity"),
        CheckConstraint("reserved >= 0 AND reserved <= capacity", name="valid_reservations"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cafe_id: Mapped[int] = mapped_column(ForeignKey("cafes.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int] = mapped_column(Integer)
    reserved: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key"),
        UniqueConstraint("id", "cafe_id"),
        ForeignKeyConstraint(["slot_id", "cafe_id"], ["pickup_slots.id", "pickup_slots.cafe_id"]),
        CheckConstraint("total_minor > 0", name="positive_order_total"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    cafe_id: Mapped[int] = mapped_column(ForeignKey("cafes.id"))
    slot_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    total_minor: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        ForeignKeyConstraint(["order_id", "cafe_id"], ["orders.id", "orders.cafe_id"]),
        ForeignKeyConstraint(["menu_item_id", "cafe_id"], ["menu_items.id", "menu_items.cafe_id"]),
        CheckConstraint("quantity > 0 AND quantity <= 20", name="valid_quantity"),
        CheckConstraint("price_minor > 0", name="positive_item_price"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    cafe_id: Mapped[int] = mapped_column(Integer)
    menu_item_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    price_minor: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
