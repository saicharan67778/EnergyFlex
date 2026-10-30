"""Hourly WeatherObservation per plant: seasonal trend + diurnal cycle + AR(1) synoptic anomaly + noise.

Climate parameters are hand-set approximations (see docs/PROVENANCE.md); no external dataset is used.
"""
import numpy as np
import pandas as pd

from .. import config, ids
from ..timeutil import START


def build(plants, days, rng_for):
    rows = []
    n_h = days * 24
    ts = START + pd.to_timedelta(np.arange(n_h), unit="h")
    for p_idx, pc in enumerate(config.PLANTS[: len(plants)]):
        rng = rng_for("weather", p_idx)
        c = pc["climate"]
        local_hour = ts.tz_convert(pc["timezone"]).hour.to_numpy()
        day = np.arange(n_h) / 24.0
        # seasonal trend is anchored to a 90-day year segment so starter and full share the same climate
        seasonal = c["t_start"] + (c["t_end"] - c["t_start"]) * np.clip(day / 90.0, 0, 1)
        diurnal = c["diurnal"] * np.cos(2 * np.pi * (local_hour - 15) / 24.0)
        anom_daily = np.zeros(days)
        for d in range(1, days):
            anom_daily[d] = 0.8 * anom_daily[d - 1] + rng.normal(0, c["noise"])
        anomaly = np.repeat(anom_daily, 24)
        temp = seasonal + diurnal + anomaly + rng.normal(0, 0.4, n_h)
        rh = np.clip(c["rh"] - 1.6 * diurnal - 0.8 * anomaly + rng.normal(0, 4, n_h), 12, 100)
        wind = np.clip(rng.gamma(2.0, 1.6, n_h), 0, 25)
        precip_p = np.clip((rh - 70) / 60, 0.01, 0.4)
        raining = rng.random(n_h) < precip_p
        cond = np.where(raining, np.where(temp < 1.0, "SNOW", "RAIN"), np.where(rh > 72, "CLOUDY", "CLEAR"))
        pid = pc["plant_id"]
        rows.append(pd.DataFrame({
            "observation_id": [ids.weather(pid, t) for t in ts], "plant_id": pid, "ts_utc": ts,
            "temp_c": np.round(temp, 1), "rel_humidity_pct": np.round(rh, 1), "wind_speed_ms": np.round(wind, 1),
            "condition": cond, "source": "SYNTHETIC",
        }))
    return pd.concat(rows, ignore_index=True)
