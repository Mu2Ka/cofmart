from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.dto import OrderData, PreviewData


def money(value: int) -> str:
    return f"{value / 100:.2f}".rstrip("0").rstrip(".") + " ₽"


def local_time(value: datetime, zone: str) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(zone)).strftime("%d.%m %H:%M")


def summary(preview: PreviewData) -> str:
    lines = [f"{x.name} × {x.quantity} — {money(x.price_minor * x.quantity)}" for x in preview.items]
    return "\n".join([*lines, f"Итого: {money(preview.total_minor)}"])


def order_text(order: OrderData) -> str:
    return (f"Заказ №{order.id} подтверждён\n{order.cafe_name}\n"
            f"Получение: {local_time(order.starts_at, order.timezone)}\n"
            + summary(PreviewData(order.cafe_id, order.items, order.total_minor)))
