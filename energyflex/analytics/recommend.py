"""Recommendation rules. Every recommendation cites a measured baseline, its analysis window, an explicit savings
formula, and the finding ids it is built on. Annualisation factor = 365 / days analysed.
"""
import numpy as np
import pandas as pd

from .. import config, ids
from .reconcile import occupied_flags

STANDBY_CAPTURE = 0.85     # share of idle-above-standby energy an auto-standby timer removes
SHIFTABLE_SHARE = 0.50     # share of movable PEAK-window batch energy planners can re-sequence
LEAK_REPAIR_CAPTURE = 0.80
OVERRIDE_RECURRENCE_YR = 12


def _usd(v, cur):
    return round(v * config.FX_TO_USD[cur], 2)


def build(findings, cr, bi, bills, d, window_start, window_end, days):
    A = 365.0 / days
    plants = d["plant"].set_index("plant_id")
    mach = d["machine"].set_index("machine_id")
    recs = []

    def add(pid, scope_type, scope_id, rule, title, owner, metric, value, unit, kwh_yr, kw, cost_yr, formula,
            confidence, evidence):
        cur = plants.loc[pid, "currency"]
        recs.append({"plant_id": pid, "scope_type": scope_type, "scope_id": scope_id, "rule_id": rule, "title": title,
                     "owner_role": owner, "baseline_metric": metric, "baseline_value": round(float(value), 3),
                     "baseline_unit": unit, "baseline_window_start_utc": window_start,
                     "baseline_window_end_utc": window_end, "expected_savings_kwh_yr": round(max(kwh_yr, 0), 1),
                     "expected_savings_kw": round(max(kw, 0), 1), "expected_savings_cost_yr": round(max(cost_yr, 0), 2),
                     "currency": cur, "expected_savings_usd_yr": _usd(max(cost_yr, 0), cur), "savings_formula": formula,
                     "confidence": confidence, "evidence_ids": ";".join(evidence), "status": "PROPOSED"})

    # --- idle -> auto-standby (per machine)
    idle = findings[findings["issue_type"] == "HIGH_IDLE_CONSUMPTION"]
    for m, g in idle.groupby("entity_id"):
        mr = mach.loc[m]
        sel = cr[(cr["machine_id"] == m)]
        cost = 0.0
        for f in g.itertuples():
            seg = sel[(sel["ts_utc"] >= f.window_start_utc) & (sel["ts_utc"] < f.window_end_utc)].iloc[2:]
            cost += float(((seg["avg_kw"] - mr.standby_kw).clip(lower=0) * 0.25 * seg["rate"]).sum())
        waste = float(g["impact_kwh"].sum())
        add(mr.plant_id, "machine", m, "R-REC-IDLE", f"Enable auto-standby after 30 min idle on {mr.machine_name}",
            "plant_operator", "Idle energy above standby with no batch running", waste, "kWh",
            STANDBY_CAPTURE * waste * A, 0, STANDBY_CAPTURE * cost * A,
            f"{STANDBY_CAPTURE} x idle-above-standby kWh (after 30 min grace) x 365/{days}; cost at each interval's TOU rate",
            "HIGH" if len(g) >= 3 else "MEDIUM", list(g["finding_id"]))

    # --- peak spikes -> staggered start / demand limiting (per plant)
    spikes = findings[findings["issue_type"] == "PEAK_DEMAND_SPIKE"]
    main = cr[cr["meter_type"] == "MAIN"]
    for pid, g in spikes.groupby("plant_id"):
        tz = plants.loc[pid, "timezone"]
        pm = main[main["plant_id"] == pid].copy()
        mask = np.zeros(len(pm), dtype=bool)
        for f in g.itertuples():
            mask |= ((pm["ts_utc"] >= f.window_start_utc) & (pm["ts_utc"] < f.window_end_utc)).to_numpy()
        pm["spike"] = mask
        pm["month"] = pm["ts_utc"].dt.tz_convert(tz).dt.strftime("%Y-%m")
        saved, monthly = [], []
        for month, mg in pm.groupby("month"):
            b = bills[(bills["plant_id"] == pid) & (bills["month"] == month)].iloc[0]
            peak, clean_peak = mg["avg_kw"].max(), mg.loc[~mg["spike"], "avg_kw"].max()
            saved.append(peak - clean_peak)
            monthly.append((peak - clean_peak) * b.demand_rate)
        dkw = float(np.mean(saved))
        if dkw < 0.5:
            continue
        add(pid, "plant", pid, "R-REC-PEAK", "Stagger heat-up starts and add a demand-limit interlock in PEAK windows",
            "production_planner", "Monthly max 15-min demand at incomer", float(bills[bills["plant_id"] == pid]["peak_kw"].max()),
            "kW", 0, dkw, float(np.mean(monthly)) * 12,
            "mean over months of (monthly peak kW - peak kW excluding spike intervals) x demand rate x 12",
            "HIGH", list(g["finding_id"]))

    # --- load shifting out of PEAK, limited to free non-PEAK capacity inside staffed shifts (per plant)
    for pid, g in bi[bi["status"] != "CANCELLED"].groupby("plant_id"):
        pm = main[main["plant_id"] == pid]
        occ = occupied_flags(pm["ts_utc"], d["shift_instance"], pid)
        nonpeak_occ = occ & (pm["period"] != "PEAK").to_numpy()
        rate_peak = pm.loc[pm["period"] == "PEAK", "rate"].mean()
        rate_alt = pm.loc[nonpeak_occ, "rate"].mean() if nonpeak_occ.any() else rate_peak
        spread = rate_peak - rate_alt
        movable = 0.0
        for m, mg in g.groupby("machine_id"):
            run_nonpeak_min = float((mg["run_hours"] * 60 * (1 - mg["peak_share"].fillna(0))).sum())
            free_min = max(0.0, nonpeak_occ.sum() * 15 - run_nonpeak_min)
            kwh_per_min = mg["kwh"].sum() / max(float((mg["run_hours"] * 60).sum()), 1.0)
            movable += min(float(mg["kwh_peak"].sum()), free_min * kwh_per_min) * SHIFTABLE_SHARE
        share = g["kwh_peak"].sum() / g["kwh"].sum()
        if movable <= 0 or spread / rate_peak < 0.10:
            continue
        add(pid, "plant", pid, "R-REC-SHIFT",
            "Re-sequence energy-intensive batches into non-PEAK hours of existing shifts",
            "production_planner", "Share of batch energy in PEAK window", 100 * share, "%", 0, 0,
            movable * spread * A,
            f"{SHIFTABLE_SHARE} x min(PEAK batch kWh, free non-PEAK staffed minutes x machine kWh/min) "
            f"= {movable:,.0f} kWh x (PEAK - staffed non-PEAK rate = {spread:.3f}) x 365/{days}",
            "MEDIUM", [])

    # --- intensity drift -> maintenance (per finding)
    for f in findings[findings["issue_type"] == "INTENSITY_DRIFT"].itertuples():
        mr = mach.loc[f.entity_id]
        mb = bi[(bi["machine_id"] == f.entity_id) & (bi["status"] == "COMPLETED")]
        rate = float(mb["energy_cost"].sum() / mb["kwh"].sum())
        if "still elevated" in f.detail:
            recent = mb[mb["actual_start_utc"] >= window_end - pd.Timedelta(days=14)]
            kwh_yr = float(recent["kwh"].sum()) * 365 / 14 * (f.metric_value - 1) / f.metric_value
            add(mr.plant_id, "machine", f.entity_id, "R-REC-MAINT",
                f"Schedule corrective maintenance on {mr.machine_name} (kWh/unit x{f.metric_value:.2f} of baseline)",
                "maintenance_engineer", "Rolling median kWh/unit vs baseline", f.metric_value, "ratio", kwh_yr, 0,
                kwh_yr * rate, "(ratio-1)/ratio x last-14-day machine kWh x 365/14; cost at machine's average rate",
                "HIGH", [f.finding_id])
        else:
            add(mr.plant_id, "machine", f.entity_id, "R-REC-MAINT",
                f"Add a 1.10x kWh/unit alert on {mr.machine_name} to trigger condition-based maintenance",
                "maintenance_engineer", "Excess kWh during the drift episode before repair", f.impact_kwh, "kWh",
                f.impact_kwh, 0, f.impact_kwh * rate,
                "measured excess kWh of the episode, assuming one recurrence per year is caught early; machine avg rate",
                "MEDIUM", [f.finding_id])

    # --- off-shift waste (per finding)
    for f in findings[findings["issue_type"] == "OFF_SHIFT_WASTE"].itertuples():
        seg = cr[(cr["meter_id"] == f.entity_id) & (cr["ts_utc"] >= f.window_start_utc) & (cr["ts_utc"] < f.window_end_utc)]
        rate = float(seg["rate"].mean())
        ndays = max(1.0, (f.window_end_utc - f.window_start_utc) / pd.Timedelta(days=1))
        if f.decision == "RECOMMEND_LEAK_SURVEY":
            kwh_yr = LEAK_REPAIR_CAPTURE * f.impact_kwh / ndays * 365
            title, owner = "Run an ultrasonic compressed-air leak survey and repair", "maintenance_engineer"
            formula = f"{LEAK_REPAIR_CAPTURE} x excess off-shift kWh/day x 365"
        else:
            kwh_yr = f.impact_kwh * OVERRIDE_RECURRENCE_YR
            title, owner = "Lock the BMS HVAC weekend schedule (override auto-expiry)", "ot_it_admin"
            formula = f"measured excess kWh per override x {OVERRIDE_RECURRENCE_YR} expected overrides/yr without a lock"
        add(f.plant_id, "meter", f.entity_id, "R-REC-OFF", title, owner,
            "Off-shift utilities energy vs weather-normalised baseline", f.impact_kwh, "kWh excess", kwh_yr, 0,
            kwh_yr * rate, formula + "; cost at the window's average rate", "HIGH" if f.metric_value > 1.4 else "MEDIUM",
            [f.finding_id])

    rec = pd.DataFrame(recs)
    rec = rec.sort_values(["expected_savings_usd_yr", "plant_id"], ascending=[False, True], kind="stable").reset_index(drop=True)
    rec.insert(0, "rec_id", [ids.recommendation(i + 1) for i in range(len(rec))])
    ev = pd.DataFrame({"rec_event_id": [ids.recommendation_event(i + 1) for i in range(len(rec))],
                       "rec_id": rec["rec_id"], "from_status": None, "to_status": "PROPOSED",
                       "event_ts": window_end, "actor_role": "energyflex_pipeline"})
    return rec, ev
