"""Waste and peak-demand detection on curated (de-duplicated, corrected, non-quarantined) readings.

R-IDLE-01  machine sub-meter in the machine's idle power band, no batch running, >= 5 consecutive intervals.
R-PEAK-01  machine sub-meter above 1.3 x nameplate for <= 4 consecutive intervals (coincident heat-up spike).
R-OFF-01   utilities off-shift energy vs a weather-normalised baseline (piecewise degree-hours, fitted on the baseline
           window); days above 1.4 x expected (and > 60 kWh excess) are grouped into OFF_SHIFT_WASTE events.
"""
import numpy as np
import pandas as pd
from scipy.optimize import nnls

from .. import config
from .common import Q, runs
from .reconcile import occupied_flags

IDLE_LO, IDLE_HI, IDLE_MIN_INTERVALS, IDLE_GRACE = 0.70, 1.40, 5, 2
SPIKE_FACTOR, SPIKE_MAX_INTERVALS = 1.30, 4   # nameplate + 30 % inrush allowance
OFF_RATIO, OFF_MIN_EXCESS_KWH = 1.40, 60.0


def _batch_busy(ts, batches):
    t = pd.DatetimeIndex(ts).tz_convert("UTC").tz_localize(None).values
    busy = np.zeros(len(t), dtype=bool)
    for r in batches.itertuples():
        busy |= (t + Q.to_timedelta64() > r.actual_start_utc.to_datetime64()) & (t < r.actual_end_utc.to_datetime64())
    return busy


def run(cr, d, F, window_start, days):
    mach = d["machine"].set_index("machine_id")
    batches = d["production_batch"].dropna(subset=["actual_start_utc"])
    meter = d["meter"]
    idle_rows = []

    for mid in meter[meter["measured_scope"] == "MACHINE"]["meter_id"]:
        s = cr[cr["meter_id"] == mid].sort_values("ts_utc").reset_index(drop=True)
        for machine_id, g in s.groupby("machine_id"):
            g = g.reset_index(drop=True)
            m = mach.loc[machine_id]
            kw = g["avg_kw"].to_numpy()
            usable = ~g["quarantined"].to_numpy()
            busy = _batch_busy(g["ts_utc"], batches[batches["machine_id"] == machine_id])
            idle = usable & ~busy & (kw >= IDLE_LO * m.idle_kw) & (kw <= IDLE_HI * m.idle_kw)
            for a, b in runs(idle):
                if b - a < IDLE_MIN_INTERVALS:
                    continue
                seg = g.iloc[a:b]
                waste = float(((seg["avg_kw"] - m.standby_kw) * 0.25).iloc[IDLE_GRACE:].clip(lower=0).sum())
                cost = float((((seg["avg_kw"] - m.standby_kw) * 0.25).clip(lower=0) * seg["rate"]).iloc[IDLE_GRACE:].sum())
                F.add("HIGH_IDLE_CONSUMPTION", "WASTE", m.plant_id, "machine", machine_id, seg.ts_utc.iloc[0],
                      seg.ts_utc.iloc[-1] + Q, "R-IDLE-01", "RECOMMEND_AUTO_STANDBY", "plant_operator",
                      f"{(b - a) * 15} min idling at {seg['avg_kw'].mean():.1f} kW (idle band {m.idle_kw:.1f} kW, "
                      f"standby {m.standby_kw:.1f} kW) with no batch running", metric_value=(b - a) * 15,
                      metric_unit="minutes", impact_kwh=waste)
                idle_rows.append({"machine_id": machine_id, "plant_id": m.plant_id, "waste_kwh": waste, "waste_cost": cost})

            over = usable & (kw > SPIKE_FACTOR * m.rated_kw)
            for a, b in runs(over):
                if b - a > SPIKE_MAX_INTERVALS:
                    continue
                seg = g.iloc[a:b]
                F.add("PEAK_DEMAND_SPIKE", "WASTE", m.plant_id, "meter", mid, seg.ts_utc.iloc[0], seg.ts_utc.iloc[-1] + Q,
                      "R-PEAK-01", "RECOMMEND_STAGGERED_START", "production_planner",
                      f"{seg['avg_kw'].max():.1f} kW on {machine_id} = x{seg['avg_kw'].max() / m.rated_kw:.2f} nameplate "
                      f"in {', '.join(sorted(set(seg['period'].dropna())))} window", metric_value=float(seg["avg_kw"].max()),
                      metric_unit="kW", impact_kwh=float(((seg["avg_kw"] - m.rated_kw) * 0.25).clip(lower=0).sum()))

    # off-shift utilities, weather normalised
    wx = d["weather_observation"]
    base_end = window_start + pd.Timedelta(days=config.baseline_days(days))
    off_rows = []
    for mid in meter[meter["measured_scope"] == "UTILITIES"]["meter_id"]:
        s = cr[cr["meter_id"] == mid].sort_values("ts_utc").reset_index(drop=True)
        pid = s["plant_id"].iloc[0]
        tz = d["plant"].set_index("plant_id").loc[pid, "timezone"]
        temp = wx[wx["plant_id"] == pid].set_index("ts_utc")["temp_c"]
        s["temp"] = s["ts_utc"].dt.floor("h").map(temp).to_numpy()
        s["off"] = ~occupied_flags(s["ts_utc"], d["shift_instance"], pid)
        s = s[s["off"] & ~s["quarantined"]].copy()
        # piecewise-linear degree-hour model (hinges at 5/10/18 degC heating and 18/24/28 degC cooling)
        T = s["temp"].to_numpy()
        X = np.column_stack([np.ones(len(s))] + [np.maximum(T - b, 0) for b in (18, 24, 28)] +
                            [np.maximum(b - T, 0) for b in (18, 10, 5)])
        tr = (s["ts_utc"] < base_end).to_numpy()
        coef, _ = nnls(X[tr], s["avg_kw"].to_numpy()[tr])  # slopes >= 0 keep extrapolation physical
        s["expected_kwh"] = np.clip(X @ coef, 0.1, None) * 0.25
        s["day"] = s["ts_utc"].dt.tz_convert(tz).dt.date
        daily = s.groupby("day").agg(actual=("interval_kwh", "sum"), expected=("expected_kwh", "sum"),
                                     start=("ts_utc", "min"), end=("ts_utc", "max"), n=("ts_utc", "size"))
        daily["ratio"] = daily["actual"] / daily["expected"]
        daily["excess"] = daily["actual"] - daily["expected"]
        flag = ((daily["ratio"] > OFF_RATIO) & (daily["excess"] > OFF_MIN_EXCESS_KWH)).to_numpy()
        for a, b in runs(flag, max_gap=1):
            seg = daily.iloc[a:b]
            segf = seg[flag[a:b]]
            # a step that persists >= 4 days is structural base load (air leak, stuck valve); a short bounded
            # episode is a schedule override in the BMS
            structural = len(seg) >= 4
            F.add("OFF_SHIFT_WASTE", "WASTE", pid, "meter", mid, segf["start"].iloc[0], segf["end"].iloc[-1] + Q,
                  "R-OFF-01", "RECOMMEND_LEAK_SURVEY" if structural else "RECOMMEND_BMS_SCHEDULE_LOCK",
                  "maintenance_engineer" if structural else "ot_it_admin",
                  f"Off-shift utilities energy x{segf['actual'].sum() / segf['expected'].sum():.2f} of weather-normalised "
                  f"baseline on {len(segf)} day(s); excess {segf['excess'].sum():.0f} kWh "
                  f"({segf['excess'].sum() / max(1, len(segf)):.0f} kWh/day)",
                  metric_value=float(segf["actual"].sum() / segf["expected"].sum()), metric_unit="ratio",
                  impact_kwh=float(segf["excess"].sum()))
        daily["meter_id"] = mid
        daily["plant_id"] = pid
        off_rows.append(daily.reset_index())
    return pd.DataFrame(idle_rows), pd.concat(off_rows, ignore_index=True)
