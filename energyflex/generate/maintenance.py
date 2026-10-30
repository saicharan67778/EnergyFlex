"""Intensity-drift plan, MaintenanceEvent work orders and the machine/maintenance lifecycle event history.

Work order lifecycle: OPEN -> IN_PROGRESS -> CLOSED.
Machine lifecycle:    INSTALLED -> ACTIVE <-> UNDER_MAINTENANCE ; ACTIVE -> DECOMMISSIONED.
All maintenance runs on Sundays when no plant has a shift, so it never overlaps a batch.
"""
import pandas as pd

from .. import config, ids
from ..timeutil import START, local_to_utc, to_min


def _sunday_date(day_idx, tz):
    return (START + pd.Timedelta(days=day_idx, hours=12)).tz_convert(tz).date()


def plan_drifts(masters, days):
    """Drift #1: plant 1 / machine 1, repaired by corrective maintenance. Drift #2 (full only): ongoing."""
    plants = masters["plant"]
    tz = dict(zip(plants["plant_id"], plants["timezone"]))
    b = config.baseline_days(days)
    drifts = []
    p1 = plants["plant_id"].iloc[0]
    start = max(b, round(config.SCENARIO["drift_frac_start"] * days))
    sundays = list(range(6, days, 7))
    fix_day = next((d for d in sundays if d >= start + 21), sundays[-1])
    fix = local_to_utc(_sunday_date(fix_day, tz[p1]), "07:00", tz[p1])
    drifts.append({"machine_id": ids.machine(p1, 1), "start_min": start * 1440,
                   "ramp_end_min": min(start * 1440 + 14 * 1440, to_min(fix)), "fix_ts": fix, "max_mult": 1.25})
    if len(plants) >= 3:
        p3 = plants["plant_id"].iloc[2]
        s2 = round(0.78 * days)
        drifts.append({"machine_id": ids.machine(p3, 3), "start_min": s2 * 1440,
                       "ramp_end_min": min((s2 + 10) * 1440, days * 1440), "fix_ts": None, "max_mult": 1.22})
    return drifts


def build(masters, drifts, days, rng):
    mach = masters["machine"]
    tz = dict(zip(masters["plant"]["plant_id"], masters["plant"]["timezone"]))
    corrective = {d["machine_id"]: d["fix_ts"] for d in drifts if d["fix_ts"] is not None}
    wo = []
    for p_idx, (pid, g) in enumerate(mach.groupby("plant_id", sort=True)):
        for m in g[g["is_production"]].itertuples():
            mno = int(m.machine_id[-3:])
            for week, sunday in enumerate(range(6, days, 7)):
                d = _sunday_date(sunday, tz[pid])
                start = local_to_utc(d, "07:00" if m.machine_id in corrective else "08:00", tz[pid])
                in_service = start >= m.commissioned_at and (pd.isna(m.decommissioned_at) or start < m.decommissioned_at)
                if not in_service:
                    continue
                if corrective.get(m.machine_id) == start:
                    wo.append({"machine_id": m.machine_id, "plant_id": pid, "maintenance_type": "CORRECTIVE",
                               "reason": "Rising kWh/unit; heater/drive degradation suspected",
                               "opened_at": start - pd.Timedelta(days=2, hours=3), "started_at": start,
                               "closed_at": local_to_utc(d, "15:00", tz[pid]), "raised_by_role": "maintenance_engineer"})
                elif (week + mno + p_idx) % 4 == 0:
                    wo.append({"machine_id": m.machine_id, "plant_id": pid, "maintenance_type": "PREVENTIVE",
                               "reason": "Scheduled 4-weekly PM", "opened_at": start - pd.Timedelta(days=7),
                               "started_at": start, "closed_at": start + pd.Timedelta(hours=int(rng.integers(3, 5))),
                               "raised_by_role": "maintenance_engineer"})
    wo = pd.DataFrame(wo).sort_values(["started_at", "machine_id"]).reset_index(drop=True)
    wo.insert(0, "maintenance_id", [ids.maintenance(i + 1) for i in range(len(wo))])
    wo["downtime_min"] = ((wo["closed_at"] - wo["started_at"]) / pd.Timedelta(minutes=1)).astype(int)

    mev = []
    for r in wo.itertuples():
        mev += [(r.maintenance_id, None, "OPEN", r.opened_at), (r.maintenance_id, "OPEN", "IN_PROGRESS", r.started_at),
                (r.maintenance_id, "IN_PROGRESS", "CLOSED", r.closed_at)]
    mev = pd.DataFrame(mev, columns=["maintenance_id", "from_status", "to_status", "event_ts"])
    mev = mev.sort_values(["event_ts", "maintenance_id"], kind="stable").reset_index(drop=True)
    mev.insert(0, "maintenance_event_id", [ids.maintenance_event(i + 1) for i in range(len(mev))])
    wo["status"] = wo["maintenance_id"].map(mev.groupby("maintenance_id")["to_status"].last())

    # machine lifecycle derived from commissioning, maintenance and decommissioning
    cev = []
    for m in mach.itertuples():
        cev.append((m.machine_id, None, "INSTALLED", m.commissioned_at - pd.Timedelta(days=3), None))
        cev.append((m.machine_id, "INSTALLED", "ACTIVE", m.commissioned_at, None))
        for r in wo[wo["machine_id"] == m.machine_id].itertuples():
            cev.append((m.machine_id, "ACTIVE", "UNDER_MAINTENANCE", r.started_at, r.maintenance_id))
            cev.append((m.machine_id, "UNDER_MAINTENANCE", "ACTIVE", r.closed_at, r.maintenance_id))
        if pd.notna(m.decommissioned_at):
            cev.append((m.machine_id, "ACTIVE", "DECOMMISSIONED", m.decommissioned_at, None))
    cev = pd.DataFrame(cev, columns=["machine_id", "from_status", "to_status", "event_ts", "maintenance_id"])
    cev = cev.sort_values(["event_ts", "machine_id"], kind="stable").reset_index(drop=True)
    cev.insert(0, "machine_event_id", [ids.machine_event(i + 1) for i in range(len(cev))])
    return wo, mev, cev
