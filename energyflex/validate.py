"""Dataset validation: keys, references, enums, ordering, arithmetic, lifecycles, duplicates, cross-entity rules.

Each check reports failures and how many are *explained* by a labelled ground-truth row. Status:
PASS (no failures), EXPECTED_FAIL (every failure is a labelled anomaly), FAIL (unexplained failures).
Ground truth is used here only to explain QA failures - never by the analytics.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import ids, schema, tariffs as tariff_lookup

TRANSITIONS = {
    "batch": {(None, "PLANNED"), ("PLANNED", "RELEASED"), ("RELEASED", "RUNNING"), ("RUNNING", "COMPLETED"),
              ("RUNNING", "SCRAPPED"), ("PLANNED", "CANCELLED"), ("RELEASED", "CANCELLED")},
    "maintenance": {(None, "OPEN"), ("OPEN", "IN_PROGRESS"), ("IN_PROGRESS", "CLOSED")},
    "machine": {(None, "INSTALLED"), ("INSTALLED", "ACTIVE"), ("ACTIVE", "UNDER_MAINTENANCE"),
                ("UNDER_MAINTENANCE", "ACTIVE"), ("ACTIVE", "DECOMMISSIONED")},
    "meter": {(None, "ACTIVE"), ("ACTIVE", "COMM_LOSS"), ("COMM_LOSS", "ACTIVE"), ("ACTIVE", "RETIRED")},
}


class Report:
    def __init__(self, gt):
        self.rows = []
        self.gt = gt

    def add(self, check, category, table, failures, explained=0, sample=None, note=""):
        failures, explained = int(failures), int(explained)
        status = "PASS" if failures == 0 else "EXPECTED_FAIL" if explained >= failures else "FAIL"
        self.rows.append({"check": check, "category": category, "table": table, "failures": failures,
                          "explained_by_ground_truth": min(explained, failures),
                          "unexplained": max(0, failures - explained), "status": status,
                          "sample": [str(s) for s in (sample or [])][:5], "note": note})

    def explain_readings(self, meter_ts, types, include_end=False):
        """Count (meter_id, ts) pairs that fall inside a GT window of one of `types` on that meter."""
        g = self.gt[self.gt["issue_type"].isin(types) & (self.gt["entity_type"] == "meter")]
        if meter_ts.empty or g.empty:
            return 0
        hit = np.zeros(len(meter_ts), dtype=bool)
        m = meter_ts["meter_id"].to_numpy()
        t = meter_ts["ts_utc"]
        for r in g.itertuples():
            end = r.window_end_utc + (pd.Timedelta(minutes=15) if include_end else pd.Timedelta(0))
            hit |= (m == r.entity_id) & ((t >= r.window_start_utc) & (t < end)).to_numpy()
        return int(hit.sum())


def _lifecycle(rep, name, ev, key, table):
    ev = ev.sort_values([key, "event_ts"], kind="stable")
    pairs = list(zip(ev["from_status"], ev["to_status"]))
    bad = [p for p in pairs if (p[0], p[1]) not in TRANSITIONS[name]]
    rep.add(f"{name}_lifecycle_transitions_valid", "lifecycle", table, len(bad), sample=bad)
    prev = ev.groupby(key)["to_status"].shift(1)
    chain = (prev.fillna("__") != ev["from_status"].fillna("__")).sum()
    rep.add(f"{name}_event_chain_consistent", "lifecycle", table, chain, note="from_status equals previous to_status")
    order = (ev.groupby(key)["event_ts"].diff() < pd.Timedelta(0)).sum()
    rep.add(f"{name}_events_chronological", "date_ordering", table, order)


def run(d, gt):
    rep = Report(gt)
    # ---------- per-table generic checks from the data dictionary ----------
    for name, df in d.items():
        t = schema.BY_NAME[name]
        rep.add(f"{name}.pk_unique", "primary_key", name, df[t.pk].duplicated().sum() + df[t.pk].isna().sum(),
                sample=list(df[df[t.pk].duplicated()][t.pk]))
        for f in t.fields:
            s = df[f.name]
            if f.required:
                rep.add(f"{name}.{f.name}.required", "required", name, s.isna().sum())
            if f.allowed:
                bad = s.notna() & ~s.isin(f.allowed)
                rep.add(f"{name}.{f.name}.allowed_values", "enum", name, bad.sum(), sample=list(s[bad].unique()))
            if f.pattern:
                rx = ids.COMPILED[f.pattern]
                bad = s.notna() & ~s.astype(str).map(lambda v: bool(rx.match(v)))
                rep.add(f"{name}.{f.name}.id_format", "id_format", name, bad.sum(), sample=list(s[bad]))
            if f.unique and f.name != t.pk and name != "energy_reading":
                rep.add(f"{name}.{f.name}.unique", "uniqueness", name, s.dropna().duplicated().sum())
            if f.fk:
                rt, rc = f.fk.split(".")
                bad = s.notna() & ~s.isin(set(d[rt][rc]))
                rep.add(f"{name}.{f.name}.fk->{f.fk}", "foreign_key", name, bad.sum(), sample=list(s[bad].unique()))

    plant, meter, machine, mmap = d["plant"], d["meter"], d["machine"], d["meter_machine_map"]
    inst, batch, bev = d["shift_instance"], d["production_batch"], d["batch_status_event"]
    mnt, er = d["maintenance_event"], d["energy_reading"]

    # ---------- natural key + duplicates on raw readings ----------
    dup_ids = er[er["reading_id"].duplicated(keep="first")]
    gt_dup = set(gt[gt["issue_type"] == "DUPLICATE_READING"]["entity_id"])
    rep.add("energy_reading.reading_id.unique_natural_key", "uniqueness", "energy_reading", len(dup_ids),
            explained=dup_ids["reading_id"].isin(gt_dup).sum(), sample=list(dup_ids["reading_id"]))
    exact = er.drop(columns=["ingest_seq", "ingested_at"]).duplicated(keep="first")
    rep.add("energy_reading.exact_duplicate_rows", "duplicates", "energy_reading", exact.sum(),
            explained=er[exact]["reading_id"].isin(gt_dup).sum())
    mism = er["reading_id"] != [ids.reading(m, t) for m, t in zip(er["meter_id"], er["ts_utc"])]
    rep.add("energy_reading.reading_id_matches_meter_and_ts", "id_format", "energy_reading", mism.sum())

    # ---------- date ordering ----------
    def order(name, df, a, b, strict=True, nullable=False):
        x = df[[a, b]].dropna() if nullable else df
        bad = (x[b] <= x[a]) if strict else (x[b] < x[a])
        rep.add(f"{name}.{a}<{'' if strict else '='}{b}", "date_ordering", name, bad.sum())
    order("shift_instance", inst, "start_utc", "end_utc")
    order("production_batch", batch, "planned_start_utc", "planned_end_utc")
    order("production_batch", batch, "actual_start_utc", "actual_end_utc", nullable=True)
    order("maintenance_event", mnt, "opened_at", "started_at", strict=False)
    order("maintenance_event", mnt, "started_at", "closed_at")
    order("machine", machine, "commissioned_at", "decommissioned_at", nullable=True)
    order("meter_machine_map", mmap, "effective_from", "effective_to", nullable=True)
    order("machine_state_interval", d["machine_state_interval"], "start_utc", "end_utc")
    tf = d["tariff"].dropna(subset=["effective_to"])
    rep.add("tariff.effective_from<=effective_to", "date_ordering", "tariff",
            (pd.to_datetime(tf["effective_to"]) < pd.to_datetime(tf["effective_from"])).sum())
    late = er["ingested_at"] < er["ts_utc"] + pd.Timedelta(minutes=15)
    rep.add("energy_reading.ingested_after_interval_end", "date_ordering", "energy_reading", late.sum())
    misaligned = (er["ts_utc"].dt.minute % 15 != 0) | (er["ts_utc"].dt.second != 0)
    rep.add("energy_reading.ts_aligned_to_15min", "cadence", "energy_reading", misaligned.sum())

    # ---------- arithmetic / derived values ----------
    rep.add("production_batch.scrap=produced-good", "arithmetic", "production_batch",
            (batch["scrap_units"] != batch["produced_units"] - batch["good_units"]).sum())
    rep.add("production_batch.good<=produced", "arithmetic", "production_batch",
            (batch["good_units"] > batch["produced_units"]).sum())
    canc = batch["status"] == "CANCELLED"
    rep.add("production_batch.cancelled_has_no_actuals", "arithmetic", "production_batch",
            (canc & (batch["actual_start_utc"].notna() | (batch["produced_units"] > 0))).sum()
            + (~canc & batch["actual_start_utc"].isna()).sum())
    rep.add("maintenance_event.downtime_min=closed-started", "arithmetic", "maintenance_event",
            (mnt["downtime_min"] != ((mnt["closed_at"] - mnt["started_at"]) / pd.Timedelta(minutes=1))).sum())
    msi = d["machine_state_interval"]
    rep.add("machine_state_interval.duration_min=end-start", "arithmetic", "machine_state_interval",
            (msi["duration_min"] != ((msi["end_utc"] - msi["start_utc"]) / pd.Timedelta(minutes=1))).sum())
    rep.add("energy_reading.non_negative", "arithmetic", "energy_reading",
            ((er["interval_kwh"] < 0) | (er["avg_kw"] < 0)).sum())

    clean = er.sort_values("ingest_seq").drop_duplicates("reading_id", keep="first").sort_values(["meter_id", "ts_utc"])
    unit_bad = (clean["interval_kwh"] - clean["avg_kw"] * 0.25).abs() > 0.002
    rep.add("energy_reading.interval_kwh=avg_kw*0.25", "arithmetic", "energy_reading", unit_bad.sum(),
            explained=rep.explain_readings(clean[unit_bad], ["UNIT_KW_AS_KWH"]))
    prev_ts = clean.groupby("meter_id")["ts_utc"].shift(1)
    dreg = clean["register_kwh"] - clean.groupby("meter_id")["register_kwh"].shift(1)
    contiguous = (clean["ts_utc"] - prev_ts) == pd.Timedelta(minutes=15)
    reg_bad = contiguous & ((dreg - clean["interval_kwh"]).abs() > 0.002)
    rep.add("energy_reading.register_delta=interval_kwh", "reconciliation", "energy_reading", reg_bad.sum(),
            explained=rep.explain_readings(clean[reg_bad], ["UNIT_KW_AS_KWH", "REGISTER_INTERVAL_MISMATCH"]))
    gap_rows = prev_ts.notna() & ~contiguous
    rep.add("energy_reading.no_cadence_gaps", "cadence", "energy_reading", gap_rows.sum(),
            explained=rep.explain_readings(clean[gap_rows].assign(ts_utc=clean[gap_rows]["ts_utc"] - pd.Timedelta(minutes=15)),
                                           ["METER_GAP"]))
    rep.add("energy_reading.register_non_decreasing", "reconciliation", "energy_reading", (dreg < 0).sum())

    # main incomer >= sum of sub-meters, per plant-day (only on days with complete sub-meter data)
    cl = clean.merge(meter[["meter_id", "plant_id", "meter_type"]], on="meter_id")
    cl["day"] = cl["ts_utc"].dt.floor("D")
    cnt = cl[cl["meter_type"] == "SUB"].groupby(["plant_id", "day"])["meter_id"].size()
    daily = cl.pivot_table(index=["plant_id", "day"], columns="meter_type", values="interval_kwh", aggfunc="sum")
    full_days = cnt[cnt == 4 * 96].index
    dd = daily.loc[daily.index.intersection(full_days)]
    neg = dd[dd["MAIN"] < dd["SUB"]]
    expl = 0
    for (pid, day) in neg.index:
        g = gt[(gt["plant_id"] == pid) & gt["issue_type"].isin(["HIERARCHY_TOTAL_MISMATCH", "UNIT_KW_AS_KWH"])
               & (gt["window_start_utc"] < day + pd.Timedelta(days=1)) & (gt["window_end_utc"] > day)]
        expl += int(len(g) > 0)
    rep.add("hierarchy.main>=sum(sub)_daily", "reconciliation", "energy_reading", len(neg), explained=expl,
            sample=[f"{p} {t:%Y-%m-%d}" for p, t in neg.index])

    # ---------- hierarchy / join validity ----------
    mm = meter.set_index("meter_id")
    bad_parent = meter[(meter["meter_type"] == "SUB") & ~meter.apply(
        lambda r: r["parent_meter_id"] in mm.index and mm.loc[r["parent_meter_id"], "meter_type"] == "MAIN"
        and mm.loc[r["parent_meter_id"], "plant_id"] == r["plant_id"], axis=1)]
    bad_parent = pd.concat([bad_parent, meter[(meter["meter_type"] == "MAIN") & meter["parent_meter_id"].notna()]])
    rep.add("meter.hierarchy_parent_is_main_same_plant", "hierarchy", "meter", len(bad_parent))
    j = mmap.merge(meter[["meter_id", "plant_id", "meter_type"]], on="meter_id").merge(
        machine[["machine_id", "plant_id"]], on="machine_id", suffixes=("_m", "_x"))
    rep.add("meter_machine_map.same_plant_and_sub_meter", "hierarchy", "meter_machine_map",
            ((j["plant_id_m"] != j["plant_id_x"]) | (j["meter_type"] != "SUB")).sum())
    tagged = clean[clean["machine_id"].notna()].merge(mmap, on=["meter_id", "machine_id"], how="left")
    ok = (tagged["ts_utc"] >= tagged["effective_from"]) & (tagged["effective_to"].isna() | (tagged["ts_utc"] < tagged["effective_to"]))
    okr = tagged[ok]["reading_id"]
    viol = clean[clean["machine_id"].notna() & ~clean["reading_id"].isin(okr)]
    rep.add("energy_reading.machine_in_meter_hierarchy", "hierarchy", "energy_reading", len(viol),
            explained=rep.explain_readings(viol, ["MACHINE_OUTSIDE_HIERARCHY"]), sample=list(viol["reading_id"]))

    # ---------- tariffs ----------
    cov = tariff_lookup.coverage_issues(d["tariff_window"])
    rep.add("tariff_window.full_week_coverage_no_overlap", "tariff", "tariff_window", len(cov), sample=cov)
    tz = d["tariff"].merge(plant[["plant_id", "timezone"]], on="plant_id", suffixes=("", "_plant"))
    tzbad = tz[tz["timezone"] != tz["timezone_plant"]]
    rep.add("tariff.timezone=plant.timezone", "tariff", "tariff", len(tzbad),
            explained=tzbad["tariff_id"].isin(set(gt[gt["issue_type"] == "TARIFF_TZ_MISMATCH"]["entity_id"])).sum(),
            sample=list(tzbad["tariff_id"]))
    ov = 0
    for _, g in d["tariff"].groupby("plant_id"):
        g = g.sort_values("effective_from")
        prev_to = g["effective_to"].shift(1)
        ov += int(((prev_to.isna() & (g.index != g.index[0])) | (pd.to_datetime(prev_to) >= pd.to_datetime(g["effective_from"]))).sum())
    rep.add("tariff.versions_non_overlapping", "tariff", "tariff", ov)
    rep.add("tariff.currency=plant.currency", "tariff", "tariff",
            (d["tariff"].merge(plant, on="plant_id", suffixes=("", "_p")).pipe(lambda x: x["currency"] != x["currency_p"])).sum())

    # ---------- lifecycles + derived status ----------
    _lifecycle(rep, "batch", bev, "batch_id", "batch_status_event")
    _lifecycle(rep, "maintenance", d["maintenance_status_event"], "maintenance_id", "maintenance_status_event")
    _lifecycle(rep, "machine", d["machine_status_event"], "machine_id", "machine_status_event")
    _lifecycle(rep, "meter", d["meter_status_event"], "meter_id", "meter_status_event")
    for name, df, ev, key in [("production_batch", batch, bev, "batch_id"),
                              ("maintenance_event", mnt, d["maintenance_status_event"], "maintenance_id"),
                              ("machine", machine, d["machine_status_event"], "machine_id"),
                              ("meter", meter, d["meter_status_event"], "meter_id")]:
        last = ev.sort_values("event_ts", kind="stable").groupby(key)["to_status"].last()
        rep.add(f"{name}.status=last_event", "lifecycle", name, (df[key].map(last) != df["status"]).sum())

    # ---------- cross-entity consistency ----------
    b = batch.merge(inst[["shift_instance_id", "plant_id", "start_utc", "end_utc", "calendar_status"]],
                    on="shift_instance_id", suffixes=("", "_s"))
    rep.add("production_batch.within_shift_instance", "cross_entity", "production_batch",
            ((b["planned_start_utc"] < b["start_utc"]) | (b["planned_end_utc"] > b["end_utc"]) |
             (b["actual_end_utc"].notna() & (b["actual_end_utc"] > b["end_utc"]))).sum())
    rep.add("production_batch.shift_is_working_day_same_plant", "cross_entity", "production_batch",
            ((b["calendar_status"] != "WORKING") | (b["plant_id"] != b["plant_id_s"])).sum())
    bm = batch.merge(machine, on="machine_id", suffixes=("", "_m"))
    rep.add("production_batch.machine_production_in_service_same_plant", "cross_entity", "production_batch",
            ((~bm["is_production"]) | (bm["plant_id"] != bm["plant_id_m"]) | (bm["planned_start_utc"] < bm["commissioned_at"])
             | (bm["decommissioned_at"].notna() & (bm["planned_end_utc"] > bm["decommissioned_at"]))).sum())
    x = batch.dropna(subset=["actual_start_utc"]).merge(mnt[["machine_id", "started_at", "closed_at"]], on="machine_id")
    rep.add("production_batch.no_overlap_with_maintenance", "cross_entity", "production_batch",
            ((x["actual_start_utc"] < x["closed_at"]) & (x["actual_end_utc"] > x["started_at"])).sum())
    s = batch.dropna(subset=["actual_start_utc"]).sort_values(["machine_id", "actual_start_utc"])
    rep.add("production_batch.no_overlap_same_machine", "cross_entity", "production_batch",
            (s.groupby("machine_id")["actual_end_utc"].shift(1) > s["actual_start_utc"]).sum())
    ms = msi.sort_values(["machine_id", "start_utc"])
    rep.add("machine_state_interval.contiguous_per_machine", "cross_entity", "machine_state_interval",
            (ms.groupby("machine_id")["end_utc"].shift(1).notna() &
             (ms.groupby("machine_id")["end_utc"].shift(1) != ms["start_utc"])).sum())
    run = msi[msi["state"] == "RUNNING"]
    xb = batch.dropna(subset=["actual_start_utc"])
    covered = run.merge(xb[["machine_id", "actual_start_utc", "actual_end_utc"]], on="machine_id")
    covered = covered[(covered["start_utc"] >= covered["actual_start_utc"]) & (covered["end_utc"] <= covered["actual_end_utc"])]
    rep.add("machine_state_interval.running_inside_a_batch", "cross_entity", "machine_state_interval",
            len(run) - covered["state_interval_id"].nunique())
    me = d["machine_status_event"]
    lnk = me[me["maintenance_id"].notna()].merge(mnt[["maintenance_id", "machine_id"]], on="maintenance_id", suffixes=("", "_w"))
    rep.add("machine_status_event.maintenance_link_same_machine", "cross_entity", "machine_status_event",
            (lnk["machine_id"] != lnk["machine_id_w"]).sum())
    return rep.rows


def summarize(rows):
    df = pd.DataFrame(rows)
    return {"checks": len(df), "pass": int((df["status"] == "PASS").sum()),
            "expected_fail": int((df["status"] == "EXPECTED_FAIL").sum()), "fail": int((df["status"] == "FAIL").sum()),
            "by_category": df.groupby("category")["status"].value_counts().unstack(fill_value=0).to_dict("index")}


def write_report(rows, root):
    root = Path(root)
    summary = summarize(rows)
    (root / "validation_summary.json").write_text(json.dumps({"summary": summary, "checks": rows}, indent=2,
                                                             default=str), encoding="utf-8")
    lines = ["# Validation summary", "",
             f"**{summary['checks']} checks** — PASS {summary['pass']}, EXPECTED_FAIL {summary['expected_fail']} "
             f"(every failure is a labelled anomaly in ground_truth), FAIL {summary['fail']}.", "",
             "| Status | Check | Category | Failures | Explained by GT |", "|---|---|---|---:|---:|"]
    rank = {"FAIL": 0, "EXPECTED_FAIL": 1, "PASS": 2}
    for r in sorted(rows, key=lambda r: (rank[r["status"]], r["category"], r["check"])):
        lines.append(f"| {r['status']} | `{r['check']}` | {r['category']} | {r['failures']} | "
                     f"{r['explained_by_ground_truth']} |")
    (root / "validation_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
