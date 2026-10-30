"""Shared helpers for the analytics: run grouping, findings accumulator, bridge lookup."""
import numpy as np
import pandas as pd

Q = pd.Timedelta(minutes=15)


def runs(flags, max_gap=0):
    """(start, end_exclusive) index pairs of True runs, merging runs separated by <= max_gap False entries."""
    flags = np.asarray(flags, dtype=bool)
    d = np.diff(np.concatenate([[0], flags.astype(np.int8), [0]]))
    starts, ends = list(np.flatnonzero(d == 1)), list(np.flatnonzero(d == -1))
    merged = []
    for s, e in zip(starts, ends):
        if merged and s - merged[-1][1] <= max_gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(int(s), int(e)) for s, e in merged]


class Findings:
    def __init__(self):
        self.rows = []

    def add(self, issue_type, category, plant_id, entity_type, entity_id, start, end, rule_id, decision,
            owner_role, detail, metric_value=None, metric_unit=None, impact_kwh=None):
        self.rows.append({"issue_type": issue_type, "category": category, "plant_id": plant_id,
                          "entity_type": entity_type, "entity_id": entity_id, "window_start_utc": start,
                          "window_end_utc": end, "rule_id": rule_id, "decision": decision,
                          "metric_value": None if metric_value is None else round(float(metric_value), 3),
                          "metric_unit": metric_unit,
                          "impact_kwh": None if impact_kwh is None else round(float(impact_kwh), 3),
                          "owner_role": owner_role, "detail": detail})

    def frame(self):
        from .. import ids
        df = pd.DataFrame(self.rows)
        df = df.sort_values(["window_start_utc", "issue_type", "entity_id"], kind="stable").reset_index(drop=True)
        df.insert(0, "finding_id", [ids.finding(i + 1) for i in range(len(df))])
        return df


def mapped_machine(meter_ids, ts, mmap):
    """Machine mapped to each (meter, ts) by the effective-dated bridge (single-machine meters only)."""
    out = pd.Series([None] * len(ts), index=ts.index, dtype=object)
    for mp in mmap.itertuples():
        sel = (meter_ids == mp.meter_id) & (ts >= mp.effective_from)
        if pd.notna(mp.effective_to):
            sel &= ts < mp.effective_to
        out[sel] = mp.machine_id
    return out
