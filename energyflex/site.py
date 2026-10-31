"""Build site/data/dashboard.json from a dataset + analytics outputs (the static dashboard reads only this file)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, io


def _r(x, n=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def _clean(o):
    """Recursively replace NaN/inf with None so the output is strict JSON."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):
        return None
    if isinstance(o, np.generic):
        return _clean(o.item())
    return o


def build(data_root, out_root, site_root):
    data_root, out_root, site_root = Path(data_root), Path(out_root), Path(site_root)
    d = io.load_dataset(data_root)
    metrics = json.loads((out_root / "metrics.json").read_text())
    manifest = json.loads((data_root / "manifest.json").read_text())
    val = json.loads((data_root / "validation_summary.json").read_text())
    repro_p = data_root / "repro_report.json"
    repro = json.loads(repro_p.read_text()) if repro_p.exists() else None
    plants = d["plant"]
    tz = dict(zip(plants["plant_id"], plants["timezone"]))
    cur = dict(zip(plants["plant_id"], plants["currency"]))

    cr = pd.read_csv(out_root / "readings_curated.csv", parse_dates=["ts_utc"])
    meter = d["meter"].set_index("meter_id")
    cr["meter_type"] = cr["meter_id"].map(meter["meter_type"])
    cr["scope"] = cr["meter_id"].map(meter["measured_scope"])
    main = cr[cr["meter_type"] == "MAIN"].copy()

    daily, profile, period_daily = [], {}, []
    for pid, g in main.groupby("plant_id"):
        lt = g["ts_utc"].dt.tz_convert(tz[pid])
        g = g.assign(day=lt.dt.strftime("%Y-%m-%d"), hour=lt.dt.hour, weekend=lt.dt.dayofweek >= 5)
        fx = config.FX_TO_USD[cur[pid]]
        dd = g.groupby("day").agg(kwh=("interval_kwh", "sum"), cost=("cost", "sum"), peak_kw=("avg_kw", "max"))
        for day, r in dd.iterrows():
            daily.append({"plant_id": pid, "day": day, "kwh": _r(r.kwh, 1), "cost_usd": _r(r.cost * fx, 2),
                          "peak_kw": _r(r.peak_kw, 1)})
        pr = g.groupby(["weekend", "hour"])["avg_kw"].mean().unstack(0)
        per = g[~g["weekend"]].groupby("hour")["period"].agg(lambda s: s.mode().iloc[0])
        profile[pid] = {"weekday_kw": [_r(v, 1) for v in pr[False]], "weekend_kw": [_r(v, 1) for v in pr[True]],
                        "weekday_period": list(per.reindex(range(24)).fillna(""))}
        pdd = g.pivot_table(index="day", columns="period", values="interval_kwh", aggfunc="sum").fillna(0)
        for day, r in pdd.iterrows():
            period_daily.append({"plant_id": pid, "day": day, **{k: _r(v, 1) for k, v in r.items()}})

    # utilities off-shift daily (actual vs weather-normalised expectation)
    off = pd.read_csv(out_root / "offshift_daily.csv")
    offshift = [{"plant_id": r.plant_id, "day": str(r.day), "actual": _r(r.actual, 1), "expected": _r(r.expected, 1)}
                for r in off.itertuples()]

    bi = pd.read_csv(out_root / "batch_intensity.csv", parse_dates=["actual_start_utc"])
    bi = bi[(bi["status"] == "COMPLETED")]
    intensity = [{"batch_id": r.batch_id, "machine_id": r.machine_id, "product": r.product_code,
                  "t": r.actual_start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "kwh": _r(r.kwh, 1),
                  "kwh_per_unit": _r(r.kwh_per_unit, 4), "ratio": _r(r.intensity_ratio, 3), "reliable": bool(r.reliable)}
                 for r in bi.itertuples()]

    findings = pd.read_csv(out_root / "findings.csv").fillna("")
    recs = pd.read_csv(out_root / "recommendations.csv").fillna("")
    bills = pd.read_csv(out_root / "monthly_bill.csv")
    bal = pd.read_csv(out_root / "energy_balance_meter.csv")
    pbal = pd.read_csv(out_root / "energy_balance_plant.csv")

    mach = d["machine"]
    idle = findings[findings["issue_type"] == "HIGH_IDLE_CONSUMPTION"].groupby("entity_id")["impact_kwh"].agg(["sum", "count"])
    machines = []
    for m in mach.itertuples():
        machines.append({"machine_id": m.machine_id, "plant_id": m.plant_id, "name": m.machine_name,
                         "type": m.machine_type, "rated_kw": m.rated_kw, "idle_kw": m.idle_kw, "standby_kw": m.standby_kw,
                         "status": m.status, "is_production": bool(m.is_production),
                         "idle_waste_kwh": _r(idle["sum"].get(m.machine_id, 0.0), 1),
                         "idle_events": int(idle["count"].get(m.machine_id, 0))})
    maint = d["maintenance_event"]
    maintenance = [{"maintenance_id": r.maintenance_id, "machine_id": r.machine_id, "type": r.maintenance_type,
                    "started": r.started_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "reason": r.reason} for r in maint.itertuples()]

    out = {
        "meta": {"scale": manifest["scale"], "seed": manifest["seed"], "window_utc": manifest["window_utc"],
                 "generator_command": manifest["generator_command"], "row_counts": manifest["row_counts"],
                 "reporting_currency": config.REPORTING_CURRENCY, "fx_to_usd": config.FX_TO_USD},
        "plants": plants.assign(n_meters=plants["plant_id"].map(d["meter"].groupby("plant_id").size()))
                       [["plant_id", "plant_name", "city", "timezone", "currency", "n_meters"]].to_dict("records"),
        "headline": metrics["headline"], "acceptance": metrics["acceptance"],
        "evaluation": metrics["evaluation_by_issue"], "evaluation_overall": metrics["evaluation_overall"],
        "validation": {"summary": val["summary"],
                       "checks": [{k: c[k] for k in ("check", "category", "status", "failures",
                                                     "explained_by_ground_truth")} for c in val["checks"]]},
        "repro": {k: repro[k] for k in ("reproducible", "files_compared", "row_counts_equal", "checksum_mismatches")}
        if repro else None,
        "daily": daily, "period_daily": period_daily, "profile": profile, "offshift": offshift,
        "intensity": intensity, "machines": machines, "maintenance": maintenance,
        "findings": findings.to_dict("records"), "recommendations": recs.to_dict("records"),
        "bills": bills.to_dict("records"), "energy_balance": bal.to_dict("records"),
        "plant_balance": pbal.to_dict("records"),
    }
    site_root.mkdir(parents=True, exist_ok=True)
    (site_root / "dashboard.json").write_text(json.dumps(_clean(out), separators=(",", ":"), default=str, allow_nan=False), encoding="utf-8", newline="\n")
