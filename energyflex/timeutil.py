"""Time helpers. Internally the generator works on integer minutes since START (UTC)."""
import pandas as pd

from . import config

START = pd.Timestamp(config.START_UTC)
DAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def end(days):
    return START + pd.Timedelta(days=days)


def local_to_utc(date, hhmm, tz):
    """Local wall-clock time on `date` (HH:MM, '24:00' allowed) -> UTC Timestamp."""
    h, m = (int(x) for x in hhmm.split(":"))
    local = pd.Timestamp(date) + pd.Timedelta(hours=h, minutes=m)
    return local.tz_localize(tz, nonexistent="shift_forward", ambiguous=False).tz_convert("UTC")


def to_min(ts):
    return int((ts - START) // pd.Timedelta(minutes=1))


def from_min(m):
    return START + pd.Timedelta(minutes=int(m))


def mins_to_ts(arr):
    return START + pd.to_timedelta(pd.Series(arr, dtype="int64"), unit="min")


def iso(series):
    """UTC timestamps -> 'YYYY-MM-DDTHH:MM:SSZ' strings (NaT -> None)."""
    s = pd.to_datetime(series, utc=True)
    out = s.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return out.where(s.notna(), None)


def parse(series):
    return pd.to_datetime(series, utc=True, format="%Y-%m-%dT%H:%M:%SZ")
