from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import ARRAY, JSONB


from app.db.models import Base


class User(Base):
    __tablename__ = "flow_users"

    # Telegram ID задаётся самим Telegram.
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
    )

    first_name: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class Cafe(Base):
    __tablename__ = "flow_cafes"

    # Сохраняем привычные ID кофеен: "1", "2".
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))

    accepts_orders: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("true"),
    )


class OrderRecord(Base):
    __tablename__ = "flow_orders"
    __table_args__ = (
        CheckConstraint("status IN ('new','preparing','ready','done','cancelled')", name="order_status"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="order_rating"),
        CheckConstraint("rating IS NULL OR status = 'done'", name="rating_only_done"),
        CheckConstraint("revision >= 0", name="order_revision"),
    )

    number: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token: Mapped[str] = mapped_column(String(16), unique=True)
    key: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[int] = mapped_column(ForeignKey("flow_users.id"), index=True)
    cafe_id: Mapped[str] = mapped_column(ForeignKey("flow_cafes.id"), index=True)
    break_id: Mapped[str] = mapped_column(String(20), index=True)
    # Снимок выбора: названия, цена, комментарий и время выдачи не меняются вместе с меню.
    draft: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer)
    barista_id: Mapped[int | None] = mapped_column(BigInteger)
    rating: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DraftRecord(Base):
    __tablename__ = "flow_order_drafts"

    user_id: Mapped[int] = mapped_column(ForeignKey("flow_users.id"), primary_key=True)
    token: Mapped[str] = mapped_column(String(16), unique=True)
    cafe_id: Mapped[str] = mapped_column(ForeignKey("flow_cafes.id"))
    break_id: Mapped[str] = mapped_column(String(20))
    reserved_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    draft: Mapped[dict] = mapped_column(JSONB)


class SlotLimitRecord(Base):
    __tablename__ = "flow_slot_limits"
    __table_args__ = (CheckConstraint('"limit" BETWEEN 0 AND 999', name="slot_limit_range"),)

    cafe_id: Mapped[str] = mapped_column(ForeignKey("flow_cafes.id"), primary_key=True)
    break_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    limit: Mapped[int] = mapped_column(Integer)
    # Старые callback содержат случайную 64-битную начальную ревизию.
    revision: Mapped[int] = mapped_column(Numeric(30, 0))


class FavoriteRecord(Base):
    __tablename__ = "flow_favorites"
    __table_args__ = (UniqueConstraint("user_id", "cafe_id", "drink_id", name="favorite_variant"),)

    key: Mapped[str] = mapped_column(String(12), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("flow_users.id"), index=True)
    cafe_id: Mapped[str] = mapped_column(ForeignKey("flow_cafes.id"))
    drink_id: Mapped[str] = mapped_column(String(32))
    cafe_name: Mapped[str] = mapped_column(String(120))
    drink_name: Mapped[str] = mapped_column(String(255))


class RoleOverrideRecord(Base):
    __tablename__ = "flow_barista_overrides"

    # Баристу можно назначить до его первого обращения к боту. Пустой список снимает доступ.
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    cafe_ids: Mapped[list[str]] = mapped_column(ARRAY(String(20)))


class StoppedProductRecord(Base):
    __tablename__ = "flow_stopped_products"

    cafe_id: Mapped[str] = mapped_column(ForeignKey("flow_cafes.id"), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(20), primary_key=True)


class SessionRecord(Base):
    __tablename__ = "flow_order_sessions"

    user_id: Mapped[int] = mapped_column(ForeignKey("flow_users.id"), primary_key=True)
    token: Mapped[str | None] = mapped_column(String(8))
    waiting_comment: Mapped[str | None] = mapped_column(String(16))
    slot_edit: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


class MessageDeletionRecord(Base):
    __tablename__ = "flow_message_deletions"

    # Несколько тестовых/рабочих ботов могут использовать одну базу.
    bot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    delete_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
