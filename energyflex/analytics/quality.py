"""Data-quality gate: raw landing readings -> curated 15-minute series + DATA_QUALITY findings.

Rules (docs/RULES.md): R-DUP-01 duplicates, R-UNIT-01 kW-in-kWh, R-GAP-01 gaps + register backfill,
R-REG-01 register vs interval reconciliation, R-HIER-02 machine tag outside the meter hierarchy.
Corrections never overwrite the raw file; the curated frame carries `dq_flags` for traceability.
"""
import numpy as np
import pandas as pd

from .. import ids
from .common import Findings, Q, mapped_machine, runs

REG_ABS_TOL = 0.01    # kWh
REG_REL_TOL = 0.005   # 0.5 %
UNIT_TOL = 0.002      # |interval - avg_kw| at or below this => kW was written into the kWh field


def _dedupe(er, F, meter_plant):
    er = er.sort_values(["meter_id", "ts_utc", "ingest_seq"], kind="stable")
    dup = er["reading_id"].duplicated(keep=False)
    first = er.drop_duplicates("reading_id", keep="first")
    reg_by_key = dict(zip(zip(first["meter_id"], first["ts_utc"]), first["register_kwh"]))
    drop = []
    for rid, g in er[dup].groupby("reading_id", sort=False):
        vals = g[["interval_kwh", "avg_kw", "register_kwh", "machine_id"]].astype(str)
        exact = (vals.nunique() == 1).all()
        if exact:
            keep = g.index[0]
            decision, detail = "DROP_LATER_COPY", f"{len(g)} identical copies; kept ingest_seq {g.iloc[0].ingest_seq}"
        else:
            prev = reg_by_key.get((g.iloc[0].meter_id, g.iloc[0].ts_utc - Q))
            if prev is None:
                keep = g.index[0]
            else:
                keep = (g["register_kwh"] - prev - g["interval_kwh"]).abs().idxmin()
            decision = "KEEP_REGISTER_CONSISTENT_ROW"
            detail = (f"{len(g)} conflicting copies (kWh {', '.join(f'{v:.3f}' for v in g.interval_kwh)}); "
                      f"kept ingest_seq {er.loc[keep, 'ingest_seq']} whose value matches the register delta")
        drop += [i for i in g.index if i != keep]
        r = g.iloc[0]
        F.add("DUPLICATE_READING", "DATA_QUALITY", meter_plant[r.meter_id], "reading", rid, r.ts_utc, r.ts_utc + Q,
              "R-DUP-01", decision, "ot_it_admin", detail, metric_value=len(g), metric_unit="copies",
              impact_kwh=float(g.drop(index=keep)["interval_kwh"].sum()))
    return er.drop(index=drop)


def _shape_backfill(cr, meter):
    """Re-shape each sub-meter gap on the hierarchy: incomer minus the other sub-meters at the same timestamps,
    scaled so the gap total still equals the register delta (falls back to the previous-day profile)."""
    if "gap_ref" not in cr or not cr["is_estimated"].any():
        return
    typ = cr["meter_id"].map(dict(zip(meter["meter_id"], meter["meter_type"])))
    main = cr[typ == "MAIN"].set_index(["plant_id", "ts_utc"])["interval_kwh"]
    subs = cr[typ == "SUB"].groupby(["plant_id", "ts_utc"])["interval_kwh"].sum()
    for ref, blk in cr[cr["is_estimated"]].groupby("gap_ref"):
        if typ[blk.index[0]] != "SUB":
            continue
        key = list(zip(blk["plant_id"], blk["ts_utc"]))
        others = subs.reindex(key).to_numpy() - blk["interval_kwh"].to_numpy()
        w = np.clip(main.reindex(key).to_numpy() - others, 1e-3, None)
        if np.isnan(w).any():
            continue
        cr.loc[blk.index, "interval_kwh"] = np.round(blk["gap_kwh"].iloc[0] * w / w.sum(), 3)
    cr.drop(columns=["gap_kwh", "gap_ref"], inplace=True)


def run(d):
    F_ = Findings()
    meter, mmap = d["meter"], d["meter_machine_map"]
    meter_plant = dict(zip(meter["meter_id"], meter["plant_id"]))
    er = _dedupe(d["energy_reading"].copy(), F_, meter_plant)
    out = []
    for mid, g in er.groupby("meter_id", sort=True):
        g = g.sort_values("ts_utc").reset_index(drop=True)
        pid = meter_plant[mid]
        flags = [[] for _ in range(len(g))]
        kwh = g["interval_kwh"].to_numpy().copy()
        avg = g["avg_kw"].to_numpy()
        reg = g["register_kwh"].to_numpy()

        # R-UNIT-01: interval_kwh equals the average kW -> it is kW, true energy is avg_kw x 0.25
        unit = (np.abs(kwh - avg) <= UNIT_TOL) & (avg > 0.05)
        for a, b in runs(unit, max_gap=1):
            over = float((kwh[a:b] - avg[a:b] * 0.25)[unit[a:b]].sum())
            F_.add("UNIT_KW_AS_KWH", "DATA_QUALITY", pid, "meter", mid, g.ts_utc[a], g.ts_utc[b - 1] + Q, "R-UNIT-01",
                   "DIVIDE_BY_4_AND_FIX_CONFIG", "ot_it_admin",
                   f"{int(unit[a:b].sum())} intervals where interval_kwh == avg_kw (ratio 1.0, expected 0.25); "
                   f"register deltas confirm kWh = kW/4", metric_value=int(unit[a:b].sum()), metric_unit="intervals",
                   impact_kwh=over)
        kwh[unit] = np.round(avg[unit] * 0.25, 3)
        for i in np.flatnonzero(unit):
            flags[i].append("UNIT_FIXED")

        # R-REG-01 on contiguous intervals; R-GAP-01 on non-contiguous ones
        dt = g["ts_utc"].diff()
        contiguous = (dt == Q).to_numpy()
        dreg = np.concatenate([[np.nan], np.diff(reg)])
        resid = dreg - kwh
        bad = contiguous & (np.abs(resid) > np.maximum(REG_ABS_TOL, REG_REL_TOL * kwh))
        for a, b in runs(bad, max_gap=8):
            off = float(np.nansum(resid[a:b][bad[a:b]]))
            variant = "JUMP" if bad[a:b].sum() == 1 else "DRIFT"
            F_.add("REGISTER_INTERVAL_MISMATCH", "DATA_QUALITY", pid, "meter", mid, g.ts_utc[a], g.ts_utc[b - 1] + Q,
                   "R-REG-01", "USE_INTERVAL_SUM_AND_RAISE_METER_TICKET", "ot_it_admin",
                   f"{variant}: register advanced {off:+.1f} kWh more than the interval sum over "
                   f"{int(bad[a:b].sum())} intervals", metric_value=off, metric_unit="kWh", impact_kwh=abs(off))
        for i in np.flatnonzero(bad):
            flags[i].append("REGISTER_MISMATCH")

        est = []
        prof = g.set_index("ts_utc")["interval_kwh"]
        for i in np.flatnonzero(~contiguous[1:] if len(g) > 1 else []) + 1:
            n_missing = int(dt[i] / Q) - 1
            gap_kwh = float(reg[i] - reg[i - 1] - kwh[i])
            # shape the backfill on the same intervals one day earlier (flat if unavailable)
            missing_ts = [g.ts_utc[i - 1] + Q * (k + 1) for k in range(n_missing)]
            w = np.array([prof.get(t - pd.Timedelta(days=1), np.nan) for t in missing_ts], dtype=float)
            if np.isnan(w).any() or (w <= 0).any():
                w = np.ones(n_missing)
            w = w / w.sum()
            for t, share in zip(missing_ts, w):
                est.append({"reading_id": ids.reading(mid, t), "meter_id": mid, "ts_utc": t,
                            "interval_kwh": round(max(gap_kwh, 0) * share, 3), "register_kwh": np.nan,
                            "machine_id_raw": None, "is_estimated": True, "dq_flags": "GAP_BACKFILL",
                            "gap_kwh": max(gap_kwh, 0), "gap_ref": f"{mid}@{i}"})
            F_.add("METER_GAP", "DATA_QUALITY", pid, "meter", mid, missing_ts[0], g.ts_utc[i], "R-GAP-01",
                   "BACKFILL_FROM_REGISTER_DELTA", "ot_it_admin",
                   f"{n_missing} missing intervals ({n_missing * 15} min); {gap_kwh:.1f} kWh recovered from register "
                   f"delta and profiled on the previous day", metric_value=n_missing, metric_unit="intervals",
                   impact_kwh=gap_kwh)

        cur = pd.DataFrame({"reading_id": g["reading_id"], "meter_id": mid, "ts_utc": g["ts_utc"], "interval_kwh": kwh,
                            "register_kwh": reg, "machine_id_raw": g["machine_id"], "is_estimated": False,
                            "dq_flags": [";".join(f) for f in flags]})
        out.append(pd.concat([cur, pd.DataFrame(est)], ignore_index=True) if est else cur)

    cr = pd.concat(out, ignore_index=True).sort_values(["meter_id", "ts_utc"]).reset_index(drop=True)
    cr["plant_id"] = cr["meter_id"].map(meter_plant)
    _shape_backfill(cr, meter)
    cr["avg_kw"] = np.round(cr["interval_kwh"] * 4, 3)

    # R-HIER-02: attribution follows the effective-dated meter->machine bridge
    machine_meters = set(meter[meter["measured_scope"] == "MACHINE"]["meter_id"])
    sel = cr["meter_id"].isin(machine_meters)
    cr["machine_id"] = None
    cr.loc[sel, "machine_id"] = mapped_machine(cr.loc[sel, "meter_id"], cr.loc[sel, "ts_utc"], mmap)
    wrong = (cr["machine_id_raw"].notna() & (cr["machine_id_raw"] != cr["machine_id"])).to_numpy()
    for mid, g in cr[sel | wrong].groupby("meter_id"):
        w = wrong[g.index]
        for a, b in runs(w, max_gap=1):
            seg = g.iloc[a:b]
            tagged = seg["machine_id_raw"][w[a:b]].mode().iloc[0]
            F_.add("MACHINE_OUTSIDE_HIERARCHY", "DATA_QUALITY", meter_plant[mid], "meter", mid, seg.ts_utc.iloc[0],
                   seg.ts_utc.iloc[-1] + Q, "R-HIER-02", "REATTRIBUTE_TO_MAPPED_MACHINE", "ot_it_admin",
                   f"{int(w[a:b].sum())} readings tagged {tagged}, which is not mapped to {mid} at that time; "
                   f"re-attributed to {seg['machine_id'].dropna().iloc[0] if seg['machine_id'].notna().any() else 'n/a'}",
                   metric_value=int(w[a:b].sum()), metric_unit="readings",
                   impact_kwh=float(seg["interval_kwh"][w[a:b]].sum()))
    cr.loc[wrong, "dq_flags"] = (cr.loc[wrong, "dq_flags"] + ";REATTRIBUTED").str.strip(";")
    return cr, F_
