"""Расписание и окна приёма заказов по новосибирскому времени."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

LOCAL_TIMEZONE = timezone(timedelta(hours=7), "Asia/Novosibirsk")
PAIRS_PER_DAY = 5
CUTOFF_MINUTES = 5


def local_now() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)


@dataclass(frozen=True)
class Break:
    id: str
    title: str
    opens_at: datetime
    starts_at: datetime
    ends_at: datetime

    @property
    def closes_at(self) -> datetime:
        return self.starts_at - timedelta(minutes=CUTOFF_MINUTES)

    def accepts_orders(self, now: datetime) -> bool:
        return self.opens_at <= now < self.closes_at

    @property
    def label(self) -> str:
        return f"{self.title}: {self.starts_at:%H:%M}–{self.ends_at:%H:%M}"


def daily_breaks(day: date) -> list[Break]:
    first_start = datetime.combine(day, time(9), LOCAL_TIMEZONE)
    result = []
    for index in range(PAIRS_PER_DAY):
        start = first_start + timedelta(minutes=110 * index)
        short_start = start + timedelta(minutes=45)
        second_start = short_start + timedelta(minutes=5)
        result.append(Break(
            f"{day:%Y%m%d}-{index + 1}s", f"Перерыв внутри {index + 1}-й пары",
            start, short_start, second_start,
        ))
        if index < PAIRS_PER_DAY - 1:
            long_start = second_start + timedelta(minutes=45)
            result.append(Break(
                f"{day:%Y%m%d}-{index + 1}l", f"После {index + 1}-й пары",
                second_start, long_start, long_start + timedelta(minutes=15),
            ))
    return result


def available_breaks(now: datetime) -> list[Break]:
    return [item for item in daily_breaks(now.astimezone(LOCAL_TIMEZONE).date())
            if item.accepts_orders(now)]


def find_break(break_id: str, now: datetime) -> Break | None:
    return next((item for item in daily_breaks(now.astimezone(LOCAL_TIMEZONE).date())
                 if item.id == break_id), None)


def closed_message(now: datetime) -> str:
    day = now.astimezone(LOCAL_TIMEZONE).date()
    next_break = next((item for item in daily_breaks(day) if item.opens_at > now), None)
    if next_break is None:
        next_break = daily_breaks(day + timedelta(days=1))[0]
    return (
        "Сейчас приём заказов закрыт. "
        f"Следующее окно откроется {next_break.opens_at:%d.%m в %H:%M}.\n"
        "Заказы закрываются за 5 минут до начала перерыва. Время Новосибирска."
    )
