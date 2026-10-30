"""Turn true meter energy into raw EnergyReading records, then inject labelled data-error edge cases.

Device-level (before registers): CT-ratio misconfiguration on a sub-meter -> HIERARCHY_TOTAL_MISMATCH.
Record-level: register jump / drift (REGISTER_INTERVAL_MISMATCH), kW written into the kWh field
(UNIT_KW_AS_KWH), telemetry gaps (METER_GAP), machine tags outside the meter hierarchy
(MACHINE_OUTSIDE_HIERARCHY), duplicate retransmissions (DUPLICATE_READING), and a tariff entered in the
wrong timezone (TARIFF_TZ_MISMATCH). Every injection writes a ground-truth row; unrelated rows are untouched.
"""
import numpy as np
import pandas as pd

from .. import config, ids
from ..timeutil import START, from_min, to_min


def _n(rate, days, lo=1):
    return max(lo, round(rate * days / 30))


class Reserver:
    """Keeps injected windows on the same meter from overlapping each other (or a scenario window)."""

    def __init__(self, meters, n_int):
        self.busy = {m: np.zeros(n_int, dtype=bool) for m in meters}
        self.n_int = n_int

    def mark(self, meter, a, b, pad=2):
        self.busy[meter][max(0, a - pad):min(self.n_int, b + pad)] = True

    def pick(self, rng, meters, length, lo=1, hi=None):
        hi = (hi or self.n_int) - length - 2
        for _ in range(500):
            m = meters[int(rng.integers(0, len(meters)))]
            a = int(rng.integers(lo, hi))
            if not self.busy[m][max(0, a - 2):a + length + 2].any():
                self.mark(m, a, a + length)
                return m, a
        raise RuntimeError("could not place injection window")


def build(masters, meter_kwh, scen_gt, swap, days, rng):
    n_int = days * 96
    meters = masters["meter"]
    maps = masters["meter_machine_map"]
    sub_ids = list(meters[meters["meter_type"] == "SUB"]["meter_id"])
    mach_meters = list(meters[meters["measured_scope"] == "MACHINE"]["meter_id"])
    all_ids = list(meters["meter_id"])
    res = Reserver(all_ids, n_int)
    gt = []
    meter_plant = dict(zip(meters["meter_id"], meters["plant_id"]))
    machine_meter = {}
    for mp in maps.itertuples():
        machine_meter.setdefault(mp.machine_id, mp.meter_id)
    for g in scen_gt:  # scenario windows are off-limits for data-error injection on the same meter
        mtr = g["entity_id"] if g["entity_type"] == "meter" else machine_meter[g["entity_id"]]
        res.mark(mtr, g["start_min"] // 15, -(-g["end_min"] // 15))

    def add(issue, mtr, a, b, impact, params, detection, decision, entity_type="meter", entity_id=None):
        gt.append({"issue_type": issue, "category": "DATA_ERROR", "plant_id": meter_plant.get(mtr, mtr[4:9]),
                   "entity_type": entity_type, "entity_id": entity_id or mtr, "start_min": a * 15, "end_min": b * 15,
                   "impact_kwh": round(float(impact), 2), "params": params, "expected_detection": detection,
                   "expected_decision": decision})

    kwh = {m: v.copy() for m, v in meter_kwh.items()}

    # ---- device level: CT ratio misconfigured on a sub-meter (register and interval both scaled) ----
    for _ in range(_n(config.EDGE["ct_windows_per_30d"], days)):
        length = int(rng.integers(48, 97)) if days < 30 else int(rng.integers(96, 289))
        m, a = res.pick(rng, sub_ids, length, lo=96)
        extra = kwh[m][a:a + length].sum()
        kwh[m][a:a + length] *= 2.0
        add("HIERARCHY_TOTAL_MISMATCH", m, a, a + length, extra, {"configured_ct": "x2 of installed"},
            "R-HIER-01", "QUARANTINE_SUBMETER_AND_VERIFY_CT")

    interval = {m: np.round(v, 3) for m, v in kwh.items()}
    init = {m: round(float(rng.uniform(1e4, 9e5)), 3) for m in all_ids}
    register = {m: np.round(init[m] + np.cumsum(interval[m]), 3) for m in all_ids}
    avg_kw = {m: np.round(interval[m] * 4, 3) for m in all_ids}

    # ---- telemetry gaps (sub-meters); registers keep counting so the gap energy is recoverable ----
    gaps = []
    for i in range(_n(config.SCENARIO["gaps_per_meter_per_30d"] * len(sub_ids), days, lo=2)):
        length = int(rng.integers(24, 65)) if i == 0 else int(rng.integers(4, 49))
        m, a = res.pick(rng, sub_ids, length, lo=4, hi=n_int - 4)
        gaps.append((m, a, a + length))
        gt.append({"issue_type": "METER_GAP", "category": "TELEMETRY_GAP", "plant_id": meter_plant[m],
                   "entity_type": "meter", "entity_id": m, "start_min": a * 15, "end_min": (a + length) * 15,
                   "impact_kwh": round(float(interval[m][a:a + length].sum()), 2),
                   "params": {"missing_intervals": length}, "expected_detection": "R-GAP-01",
                   "expected_decision": "BACKFILL_FROM_REGISTER_DELTA"})

    # ---- register jump (meter reset / replacement offset) ----
    for _ in range(_n(config.EDGE["register_jumps_per_30d"], days)):
        m, a = res.pick(rng, all_ids, 1, lo=4)
        jump = round(float(rng.uniform(500, 5000)), 3)
        register[m][a:] = np.round(register[m][a:] + jump, 3)
        add("REGISTER_INTERVAL_MISMATCH", m, a, a + 1, jump, {"variant": "JUMP", "offset_kwh": jump},
            "R-REG-01", "USE_INTERVAL_SUM_AND_RAISE_METER_TICKET")

    # ---- register drift (calibration drift: register advances 3% faster than intervals) ----
    for _ in range(_n(config.EDGE["register_drifts_per_30d"], days)):
        length = int(rng.integers(24, 49)) if days < 30 else int(rng.integers(96, 193))
        m, a = res.pick(rng, all_ids, length, lo=4)
        extra = np.cumsum(interval[m][a:a + length] * 0.03)
        register[m][a:a + length] = np.round(register[m][a:a + length] + extra, 3)
        register[m][a + length:] = np.round(register[m][a + length:] + extra[-1], 3)
        add("REGISTER_INTERVAL_MISMATCH", m, a, a + length, extra[-1], {"variant": "DRIFT", "drift_pct": 3.0},
            "R-REG-01", "USE_INTERVAL_SUM_AND_RAISE_METER_TICKET")

    # ---- kW written into the kWh field (firmware/config error) ----
    for _ in range(_n(config.EDGE["unit_windows_per_30d"], days)):
        length = int(rng.integers(24, 145))
        m, a = res.pick(rng, all_ids, length, lo=4)
        over = (avg_kw[m][a:a + length] - interval[m][a:a + length]).sum()
        interval[m][a:a + length] = avg_kw[m][a:a + length]
        add("UNIT_KW_AS_KWH", m, a, a + length, over, {"factor": 4.0}, "R-UNIT-01", "DIVIDE_BY_4_AND_FIX_CONFIG")

    # ---- assemble records ----
    ts = START + pd.to_timedelta(np.arange(n_int) * 15, unit="min")
    frames = []
    for m in all_ids:
        keep = np.ones(n_int, dtype=bool)
        for gm, a, b in gaps:
            if gm == m:
                keep[a:b] = False
        frames.append(pd.DataFrame({"meter_id": m, "idx": np.arange(n_int)[keep], "interval_kwh": interval[m][keep],
                                    "avg_kw": avg_kw[m][keep], "register_kwh": register[m][keep]}))
    rd = pd.concat(frames, ignore_index=True)
    rd["ts_utc"] = ts[rd["idx"].to_numpy()]

    # machine attribution from the effective-dated bridge (machine meters only)
    rd["machine_id"] = None
    for mp in maps[maps["meter_id"].isin(mach_meters)].itertuples():
        sel = (rd["meter_id"] == mp.meter_id) & (rd["ts_utc"] >= mp.effective_from)
        if pd.notna(mp.effective_to):
            sel &= rd["ts_utc"] < mp.effective_to
        rd.loc[sel, "machine_id"] = mp.machine_id

    # ---- machine tags outside the meter hierarchy ----
    all_machines = list(masters["machine"]["machine_id"])
    tag_windows = []
    if swap is not None and to_min(swap["ts"]) < days * 1440:
        a0 = to_min(swap["ts"]) // 15
        length = int(rng.integers(16, 49))
        if not res.busy[swap["meter_id"]][a0:a0 + length + 2].any() and a0 + length < n_int:
            res.mark(swap["meter_id"], a0, a0 + length)
            tag_windows.append((swap["meter_id"], a0, length, swap["old"], "STALE_AFTER_REMAP"))
    for _ in range(_n(config.EDGE["tag_windows_per_30d"], days)):
        length = int(rng.integers(8, 49))
        m, a = res.pick(rng, mach_meters, length, lo=4)
        own = set(maps[maps["meter_id"] == m]["machine_id"])
        foreign = [x for x in all_machines if x not in own]
        tag_windows.append((m, a, length, foreign[int(rng.integers(0, len(foreign)))], "FOREIGN_MACHINE"))
    for m, a, length, wrong, variant in tag_windows:
        sel = (rd["meter_id"] == m) & rd["idx"].between(a, a + length - 1)
        rd.loc[sel, "machine_id"] = wrong
        add("MACHINE_OUTSIDE_HIERARCHY", m, a, a + length, rd.loc[sel, "interval_kwh"].sum(),
            {"variant": variant, "tagged_machine_id": wrong}, "R-HIER-02", "REATTRIBUTE_TO_MAPPED_MACHINE")

    # ---- ingestion metadata + duplicate retransmissions ----
    rd["reading_id"] = [ids.reading(m, t) for m, t in zip(rd["meter_id"], rd["ts_utc"])]
    lat = rng.uniform(5, 90, len(rd))
    rd["ingested_at"] = (rd["ts_utc"] + pd.Timedelta(minutes=15) + pd.to_timedelta(lat, unit="s")).dt.floor("s")
    free = np.array([not res.busy[m][i] for m, i in zip(rd["meter_id"], rd["idx"])])
    free &= (rd["idx"] > 4).to_numpy() & (rd["idx"] < n_int - 4).to_numpy()
    n_dup = max(4, int(round(config.EDGE["duplicate_rate"] * len(rd))))
    pick = np.sort(rng.choice(np.flatnonzero(free), size=n_dup, replace=False))
    dups = rd.iloc[pick].copy()
    conflicting = rng.random(n_dup) < 0.5
    factor = 1 + rng.choice([-1, 1], n_dup) * rng.uniform(0.01, 0.05, n_dup)
    dups.loc[conflicting, "interval_kwh"] = np.round(dups.loc[conflicting, "interval_kwh"] * factor[conflicting], 3)
    dups.loc[conflicting, "avg_kw"] = np.round(dups.loc[conflicting, "interval_kwh"] * 4, 3)
    dups["ingested_at"] = dups["ingested_at"] + pd.to_timedelta(rng.integers(60, 3601, n_dup), unit="s")
    for (_, d), c in zip(dups.iterrows(), conflicting):
        gt.append({"issue_type": "DUPLICATE_READING", "category": "DATA_ERROR", "plant_id": meter_plant[d.meter_id],
                   "entity_type": "reading", "entity_id": d.reading_id, "start_min": int(d.idx) * 15,
                   "end_min": int(d.idx) * 15 + 15, "impact_kwh": round(float(d.interval_kwh), 3),
                   "params": {"variant": "CONFLICTING" if c else "EXACT", "meter_id": d.meter_id},
                   "expected_detection": "R-DUP-01",
                   "expected_decision": "KEEP_REGISTER_CONSISTENT_ROW" if c else "DROP_LATER_COPY"})
    rd = pd.concat([rd, dups], ignore_index=True)
    rd = rd.sort_values(["ingested_at", "meter_id", "ts_utc"], kind="stable").reset_index(drop=True)
    rd.insert(0, "ingest_seq", np.arange(1, len(rd) + 1))
    rd["unit"] = "kWh"
    rd["source_system"] = rd["meter_id"].map(dict(zip(meters["meter_id"], meters["source_system"])))
    rd = rd[["ingest_seq", "reading_id", "meter_id", "machine_id", "ts_utc", "interval_kwh", "avg_kw",
             "register_kwh", "unit", "source_system", "ingested_at"]]

    # ---- tariff entered with the wrong timezone (windows are plant-local, label says UTC) ----
    tariffs = masters["tariff"]
    tz_plant = masters["plant"].iloc[min(1, len(masters["plant"]) - 1)]
    last_local = (START + pd.Timedelta(days=days) - pd.Timedelta(minutes=1)).tz_convert(tz_plant.timezone).date()
    cand = tariffs[(tariffs["plant_id"] == tz_plant.plant_id) & (tariffs["effective_from"] <= last_local)]
    t = cand.sort_values("effective_from").iloc[-1]
    tariffs.loc[tariffs["tariff_id"] == t.tariff_id, "timezone"] = "UTC"
    eff_from = max(START, pd.Timestamp(t.effective_from).tz_localize(tz_plant.timezone).tz_convert("UTC"))
    gt.append({"issue_type": "TARIFF_TZ_MISMATCH", "category": "DATA_ERROR", "plant_id": tz_plant.plant_id,
               "entity_type": "tariff", "entity_id": t.tariff_id, "start_min": to_min(eff_from),
               "end_min": days * 1440, "impact_kwh": 0.0,
               "params": {"recorded_timezone": "UTC", "plant_timezone": tz_plant.timezone},
               "expected_detection": "R-TZ-01", "expected_decision": "REINTERPRET_WINDOWS_IN_PLANT_LOCAL_TIME"})

    # ---- meter status history: install + comm-loss episodes for long gaps ----
    mev = []
    for mt in meters.itertuples():
        mev.append((mt.meter_id, None, "ACTIVE", mt.installed_at, "Commissioned"))
    for m, a, b in gaps:
        if (b - a) * 15 >= 240:
            mev.append((m, "ACTIVE", "COMM_LOSS", from_min(a * 15), "No telemetry received"))
            mev.append((m, "COMM_LOSS", "ACTIVE", from_min(b * 15), "Telemetry restored"))
    mev = pd.DataFrame(mev, columns=["meter_id", "from_status", "to_status", "event_ts", "note"])
    mev = mev.sort_values(["event_ts", "meter_id"], kind="stable").reset_index(drop=True)
    mev.insert(0, "meter_event_id", [ids.meter_event(i + 1) for i in range(len(mev))])
    return rd, gt, mev
