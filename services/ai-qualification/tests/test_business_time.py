from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.business_time import BusinessCalendar

CAIRO = ZoneInfo("Africa/Cairo")
CAL = BusinessCalendar(CAIRO, datetime.strptime("09:00", "%H:%M").time(),
                       datetime.strptime("17:00", "%H:%M").time(), frozenset({6, 0, 1, 2, 3}))


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=CAIRO)  # Oct 2026: 4th is a Sunday


@pytest.mark.parametrize(("moment", "is_open"), [
    (at(4, 9), True), (at(4, 16, 59), True), (at(4, 17), False), (at(4, 8, 59), False),
    (at(2, 12), False),  # Friday
    (at(3, 12), False),  # Saturday
])
def test_is_open(moment, is_open):
    assert CAL.is_open(moment) is is_open


@pytest.mark.parametrize(("moment", "expected"), [
    (at(4, 10), at(4, 10)), (at(4, 7), at(4, 9)), (at(4, 18), at(5, 9)),
    (at(8, 17, 30), at(11, 9)),  # Thursday evening -> Sunday
    (at(2, 12), at(4, 9)),
])
def test_next_open(moment, expected):
    assert CAL.next_open(moment) == expected


@pytest.mark.parametrize(("moment", "hours", "expected"), [
    (at(4, 10), 2, at(4, 12)),
    (at(4, 16), 2, at(5, 10)),       # 1h today, 1h tomorrow
    (at(8, 16, 30), 2, at(11, 10, 30)),  # Thursday -> Sunday
    (at(3, 20), 2, at(4, 11)),       # Saturday night -> Sunday
])
def test_add_hours(moment, hours, expected):
    assert CAL.add_hours(moment, hours) == expected


def test_add_days_skips_weekend():
    assert CAL.add_days(at(8, 11), 1) == at(11, 11)
    assert CAL.add_days(at(4, 11), 3) == at(7, 11)


def test_utc_input_is_converted():
    utc = datetime(2026, 10, 4, 7, 0, tzinfo=ZoneInfo("UTC"))  # 10:00 Cairo (UTC+3 in Oct)
    assert CAL.is_open(utc) and CAL.local(utc).hour == 10


def test_describe():
    assert CAL.describe(at(4, 11)) == "Sunday 4 October at 11:00"


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        CAL.is_open(datetime(2026, 10, 4, 10))
