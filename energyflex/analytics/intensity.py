"""Batch energy attribution and energy intensity (kWh per unit of output).

Batch kWh = machine sub-meter energy pro-rated by the overlap of each 15-min interval with the batch's actual
run window (the meter is resolved through the effective-dated bridge, so the replacement machine gets its own
history). Intensity = kWh / produced units (physics) and kWh / good units (cost of quality).
R-INT-01: rolling median (5 batches) of intensity / (machine, product) baseline > 1.10 -> INTENSITY_DRIFT.
"""
import numpy as np
import pandas as pd

from .. import config
from .common import Q, runs

DRIFT_RATIO = 1.10
ROLL = 5


def _cum(series_ts, values):
    """Cumulative curve at interval edges for np.interp (seconds since epoch)."""
    t = series_ts.astype("int64").to_numpy() / 1e9
    edges = np.concatenate([t, [t[-1] + 900]])
    return edges, np.concatenate([[0.0], np.cumsum(values)])


def run(cr, d, F, window_start, days):
    batch, mmap, maint = d["production_batch"], d["meter_machine_map"], d["maintenance_event"]
    b = batch[batch["status"] != "CANCELLED"].copy()
    b = b.merge(mmap[["meter_id", "machine_id", "effective_from", "effective_to"]], on="machine_id")
    b = b[(b["actual_start_utc"] >= b["effective_from"]) &
          (b["effective_to"].isna() | (b["actual_start_utc"] < b["effective_to"]))]
    out = []
    for mid, g in b.groupby("meter_id"):
        s = cr[cr["meter_id"] == mid].sort_values("ts_utc")
        e_edges, e_cum = _cum(s["ts_utc"], s["interval_kwh"].to_numpy())
        _, c_cum = _cum(s["ts_utc"], s["cost"].fillna(0).to_numpy())
        _, p_cum = _cum(s["ts_utc"], (s["interval_kwh"] * (s["period"] == "PEAK")).to_numpy())
        _, q_cum = _cum(s["ts_utc"], s["quarantined"].astype(float).to_numpy())
        a = g["actual_start_utc"].astype("int64").to_numpy() / 1e9
        z = g["actual_end_utc"].astype("int64").to_numpy() / 1e9
        g = g.assign(kwh=np.interp(z, e_edges, e_cum) - np.interp(a, e_edges, e_cum),
                     energy_cost=np.interp(z, e_edges, c_cum) - np.interp(a, e_edges, c_cum),
                     kwh_peak=np.interp(z, e_edges, p_cum) - np.interp(a, e_edges, p_cum),
                     reliable=(np.interp(z, e_edges, q_cum) - np.interp(a, e_edges, q_cum)) == 0)
        out.append(g)
    bi = pd.concat(out, ignore_index=True)
    bi["run_hours"] = (bi["actual_end_utc"] - bi["actual_start_utc"]) / pd.Timedelta(hours=1)
    bi["kwh_per_unit"] = bi["kwh"] / bi["produced_units"].replace(0, np.nan).astype(float)
    bi["kwh_per_good_unit"] = bi["kwh"] / bi["good_units"].replace(0, np.nan).astype(float)
    bi["peak_share"] = bi["kwh_peak"] / bi["kwh"]

    base_end = window_start + pd.Timedelta(days=config.baseline_days(days))
    ok = (bi["status"] == "COMPLETED") & bi["reliable"]
    base = {}
    for (m, p), g in bi[ok].sort_values("actual_start_utc").groupby(["machine_id", "product_code"]):
        early = g[g["actual_start_utc"] < base_end]
        ref = early if len(early) >= 3 else g.head(5)
        base[(m, p)] = float(ref["kwh_per_unit"].median())
    bi["baseline_kwh_per_unit"] = [base.get((m, p), np.nan) for m, p in zip(bi["machine_id"], bi["product_code"])]
    bi["intensity_ratio"] = bi["kwh_per_unit"] / bi["baseline_kwh_per_unit"]

    plant_of = dict(zip(d["machine"]["machine_id"], d["machine"]["plant_id"]))
    for m, g in bi[ok].sort_values("actual_start_utc").groupby("machine_id"):
        g = g.reset_index(drop=True)
        roll = g["intensity_ratio"].rolling(ROLL, min_periods=3).median()
        flag = (roll > DRIFT_RATIO).to_numpy()
        for a, z in runs(flag, max_gap=6):
            if z - a < 3:
                continue
            first = max(0, a - ROLL + 1)
            seg = g.iloc[first:z]
            excess = float((seg["kwh"] - seg["baseline_kwh_per_unit"] * seg["produced_units"]).clip(lower=0).sum())
            after = maint[(maint["machine_id"] == m) & (maint["maintenance_type"] == "CORRECTIVE") &
                          (maint["started_at"] >= seg["actual_start_utc"].iloc[0])]
            fixed = f"; resolved by {after.iloc[0].maintenance_id} on {after.iloc[0].started_at:%Y-%m-%d}" if len(after) else \
                "; still elevated at end of data"
            F.add("INTENSITY_DRIFT", "WASTE", plant_of[m], "machine", m, seg["actual_start_utc"].iloc[0],
                  seg["actual_end_utc"].iloc[-1], "R-INT-01", "RAISE_CORRECTIVE_MAINTENANCE", "maintenance_engineer",
                  f"Rolling median kWh/unit reached x{float(roll.iloc[a:z].max()):.2f} of baseline over "
                  f"{z - first} batches{fixed}", metric_value=float(roll.iloc[a:z].max()), metric_unit="ratio",
                  impact_kwh=excess)
    return bi
