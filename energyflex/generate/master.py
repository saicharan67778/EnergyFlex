"""Master / reference data: Plant, Meter (hierarchy), Machine, MeterMachineMap bridge, Shift calendar, Tariffs."""
import datetime as dt

import pandas as pd

from .. import config, ids
from ..timeutil import DAY_NAMES, START, end, local_to_utc, to_min


def _label(machine_type):
    return machine_type.replace("_", " ").title().replace("Cnc", "CNC").replace("Hvac Ahu", "HVAC AHU")


def swap_day(days):
    """Sunday (day index 6 + 7k) closest to 53% of the period."""
    target = days * 0.53
    sundays = [d for d in range(6, days, 7)]
    return min(sundays, key=lambda d: (abs(d - target), d))


def build(scale, rng):
    days = scale["days"]
    plants_cfg = config.PLANTS[: scale["n_plants"]]
    window_end = end(days)

    plants, meters, machines, maps, shifts, instances, tariffs, windows = ([] for _ in range(8))
    swap = None
    map_n = 0
    tariff_n = 0

    for p_idx, pc in enumerate(plants_cfg):
        pid = pc["plant_id"]
        tz = pc["timezone"]
        plants.append({
            "plant_id": pid, "plant_name": pc["name"], "city": pc["city"], "country_code": pc["country"],
            "timezone": tz, "currency": pc["currency"], "latitude": pc["lat"], "longitude": pc["lon"],
            "status": "ACTIVE",
        })

        # --- Meter hierarchy: 001 MAIN incomer -> 002..004 machine sub-meters, 005 utilities sub-meter
        main_id = ids.meter(pid, 1)
        installed = pd.Timestamp("2024-03-01", tz="UTC") + pd.Timedelta(days=30 * p_idx)
        meter_rows = [(1, None, "MAIN", "PLANT_INCOMER", "AMI", "2000/5")]
        meter_rows += [(n, main_id, "SUB", "MACHINE", "SCADA", "400/5") for n in (2, 3, 4)]
        meter_rows += [(5, main_id, "SUB", "UTILITIES", "SCADA", "300/5")]
        for n, parent, mtype, scope, src, ct in meter_rows:
            meters.append({
                "meter_id": ids.meter(pid, n), "plant_id": pid, "parent_meter_id": parent, "meter_type": mtype,
                "measured_scope": scope, "serial_no": f"EM{p_idx + 1}{n:02d}-{int(rng.integers(100000, 999999))}",
                "source_system": src, "energy_unit": "kWh", "demand_unit": "kW",
                "sampling_interval_min": config.INTERVAL_MIN, "ct_ratio": ct, "installed_at": installed,
                "status": "ACTIVE",
            })

        # --- Machines: 001..003 production, 004 compressor, 005 HVAC, (006 replacement unit)
        commissioned = pd.Timestamp("2022-06-01", tz="UTC") + pd.Timedelta(days=45 * p_idx)
        mlist = [(i + 1, mt, kw) for i, (mt, kw) in enumerate(pc["machines"])]
        mlist += [(4, "AIR_COMPRESSOR", pc["compressor_kw"]), (5, "HVAC_AHU", pc["hvac_kw"])]
        for n, mt, kw in mlist:
            t = config.MACHINE_TYPES[mt]
            machines.append({
                "machine_id": ids.machine(pid, n), "plant_id": pid, "machine_type": mt,
                "machine_name": f"{pc['city']} {_label(mt)} {n}",
                "is_production": t["production"], "rated_kw": float(kw),
                "idle_kw": round(kw * t["idle_frac"], 2), "standby_kw": round(kw * t["standby_frac"], 2),
                "commissioned_at": commissioned, "decommissioned_at": pd.NaT, "status": "ACTIVE",
            })

        if p_idx == config.SWAP["plant_index"]:
            sd = swap_day(days)
            swap_date = (START + pd.Timedelta(days=sd, hours=12)).tz_convert(tz).date()
            swap_ts = local_to_utc(swap_date, "00:00", tz)
            old = next(m for m in machines if m["machine_id"] == ids.machine(pid, config.SWAP["machine_no"]))
            old["decommissioned_at"] = swap_ts
            old["status"] = "DECOMMISSIONED"
            kw = config.SWAP["new_rated_kw"]
            t = config.MACHINE_TYPES[old["machine_type"]]
            new_id = ids.machine(pid, 6)
            machines.append({
                "machine_id": new_id, "plant_id": pid, "machine_type": old["machine_type"],
                "machine_name": f"{pc['city']} {_label(old['machine_type'])} 6 (replacement)",
                "is_production": True, "rated_kw": float(kw), "idle_kw": round(kw * t["idle_frac"] * 0.85, 2),
                "standby_kw": round(kw * t["standby_frac"] * 0.85, 2),
                "commissioned_at": swap_ts, "decommissioned_at": pd.NaT, "status": "ACTIVE",
            })
            swap = {"plant_id": pid, "old": old["machine_id"], "new": new_id, "ts": swap_ts,
                    "meter_id": ids.meter(pid, 1 + config.SWAP["machine_no"]),
                    "efficiency": config.SWAP["efficiency"]}

        # --- Meter -> machine bridge (N:M capable, effective-dated; history rows are never overwritten)
        bridge = [(2, 1), (3, 2), (4, 3), (5, 4), (5, 5)]
        for mtr_n, mch_n in bridge:
            map_n += 1
            mch = ids.machine(pid, mch_n)
            eff_to = swap["ts"] if swap and swap["old"] == mch else pd.NaT
            maps.append({"map_id": ids.mapping(map_n), "meter_id": ids.meter(pid, mtr_n), "machine_id": mch,
                         "allocation_pct": 100.0, "effective_from": installed, "effective_to": eff_to})
        if swap and swap["plant_id"] == pid:
            map_n += 1
            maps.append({"map_id": ids.mapping(map_n), "meter_id": swap["meter_id"], "machine_id": swap["new"],
                         "allocation_pct": 100.0, "effective_from": swap["ts"], "effective_to": pd.NaT})

        # --- Shifts + shift calendar (local wall clock -> UTC, DST aware)
        for code in pc["shifts"]:
            s, e = config.SHIFT_TEMPLATES[code]
            wd = config.WEEKDAYS + (",SAT" if code in pc["saturday_shifts"] else "")
            shifts.append({"shift_id": ids.shift(pid, code), "plant_id": pid, "shift_code": code,
                           "start_local": s, "end_local": e, "crosses_midnight": e <= s, "working_days": wd})
        first_local = (START.tz_convert(tz) - pd.Timedelta(days=1)).date()
        last_local = window_end.tz_convert(tz).date()
        d = first_local
        while d <= last_local:
            dow = DAY_NAMES[d.weekday()]
            for code in pc["shifts"]:
                if dow == "SUN" or (dow == "SAT" and code not in pc["saturday_shifts"]):
                    continue
                s, e = config.SHIFT_TEMPLATES[code]
                su = local_to_utc(d, s, tz)
                eu = local_to_utc(d + dt.timedelta(days=1) if e <= s else d, e, tz)
                if su < START or eu > window_end:
                    continue
                instances.append({
                    "shift_instance_id": ids.shift_instance(pid, d, code), "shift_id": ids.shift(pid, code),
                    "plant_id": pid, "business_date": d, "start_utc": su, "end_utc": eu,
                    "calendar_status": "HOLIDAY" if d.isoformat() in pc["holidays"] else "WORKING",
                })
            d += dt.timedelta(days=1)

        # --- Tariffs + time-of-use windows (defined in plant local time)
        for v, tc in enumerate(pc["tariffs"], start=1):
            tariff_n += 1
            tid = ids.tariff(tariff_n)
            tariffs.append({
                "tariff_id": tid, "plant_id": pid, "utility_name": tc["utility"], "tariff_version": v,
                "currency": pc["currency"], "timezone": tz,
                "effective_from": dt.date.fromisoformat(tc["from"]),
                "effective_to": dt.date.fromisoformat(tc["to"]) if tc["to"] else None,
                "demand_charge_per_kw_month": tc["demand"],
            })
            for w_n, (period, days_str, s, e, rate) in enumerate(tc["windows"], start=1):
                windows.append({"window_id": ids.tariff_window(tid, w_n), "tariff_id": tid, "period": period,
                                "days_of_week": days_str, "start_local": s, "end_local": e,
                                "rate_per_kwh": rate})

    out = {
        "plant": pd.DataFrame(plants), "meter": pd.DataFrame(meters), "machine": pd.DataFrame(machines),
        "meter_machine_map": pd.DataFrame(maps), "shift": pd.DataFrame(shifts),
        "shift_instance": pd.DataFrame(instances).sort_values(["plant_id", "start_utc"]).reset_index(drop=True),
        "tariff": pd.DataFrame(tariffs), "tariff_window": pd.DataFrame(windows),
    }
    out["shift_instance"]["start_min"] = out["shift_instance"]["start_utc"].map(to_min)
    out["shift_instance"]["end_min"] = out["shift_instance"]["end_utc"].map(to_min)
    return out, swap
