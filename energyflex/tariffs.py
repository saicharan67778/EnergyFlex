"""Time-of-use tariff lookup shared by the generator (to place peak scenarios) and the cost engine."""
import numpy as np
import pandas as pd

from .timeutil import DAY_NAMES


def _hm(s):
    h, m = (int(x) for x in s.split(":"))
    return h * 60 + m


def lookup(ts_utc, tariffs, windows, tz):
    """Map UTC interval-start timestamps to (tariff_id, window_id, period, rate) using wall-clock time in `tz`.

    `tariffs` must already be filtered to one plant. Returns a DataFrame aligned with ts_utc; rows with no
    effective tariff or no matching window get NaN (reported as cost-coverage exceptions upstream).
    """
    ts = pd.DatetimeIndex(pd.to_datetime(ts_utc, utc=True))
    local = ts.tz_convert(tz)
    ldate = local.normalize().tz_localize(None)
    dow = np.array(DAY_NAMES)[local.dayofweek.to_numpy()]
    mod = (local.hour * 60 + local.minute).to_numpy()
    n = len(ts)
    out = pd.DataFrame({"tariff_id": pd.Series([None] * n, dtype=object),
                        "window_id": pd.Series([None] * n, dtype=object),
                        "period": pd.Series([None] * n, dtype=object), "rate_per_kwh": np.full(n, np.nan),
                        "match_count": np.zeros(n, dtype=int)})
    for t in tariffs.itertuples():
        eff = ldate >= pd.Timestamp(t.effective_from)
        if t.effective_to is not None and not pd.isna(t.effective_to):
            eff &= ldate <= pd.Timestamp(t.effective_to)
        eff = np.asarray(eff)
        if not eff.any():
            continue
        for w in windows[windows["tariff_id"] == t.tariff_id].itertuples():
            days = set(w.days_of_week.split(","))
            m = eff & np.isin(dow, list(days)) & (mod >= _hm(w.start_local)) & (mod < _hm(w.end_local))
            out.loc[m, "tariff_id"] = t.tariff_id
            out.loc[m, "window_id"] = w.window_id
            out.loc[m, "period"] = w.period
            out.loc[m, "rate_per_kwh"] = w.rate_per_kwh
            out.loc[m, "match_count"] += 1
    return out


def coverage_issues(windows):
    """Every tariff must map each of the 7x1440 local minutes-of-week to exactly one window."""
    issues = []
    for tid, g in windows.groupby("tariff_id"):
        grid = np.zeros((7, 1440), dtype=int)
        for w in g.itertuples():
            for d in w.days_of_week.split(","):
                grid[DAY_NAMES.index(d), _hm(w.start_local):_hm(w.end_local)] += 1
        gaps, overlaps = int((grid == 0).sum()), int((grid > 1).sum())
        if gaps or overlaps:
            issues.append({"tariff_id": tid, "uncovered_min": gaps, "overlap_min": overlaps})
    return issues
