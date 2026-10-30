"""ProductionBatch scheduling inside the shift calendar + BatchStatusEvent lifecycle history.

Lifecycle: PLANNED -> RELEASED -> RUNNING -> COMPLETED | SCRAPPED ; PLANNED/RELEASED -> CANCELLED.
batch.status is derived from the last event, never assigned independently.
"""
import numpy as np
import pandas as pd

from .. import config, ids
from ..timeutil import from_min

SHIFT_WEIGHT = {"A": 1.0, "B": 0.9, "C": 0.6}
MAX_PER_SLOT = 3


def _product_load(machine_type, product):
    """Each product has a characteristic load factor inside the machine type's range."""
    t = config.MACHINE_TYPES[machine_type]
    lo, hi = t["load_factor"]
    i, n = list(t["products"]).index(product), len(t["products"])
    return lo + (hi - lo) * (i + 0.5) / n


def build(masters, n_batches, rng):
    mach = masters["machine"]
    prod = mach[mach["is_production"]]
    inst = masters["shift_instance"]
    inst = inst[inst["calendar_status"] == "WORKING"]

    # candidate (machine, shift instance) slots where the machine is in service for the whole shift
    slots = []
    for _, m in prod.iterrows():
        cand = inst[inst["plant_id"] == m["plant_id"]]
        ok = cand["start_utc"] >= m["commissioned_at"]
        if pd.notna(m["decommissioned_at"]):
            ok &= cand["end_utc"] <= m["decommissioned_at"]
        for _, s in cand[ok].iterrows():
            w = SHIFT_WEIGHT[s["shift_id"][-1]] * (0.5 if s["business_date"].weekday() == 5 else 1.0)
            slots.append((m["machine_id"], s["shift_instance_id"], int(s["start_min"]), int(s["end_min"]), w))
    slots.sort(key=lambda x: (x[2], x[0]))
    w = np.array([s[4] for s in slots])
    counts = np.bincount(rng.choice(len(slots), size=n_batches, p=w / w.sum()), minlength=len(slots))
    # cap at MAX_PER_SLOT and push overflow to the next free slot (deterministic order)
    overflow = int(np.clip(counts - MAX_PER_SLOT, 0, None).sum())
    counts = np.minimum(counts, MAX_PER_SLOT)
    order = rng.permutation(len(slots))
    i = 0
    while overflow > 0:
        j = order[i % len(slots)]
        if counts[j] < MAX_PER_SLOT:
            counts[j] += 1
            overflow -= 1
        i += 1

    mtype = dict(zip(mach["machine_id"], mach["machine_type"]))
    rows = []
    for (mid, siid, s, e, _), k in zip(slots, counts):
        if k == 0:
            continue
        length = e - s
        warm = int(rng.integers(10, 41))
        avail = length - warm - 10
        gaps = [int(rng.integers(15, 51)) for _ in range(k - 1)]
        if k == 1:
            durs = [int(avail * rng.uniform(0.45, 0.85))]
        else:
            run_avail = avail - sum(gaps)
            durs = [int(d) for d in run_avail * rng.dirichlet(np.full(k, 6.0)) * rng.uniform(0.80, 0.95)]
        t = s + warm
        for b in range(k):
            dur = durs[b]
            products = config.MACHINE_TYPES[mtype[mid]]["products"]
            pcode = list(products)[int(rng.integers(0, len(products)))]
            rate, uom = products[pcode]
            delay = int(rng.integers(0, 9))
            a_start = t + delay
            a_end = min(a_start + int(dur * rng.uniform(0.97, 1.05)), e - 2)
            if b < k - 1:
                a_end = min(a_end, t + dur + gaps[b] - 5)
            planned_units = int(round(rate * dur / 60 * rng.uniform(0.96, 1.04)))
            u = rng.random()
            status = "CANCELLED" if u < 0.015 else "SCRAPPED" if u < 0.035 else "COMPLETED"
            if status == "CANCELLED":
                produced = good = 0
                a_start_v = a_end_v = None
            else:
                run_h = (a_end - a_start) / 60
                produced = int(round(rate * run_h * rng.uniform(0.93, 1.01)))
                good = int(round(produced * (rng.uniform(0.10, 0.50) if status == "SCRAPPED"
                                             else rng.uniform(0.960, 0.995))))
                a_start_v, a_end_v = a_start, a_end
            rows.append({"machine_id": mid, "shift_instance_id": siid, "product_code": pcode, "unit_of_measure": uom,
                         "planned_start_min": t, "planned_end_min": t + dur, "actual_start_min": a_start_v,
                         "actual_end_min": a_end_v, "planned_units": planned_units, "produced_units": produced,
                         "good_units": good, "scrap_units": produced - good, "final": status,
                         "load_factor": _product_load(mtype[mid], pcode) * (1 + rng.normal(0, 0.025)),
                         "plan_lead_h": int(rng.integers(24, 73)), "release_lead_min": int(rng.integers(30, 181)),
                         "qc_lag_min": int(rng.integers(5, 46))})
            t += dur + (gaps[b] if b < k - 1 else 0)

    df = pd.DataFrame(rows).sort_values(["planned_start_min", "machine_id"]).reset_index(drop=True)
    df.insert(0, "batch_id", [ids.batch(i + 1) for i in range(len(df))])
    plant_of = dict(zip(mach["machine_id"], mach["plant_id"]))
    df.insert(1, "plant_id", df["machine_id"].map(plant_of))

    # lifecycle events (append-only history)
    ev = []
    for r in df.itertuples():
        ps = from_min(r.planned_start_min)
        ev.append((r.batch_id, "PLANNED", ps.floor("h") - pd.Timedelta(hours=r.plan_lead_h), "planner"))
        ev.append((r.batch_id, "RELEASED", ps - pd.Timedelta(minutes=r.release_lead_min), "planner"))
        if r.final == "CANCELLED":
            ev.append((r.batch_id, "CANCELLED", ps, "operator"))
        else:
            ev.append((r.batch_id, "RUNNING", from_min(r.actual_start_min), "operator"))
            if r.final == "SCRAPPED":
                ev.append((r.batch_id, "SCRAPPED", from_min(r.actual_end_min) + pd.Timedelta(minutes=r.qc_lag_min),
                           "quality_engineer"))
            else:
                ev.append((r.batch_id, "COMPLETED", from_min(r.actual_end_min), "operator"))
    events = pd.DataFrame(ev, columns=["batch_id", "status", "event_ts", "actor_role"])
    events = events.sort_values(["event_ts", "batch_id"], kind="stable").reset_index(drop=True)
    events.insert(0, "batch_event_id", [ids.batch_event(i + 1) for i in range(len(events))])
    prev = events.groupby("batch_id")["status"].shift(1)
    events.insert(3, "from_status", prev.where(prev.notna(), None))
    events = events.rename(columns={"status": "to_status"})
    last = events.sort_values("event_ts", kind="stable").groupby("batch_id")["to_status"].last()
    df["status"] = df["batch_id"].map(last)
    return df, events
