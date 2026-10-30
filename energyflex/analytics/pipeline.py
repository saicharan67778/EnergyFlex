"""End-to-end analytics: raw files -> curated readings -> findings -> costs -> intensity -> recommendations -> evaluation.

The pipeline reads only data/<scale>/csv/*. Ground truth is read by the evaluation step alone, after every
finding has been produced.
"""
import json
from pathlib import Path

import pandas as pd

from .. import config, export, io, schema
from ..timeutil import iso
from . import cost, evaluate, intensity, quality, recommend, reconcile, waste


def _write(df, path):
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = iso(out[c])
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, lineterminator="\n")


def run(data_root, out_root):
    data_root, out_root = Path(data_root), Path(out_root)
    d = io.load_dataset(data_root)
    manifest = json.loads((data_root / "manifest.json").read_text())
    w_start, w_end = (pd.Timestamp(x) for x in manifest["window_utc"])
    days = int((w_end - w_start) / pd.Timedelta(days=1))

    cr, F = quality.run(d)
    hier = reconcile.hierarchy(cr, d, F)
    bills, coverage = cost.run(cr, d, F)
    bi = intensity.run(cr, d, F, w_start, days)
    idle, offshift = waste.run(cr, d, F, w_start, days)
    findings = F.frame()
    balance, plant_balance = reconcile.energy_balance(cr, findings, d["meter"])
    recs, rec_ev = recommend.build(findings, cr, bi, bills, d, w_start, w_end, days)

    gt = io.load_ground_truth(data_root)  # only now
    per_type, matches, overall = evaluate.score(findings, gt)

    # ---------- acceptance criteria ----------
    done = bi[bi["status"] == "COMPLETED"]
    acceptance = {
        "energy_totals_reconcile": {
            "max_abs_meter_difference_pct": float(balance["difference_pct"].abs().max()),
            "meters_within_0.1pct": int((balance["difference_pct"].abs() <= 0.1).sum()), "meters": len(balance),
            "plant_unmetered_pct_range": [round(float(plant_balance["unmetered_pct"].min()), 2),
                                          round(float(plant_balance["unmetered_pct"].max()), 2)],
            "pass": bool((balance["difference_pct"].abs() <= 0.1).all()
                         and plant_balance["unmetered_pct"].between(1, 25).all())},
        "cost_uses_correct_tariff_interval": {
            "intervals_priced_by_exactly_one_window_pct": round(100 * coverage["exactly_one_window"].sum() /
                                                                coverage["intervals"].sum(), 4),
            "unpriced": int(coverage["unpriced"].sum()), "ambiguous": int(coverage["ambiguous"].sum()),
            "tariff_timezone_mismatches_corrected": int((findings["issue_type"] == "TARIFF_TZ_MISMATCH").sum()),
            "pass": bool(coverage["unpriced"].sum() == 0 and coverage["ambiguous"].sum() == 0)},
        "intensity_normalized_by_output": {
            "completed_batches": len(done),
            "with_kwh_per_unit_pct": round(100 * done["kwh_per_unit"].notna().mean(), 2),
            "with_baseline_pct": round(100 * done["baseline_kwh_per_unit"].notna().mean(), 2),
            "pass": bool(done["kwh_per_unit"].notna().all())},
        "recommendations_cite_baseline_and_savings": {
            "recommendations": len(recs),
            "with_baseline_value": int(recs["baseline_value"].notna().sum()),
            "with_positive_savings": int(((recs["expected_savings_cost_yr"] > 0) |
                                          (recs["expected_savings_kw"] > 0)).sum()),
            "with_evidence_or_formula": int(((recs["evidence_ids"] != "") | recs["savings_formula"].notna()).sum()),
            "pass": bool(len(recs) > 0 and recs["baseline_value"].notna().all() and
                         ((recs["expected_savings_cost_yr"] > 0) | (recs["expected_savings_kw"] > 0)).all())},
    }

    # ---------- write outputs ----------
    out_root.mkdir(parents=True, exist_ok=True)
    ff = export.format_table(findings, "finding")
    ff.to_csv(out_root / "findings.csv", index=False, lineterminator="\n")
    export.format_table(recs, "recommendation").to_csv(out_root / "recommendations.csv", index=False, lineterminator="\n")
    _write(rec_ev, out_root / "recommendation_events.csv")
    keep = ["batch_id", "plant_id", "machine_id", "meter_id", "product_code", "status", "actual_start_utc",
            "actual_end_utc", "run_hours", "produced_units", "good_units", "kwh", "kwh_peak", "peak_share",
            "energy_cost", "kwh_per_unit", "kwh_per_good_unit", "baseline_kwh_per_unit", "intensity_ratio", "reliable"]
    _write(bi[keep].sort_values("batch_id").round(4), out_root / "batch_intensity.csv")
    _write(bills, out_root / "monthly_bill.csv")
    _write(balance, out_root / "energy_balance_meter.csv")
    _write(plant_balance, out_root / "energy_balance_plant.csv")
    _write(hier, out_root / "hierarchy_reconciliation.csv")
    _write(coverage, out_root / "tariff_coverage.csv")
    _write(offshift, out_root / "offshift_daily.csv")
    _write(per_type, out_root / "evaluation_by_issue.csv")
    _write(matches, out_root / "evaluation_matches.csv")
    cols = ["reading_id", "meter_id", "plant_id", "machine_id", "ts_utc", "interval_kwh", "avg_kw", "register_kwh",
            "is_estimated", "quarantined", "dq_flags", "tariff_id", "period", "rate", "cost"]
    cro = cr[cols].copy()
    cro["cost"] = cro["cost"].round(4)
    _write(cro, out_root / "readings_curated.csv")

    cur = {p.plant_id: p.currency for p in d["plant"].itertuples()}
    headline = {
        "scale": manifest["scale"], "window_utc": manifest["window_utc"], "days": days,
        "raw_readings": len(d["energy_reading"]), "curated_readings": len(cr),
        "findings": findings.groupby("issue_type").size().to_dict(),
        "recommendations": len(recs),
        "annual_savings_usd": round(float(recs["expected_savings_usd_yr"].sum()), 0),
        "total_cost_usd": round(float(bills["total_cost_usd"].sum()), 0),
        "detection": overall,
        "acceptance": {k: v["pass"] for k, v in acceptance.items()},
    }
    (out_root / "metrics.json").write_text(json.dumps({"headline": headline, "acceptance": acceptance,
                                                      "evaluation_overall": overall,
                                                      "evaluation_by_issue": per_type.to_dict("records"),
                                                      "currencies": cur}, indent=2, default=str), encoding="utf-8")
    return {"headline": headline, "findings": findings, "recs": recs, "bi": bi, "bills": bills, "cr": cr,
            "per_type": per_type, "acceptance": acceptance, "offshift": offshift, "d": d}
