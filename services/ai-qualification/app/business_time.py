"""Business-hours arithmetic for deadlines and message timing (Sunday-Thursday, 09:00-17:00,
Africa/Cairo by default; configurable via BUSINESS_TZ / BUSINESS_HOURS / BUSINESS_DAYS)."""

import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass(frozen=True)
class BusinessCalendar:
    tz: ZoneInfo
    start: time
    end: time
    workdays: frozenset[int]  # datetime.weekday(): Monday=0 ... Sunday=6

    @classmethod
    def from_env(cls) -> "BusinessCalendar":
        start, end = (os.environ.get("BUSINESS_HOURS") or "09:00-17:00").split("-")
        days = os.environ.get("BUSINESS_DAYS") or "6,0,1,2,3"  # Sun-Thu
        return cls(ZoneInfo(os.environ.get("BUSINESS_TZ") or "Africa/Cairo"),
                   time.fromisoformat(start), time.fromisoformat(end),
                   frozenset(int(d) for d in days.split(",")))

    def local(self, moment: datetime) -> datetime:
        if moment.tzinfo is None:
            raise ValueError("timezone-aware datetime required")
        return moment.astimezone(self.tz)

    def is_open(self, moment: datetime) -> bool:
        m = self.local(moment)
        return m.weekday() in self.workdays and self.start <= m.time() < self.end

    def next_open(self, moment: datetime) -> datetime:
        """`moment` if within business hours, else the start of the next business period."""
        m = self.local(moment)
        if m.weekday() in self.workdays and m.time() < self.start:
            return m.replace(hour=self.start.hour, minute=self.start.minute, second=0,
                             microsecond=0)
        if self.is_open(m):
            return m
        day = m.date() + timedelta(days=1)
        while day.weekday() not in self.workdays:
            day += timedelta(days=1)
        return datetime.combine(day, self.start, self.tz)

    def add_hours(self, moment: datetime, hours: float) -> datetime:
        """Add working hours, skipping nights and weekends."""
        current, remaining = self.next_open(moment), timedelta(hours=hours)
        while True:
            close = datetime.combine(current.date(), self.end, self.tz)
            if current + remaining <= close:
                return current + remaining
            remaining -= close - current
            current = self.next_open(close)

    def add_days(self, moment: datetime, days: int) -> datetime:
        """Same local time `days` business days later (snapped into business hours)."""
        current = self.next_open(moment)
        for _ in range(days):
            current += timedelta(days=1)
            while current.weekday() not in self.workdays:
                current += timedelta(days=1)
        return current

    def describe(self, moment: datetime) -> str:
        """Customer-facing, e.g. 'Sunday 4 October at 11:00'."""
        m = self.local(moment)
        return f"{WEEKDAY_NAMES[m.weekday()]} {m.day} {m.strftime('%B')} at {m.strftime('%H:%M')}"
