"""Versioned exchange calendar; unknown years never pretend to be verified sessions."""
import datetime as dt
import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / 'data' / 'trading_calendar.json'


def load_calendar(path=DEFAULT_PATH):
    return json.loads(Path(path).read_text())


def valid_date(value):
    try:
        return dt.date.fromisoformat(value).isoformat() == value
    except (ValueError, TypeError):
        return False


def covered(start, end, calendar):
    return (calendar.get('coverage_start', '') <= start <= end <= calendar.get('coverage_end', ''))


def sessions(start, end, calendar=None):
    calendar = calendar or load_calendar()
    if not covered(start, end, calendar):
        return None
    closed, opened = set(calendar['closed_dates']), set(calendar.get('open_dates', []))
    day, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    out = []
    while day <= last:
        iso = day.isoformat()
        if iso in opened or (day.weekday() < 5 and iso not in closed):
            out.append(iso)
        day += dt.timedelta(days=1)
    return out


def adjacent(start, end, calendar=None):
    days = sessions(start, end, calendar)
    return days == [start, end]
