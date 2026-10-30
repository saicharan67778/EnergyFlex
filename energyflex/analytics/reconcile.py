"""Energy reconciliation.

R-HIER-01: main incomer vs sum of sub-meters per 15-min interval. The unmetered residual (lighting, losses)
is learnt per plant and occupancy state; a deficit far below it means a sub-meter over-reads (e.g. CT ratio).
The most likely sub-meter is quarantined for the window so downstream waste analytics do not use it.
Also produces the per-meter register-vs-interval and per-plant hierarchy reconciliation tables.
"""
import numpy as np
import pandas as pd

from .common import Q, runs


def occupied_flags(ts, inst, plant_id):
    """True where the 15-min interval overlaps a WORKING shift instance of the plant."""
    occ = np.zeros(len(ts), dtype=bool)
    t = pd.DatetimeIndex(ts).tz_convert("UTC").tz_localize(None).values
    w = inst[(inst["plant_id"] == plant_id) & (inst["calendar_status"] == "WORKING")]
    for r in w.itertuples():
        occ |= (t + Q.to_timedelta64() > r.start_utc.to_datetime64()) & (t < r.end_utc.to_datetime64())
    return occ


def hierarchy(cr, d, F):
    meter = d["meter"]
    typ = dict(zip(meter["meter_id"], meter["meter_type"]))
    cr["meter_type"] = cr["meter_id"].map(typ)
    cr["quarantined"] = False
    rows = []
    for pid, g in cr.groupby("plant_id"):
        main = g[g["meter_type"] == "MAIN"].set_index("ts_utc")["interval_kwh"]
        subs = g[g["meter_type"] == "SUB"].pivot(index="ts_utc", columns="meter_id", values="interval_kwh")
        df = pd.DataFrame({"main": main}).join(subs, how="inner")
        sub_cols = list(subs.columns)
        df = df.dropna()
        resid_kw = (df["main"] - df[sub_cols].sum(axis=1)) * 4
        occ = occupied_flags(df.index, d["shift_instance"], pid)
        # expected unmetered residual (lighting by occupancy + losses proportional to load), robust OLS
        sub_kw = df[sub_cols].sum(axis=1).to_numpy() * 4
        X = np.column_stack([np.ones(len(df)), occ.astype(float), sub_kw])
        y = resid_kw.to_numpy()
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        for _ in range(2):
            r = y - X @ coef
            mad = 1.4826 * np.median(np.abs(r - np.median(r)))
            keep = np.abs(r) < 3 * max(mad, 0.5)
            coef, *_ = np.linalg.lstsq(X[keep], y[keep], rcond=None)
        expected = X @ coef
        deficit = expected - y
        est = g[g["meter_type"] == "SUB"].pivot(index="ts_utc", columns="meter_id", values="is_estimated")
        has_est = est.reindex(df.index).fillna(False).astype(bool).any(axis=1).to_numpy()
        # physical rule: sub-meters cannot sum to more than the incomer (1 % + 2 kW tolerance); statistical rule:
        # residual far below its learnt level. Intervals containing a backfilled estimate are not evidence.
        physical = -y > np.maximum(2.0, 0.01 * df["main"].to_numpy() * 4)
        statistical = deficit > max(4 * mad, 6.0)
        flag = (physical | statistical) & ~has_est
        for a, b in runs(flag, max_gap=48):  # bridge off-shift hours where a scaled meter reads ~0
            if flag[a:b].sum() < 2:
                continue
            seg = df.iloc[a:b]
            dfc = deficit[a:b]
            scores = {}
            for c in sub_cols:
                x = seg[c].to_numpy() * 4
                scores[c] = float(np.corrcoef(dfc, x)[0, 1]) if x.std() > 0 and dfc.std() > 0 else 0.0
                # a doubled sub-meter shows a deficit ~ half of its own reading
                ratio = np.median(dfc[flag[a:b]] / np.maximum(x[flag[a:b]], 1e-6))
                scores[c] += 1.0 - min(abs(ratio - 0.5) * 2, 1.0)
            suspect = max(scores, key=scores.get)
            x = seg[suspect].to_numpy() * 4
            factor = float(np.median(x[flag[a:b]] / np.maximum(x[flag[a:b]] - dfc[flag[a:b]], 1e-6)))
            start, end = seg.index[0], seg.index[-1] + Q
            F.add("HIERARCHY_TOTAL_MISMATCH", "DATA_QUALITY", pid, "meter", suspect, start, end, "R-HIER-01",
                  "QUARANTINE_SUBMETER_AND_VERIFY_CT", "ot_it_admin",
                  f"Sum of sub-meters exceeds the incomer by up to {float((-resid_kw.iloc[a:b]).max()):.1f} kW; "
                  f"{suspect} best explains the deficit (implied scale x{factor:.2f}); quarantined pending CT check",
                  metric_value=factor, metric_unit="implied_scale", impact_kwh=float(dfc[flag[a:b]].sum() / 4))
            q = (cr["meter_id"] == suspect) & (cr["ts_utc"] >= start) & (cr["ts_utc"] < end)
            cr.loc[q, "quarantined"] = True
        rows.append({"plant_id": pid, "intervals_compared": len(df), "intervals_flagged": int(flag.sum()),
                     "median_unmetered_kw_occupied": round(float(np.median(resid_kw[occ])) if occ.any() else 0, 2),
                     "median_unmetered_kw_unoccupied": round(float(np.median(resid_kw[~occ])) if (~occ).any() else 0, 2)})
    cr.loc[cr["quarantined"], "dq_flags"] = (cr.loc[cr["quarantined"], "dq_flags"] + ";QUARANTINED").str.strip(";")
    return pd.DataFrame(rows)


def energy_balance(cr, findings, meter):
    """Per meter: interval sum vs register span (minus detected register offsets); per plant: main vs subs."""
    reg_off = findings[findings["issue_type"] == "REGISTER_INTERVAL_MISMATCH"].groupby("entity_id")["metric_value"].sum()
    rows = []
    for mid, g in cr.groupby("meter_id"):
        g = g.sort_values("ts_utc")
        r = g["register_kwh"].dropna()
        first_idx = r.index[0]
        interval_sum = float(g.loc[g.index > first_idx, "interval_kwh"].sum())
        span = float(r.iloc[-1] - r.iloc[0])
        adj = span - float(reg_off.get(mid, 0.0))
        rows.append({"meter_id": mid, "interval_sum_kwh": round(interval_sum, 3), "register_span_kwh": round(span, 3),
                     "detected_register_offsets_kwh": round(float(reg_off.get(mid, 0.0)), 3),
                     "adjusted_register_kwh": round(adj, 3),
                     "difference_kwh": round(interval_sum - adj, 3),
                     "difference_pct": round(100 * (interval_sum - adj) / adj, 4) if adj else 0.0,
                     "estimated_intervals": int(g["is_estimated"].sum())})
    per_meter = pd.DataFrame(rows).merge(meter[["meter_id", "plant_id", "meter_type"]], on="meter_id")
    ok = cr[~cr["quarantined"]]
    q_ts = cr[cr["quarantined"]][["plant_id", "ts_utc"]].drop_duplicates()
    ok = ok.merge(q_ts.assign(_q=1), on=["plant_id", "ts_utc"], how="left")
    ok = ok[ok["_q"].isna()]
    plant = ok.pivot_table(index="plant_id", columns="meter_type", values="interval_kwh", aggfunc="sum")
    plant["unmetered_kwh"] = plant["MAIN"] - plant["SUB"]
    plant["unmetered_pct"] = 100 * plant["unmetered_kwh"] / plant["MAIN"]
    plant = plant.reset_index().rename(columns={"MAIN": "main_kwh", "SUB": "sum_sub_kwh"}).round(3)
    return per_meter, plant
