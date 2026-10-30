"""Machine state timeline (minute resolution) -> machine kW -> 15-minute meter energy.

Normal behaviour is generated first; labelled behavioural scenarios (excess idle, overnight idle,
peak spikes, intensity drift, compressed-air leak, HVAC schedule override) are then applied on a copy so
ground truth can be computed exactly as the difference. Data-error edge cases are injected later
(see anomalies.py) on the meter records only.
"""
import numpy as np
import pandas as pd

from .. import config, ids, tariffs as tariff_lookup
from ..timeutil import START, local_to_utc, to_min

OFF, STANDBY, IDLE, RUNNING, MAINT, OOS = range(6)
STATE_NAMES = ["OFF", "STANDBY", "IDLE", "RUNNING", "MAINTENANCE", "OUT_OF_SERVICE"]
IDLE_LABEL_MIN = 75       # scenario idle runs at least this long are labelled HIGH_IDLE_CONSUMPTION (= R-IDLE-01)
IDLE_LABEL_SCEN_MIN = 30  # ... and must contain at least this many scenario-induced minutes
WARMUP_MAX_MIN = 60       # warm-up idle at shift start lapses to standby after this


def _runs(mask):
    """Start/end (exclusive) indices of True runs."""
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return np.flatnonzero(d == 1), np.flatnonzero(d == -1)


def _machine_states(n_min, in_service, shifts, maint_windows, rng):
    """shifts: list of (s, e, runs[(a, b, lf)]) for staffed shifts, sorted by start."""
    normal = np.full(n_min, OFF, dtype=np.int8)
    for s, e, runs in shifts:
        normal[s:e] = STANDBY
        if not runs:
            normal[s:min(s + 30, e)] = IDLE
            continue
        first = runs[0][0]
        normal[s:min(s + WARMUP_MAX_MIN, first)] = IDLE          # warm-up for the first batch
        normal[max(s, first - config.PREHEAT_IDLE_MIN):first] = IDLE  # pre-heat if the warm-up lapsed to standby
        for (a, b, _), nxt in zip(runs, runs[1:] + [None]):
            normal[a:b] = RUNNING
            if nxt is None:
                normal[b:min(b + config.COOLDOWN_IDLE_MIN, e)] = IDLE
            elif nxt[0] - b <= config.CHANGEOVER_MAX_MIN:
                normal[b:nxt[0]] = IDLE
            else:
                normal[b:b + config.COOLDOWN_IDLE_MIN] = IDLE
                normal[nxt[0] - config.PREHEAT_IDLE_MIN:nxt[0]] = IDLE

    scen = normal.copy()
    sc = config.SCENARIO
    for i, (s, e, runs) in enumerate(shifts):
        if rng.random() < sc["excess_idle_shift_prob"]:
            seg = scen[s:e]
            seg[seg == STANDBY] = IDLE
        if rng.random() < sc["overnight_idle_prob"]:
            nxt = shifts[i + 1][0] if i + 1 < len(shifts) else n_min
            stop = min(nxt, e + int(rng.integers(240, 541)), n_min)
            if scen[e - 1] in (IDLE, STANDBY):
                scen[e - 1] = IDLE
            seg = scen[e:stop]
            seg[seg == OFF] = IDLE
    for a, b in maint_windows:
        normal[a:b] = MAINT
        scen[a:b] = MAINT
    normal[~in_service] = OOS
    scen[~in_service] = OOS
    return normal, scen


def _power(state, m, lf, drift, inrush, rng, eff):
    t = config.MACHINE_TYPES[m.machine_type]
    kw = np.zeros(len(state))
    kw[state == OFF] = m.rated_kw * t["off_frac"]
    kw[state == STANDBY] = m.standby_kw
    idle = state == IDLE
    kw[idle] = m.idle_kw * (1 + rng.normal(0, 0.02, idle.sum()))
    run = state == RUNNING
    kw[run] = m.rated_kw * lf[run] * drift[run] * eff * inrush[run] * (1 + rng.normal(0, 0.04, run.sum()))
    return kw


def build(masters, batches, maint, drifts, swap, weather, days, rng_for):
    n_min, n_int = days * 1440, days * 96
    ts_int = START + pd.to_timedelta(np.arange(n_int) * 15, unit="min")
    mach, inst = masters["machine"], masters["shift_instance"]
    maps = masters["meter_machine_map"]
    gt, state_rows, meter_kwh, machine_kw15 = [], [], {}, {}
    plant_ctx = {}

    for p_idx, pc in enumerate(config.PLANTS[: len(masters["plant"])]):
        pid, tz = pc["plant_id"], pc["timezone"]
        rng = rng_for("telemetry", p_idx)
        pm = mach[mach["plant_id"] == pid]
        working = inst[(inst["plant_id"] == pid) & (inst["calendar_status"] == "WORKING")]
        occ_min = np.zeros(n_min, dtype=bool)
        for r in working.itertuples():
            occ_min[r.start_min:r.end_min] = True
        occupied = occ_min.reshape(n_int, 15).any(axis=1)
        running_frac = []

        # ---------------- production machines ----------------
        for m in pm[pm["is_production"]].itertuples():
            in_service = np.ones(n_min, dtype=bool)
            if m.commissioned_at > START:
                in_service[: to_min(m.commissioned_at)] = False
            if pd.notna(m.decommissioned_at):
                in_service[max(0, to_min(m.decommissioned_at)):] = False
            mb = batches[batches["machine_id"] == m.machine_id]
            shifts = []
            for siid, g in mb.groupby("shift_instance_id", sort=False):
                si = working[working["shift_instance_id"] == siid].iloc[0]
                ok = g[g["status"] != "CANCELLED"].sort_values("actual_start_min")
                runs = [(int(r.actual_start_min), int(r.actual_end_min), r.load_factor) for r in ok.itertuples()]
                shifts.append((int(si.start_min), int(si.end_min), runs))
            shifts.sort(key=lambda x: x[0])
            mw = maint[maint["machine_id"] == m.machine_id]
            mwin = [(max(0, to_min(r.started_at)), min(n_min, to_min(r.closed_at))) for r in mw.itertuples()]
            normal, scen = _machine_states(n_min, in_service, shifts, mwin, rng)

            lf = np.zeros(n_min)
            inrush = np.ones(n_min)
            for _, _, runs in shifts:
                for a, b, f in runs:
                    lf[a:b] = f
                    inrush[a:a + config.INRUSH_MIN] = config.INRUSH_FACTOR
            drift = np.ones(n_min)
            for d in (d for d in drifts if d["machine_id"] == m.machine_id):
                stop = to_min(d["fix_ts"]) if d["fix_ts"] is not None else n_min
                ramp = np.clip((np.arange(n_min) - d["start_min"]) / max(1, d["ramp_end_min"] - d["start_min"]), 0, 1)
                seg = slice(d["start_min"], stop)
                drift[seg] = 1 + (d["max_mult"] - 1) * ramp[seg]
            eff = swap["efficiency"] if swap and m.machine_id == swap["new"] else 1.0
            kw = _power(scen, m, lf, drift, inrush, rng, eff)
            kw_normal = _power(normal, m, lf, np.ones(n_min), inrush, np.random.default_rng(0), eff)

            # ground truth: excess idle runs
            diff = (scen == IDLE) & (normal != IDLE)
            for a, b in zip(*_runs(scen == IDLE)):
                n_scen = int(diff[a:b].sum())
                if b - a >= IDLE_LABEL_MIN and n_scen >= IDLE_LABEL_SCEN_MIN:
                    extra = float((kw[a:b] - kw_normal[a:b])[diff[a:b]].sum() / 60)
                    gt.append({"issue_type": "HIGH_IDLE_CONSUMPTION", "category": "WASTE_SCENARIO", "plant_id": pid,
                               "entity_type": "machine", "entity_id": m.machine_id, "start_min": a, "end_min": b,
                               "impact_kwh": round(extra, 2),
                               "params": {"idle_minutes": int(b - a), "scenario_minutes": n_scen,
                                          "variant": "OVERNIGHT" if not occ_min[min(b - 1, n_min - 1)] else "NO_STANDBY"},
                               "expected_detection": "R-IDLE-01", "expected_decision": "RECOMMEND_AUTO_STANDBY"})
            for d in (d for d in drifts if d["machine_id"] == m.machine_id):
                stop = to_min(d["fix_ts"]) if d["fix_ts"] is not None else n_min
                run = scen[d["start_min"]:stop] == RUNNING
                extra = kw[d["start_min"]:stop][run] * (1 - 1 / drift[d["start_min"]:stop][run])
                gt.append({"issue_type": "INTENSITY_DRIFT", "category": "WASTE_SCENARIO", "plant_id": pid,
                           "entity_type": "machine", "entity_id": m.machine_id, "start_min": d["start_min"],
                           "end_min": stop, "impact_kwh": round(float(extra.sum() / 60), 2),
                           "params": {"max_multiplier": d["max_mult"], "repaired": d["fix_ts"] is not None},
                           "expected_detection": "R-INT-01",
                           "expected_decision": "RAISE_CORRECTIVE_MAINTENANCE"})

            # state history (append-only intervals, run-length encoded)
            change = np.flatnonzero(np.diff(scen)) + 1
            starts = np.concatenate([[0], change])
            ends = np.concatenate([change, [n_min]])
            for a, b in zip(starts, ends):
                state_rows.append((m.machine_id, STATE_NAMES[scen[a]], int(a), int(b)))

            machine_kw15[m.machine_id] = kw.reshape(n_int, 15).mean(axis=1)
            if in_service.any():
                running_frac.append((scen == RUNNING).reshape(n_int, 15).mean(axis=1))

        prod_frac = np.mean(running_frac, axis=0)

        # ---------------- peak demand spikes (coincident heat-up in tariff PEAK window) ----------------
        ptar = masters["tariff"][masters["tariff"]["plant_id"] == pid]
        period = tariff_lookup.lookup(ts_int, ptar, masters["tariff_window"], tz)["period"].to_numpy()
        n_spk = max(1, round(config.SCENARIO["spikes_per_plant_per_30d"] * days / 30))
        prod_ids = [m for m in pm[pm["is_production"]]["machine_id"] if m in machine_kw15]
        used = []
        for _ in range(n_spk):
            mid = prod_ids[int(rng.integers(0, len(prod_ids)))]
            mrow = pm[pm["machine_id"] == mid].iloc[0]
            k15 = machine_kw15[mid]
            cand = np.flatnonzero((period == "PEAK") & (k15 > 0.55 * mrow.rated_kw) &
                                  (np.arange(n_int) > config.baseline_days(days) * 96 // 2))
            cand = [c for c in cand if all(abs(c - u) > 96 for u in used) and c + 2 < n_int]
            if not cand:
                continue
            c = int(cand[int(rng.integers(0, len(cand)))])
            length = int(rng.integers(1, 3))
            before = k15[c:c + length].copy()
            k15[c:c + length] = mrow.rated_kw * rng.uniform(1.35, 1.60, length)
            used.append(c)
            gt.append({"issue_type": "PEAK_DEMAND_SPIKE", "category": "WASTE_SCENARIO", "plant_id": pid,
                       "entity_type": "meter", "entity_id": None, "machine_id": mid, "start_min": c * 15,
                       "end_min": (c + length) * 15,
                       "impact_kwh": round(float((k15[c:c + length] - before).sum() * 0.25), 2),
                       "params": {"peak_kw": round(float(k15[c:c + length].max()), 1),
                                  "rated_kw": float(mrow.rated_kw), "intervals": length},
                       "expected_detection": "R-PEAK-01", "expected_decision": "RECOMMEND_STAGGERED_START"})

        # ---------------- utilities: compressor + HVAC (weather driven) ----------------
        wx = weather[weather["plant_id"] == pid]["temp_c"].to_numpy()
        temp = np.repeat(wx, 4)[:n_int]
        comp = pm[pm["machine_type"] == "AIR_COMPRESSOR"].iloc[0]
        hvac = pm[pm["machine_type"] == "HVAC_AHU"].iloc[0]
        comp_load = np.where(occupied, 0.22 + 0.55 * prod_frac, 0.12)
        leak_plant = 2 if len(masters["plant"]) >= 3 else 1
        if p_idx == leak_plant:
            leak_start = round(config.SCENARIO["leak_frac_start"] * days) * 96 + 8  # 02:00 UTC on that day
            leak = np.zeros(n_int)
            leak[leak_start:] = 0.16
            comp_load = comp_load + leak
            gt.append({"issue_type": "OFF_SHIFT_WASTE", "category": "WASTE_SCENARIO", "plant_id": pid,
                       "entity_type": "meter", "entity_id": ids.meter(pid, 5), "start_min": leak_start * 15,
                       "end_min": n_min, "impact_kwh": round(float(leak.sum() * comp.rated_kw * 0.25), 2),
                       "params": {"variant": "COMPRESSED_AIR_LEAK", "added_kw": round(0.16 * comp.rated_kw, 1)},
                       "expected_detection": "R-OFF-01", "expected_decision": "RECOMMEND_LEAK_SURVEY"})
        comp_kw = comp.rated_kw * comp_load * (1 + rng.normal(0, 0.03, n_int))

        occ_load = np.clip(0.12 + 0.055 * np.maximum(temp - 23, 0) + 0.045 * np.maximum(19 - temp, 0), 0, 1)
        unocc_load = np.clip(0.03 + 0.012 * np.maximum(temp - 28, 0) + 0.012 * np.maximum(10 - temp, 0), 0, 0.3)
        hvac_occ = occupied.copy()
        if p_idx == 0:
            # HVAC schedule override: BMS left in occupied mode for one full weekend after the baseline window
            sats = [d for d in range(5, days - 1, 7) if d >= config.baseline_days(days)]
            sat = sats[int(rng.integers(0, len(sats)))] if len(sats) > 1 else sats[0]
            sat_date = (START + pd.Timedelta(days=sat, hours=12)).tz_convert(tz).date()
            ws = to_min(local_to_utc(sat_date, "00:00", tz)) // 15
            we = min(n_int, to_min(local_to_utc(sat_date + pd.Timedelta(days=2), "00:00", tz)) // 15)
            forced = np.zeros(n_int, dtype=bool)
            forced[ws:we] = ~occupied[ws:we]
            hvac_occ |= forced
            gt.append({"issue_type": "OFF_SHIFT_WASTE", "category": "WASTE_SCENARIO", "plant_id": pid,
                       "entity_type": "meter", "entity_id": ids.meter(pid, 5), "start_min": ws * 15,
                       "end_min": we * 15,
                       "impact_kwh": round(float(((occ_load - unocc_load) * forced).sum() * hvac.rated_kw * 0.25), 2),
                       "params": {"variant": "HVAC_SCHEDULE_OVERRIDE"},
                       "expected_detection": "R-OFF-01", "expected_decision": "RECOMMEND_BMS_SCHEDULE_LOCK"})
        hvac_kw = hvac.rated_kw * np.where(hvac_occ, occ_load, unocc_load) * (1 + rng.normal(0, 0.03, n_int))
        machine_kw15[comp.machine_id] = comp_kw
        machine_kw15[hvac.machine_id] = hvac_kw

        # ---------------- meters ----------------
        sub_true = {}
        for mtr_n in (2, 3, 4, 5):
            mtr = ids.meter(pid, mtr_n)
            total = np.zeros(n_int)
            for mp in maps[maps["meter_id"] == mtr].itertuples():
                total += machine_kw15[mp.machine_id] * mp.allocation_pct / 100.0
            sub_true[mtr] = total * 0.25
        lo, hi = pc["lighting_kw"]
        lighting = np.where(occupied, lo, hi) * (1 + rng.normal(0, 0.03, n_int))
        main_true = sum(sub_true.values()) * (1 + config.UNMETERED_LOSS_FRAC) + lighting * 0.25
        meter_kwh[ids.meter(pid, 1)] = main_true * (1 + rng.normal(0, 0.002, n_int))
        for mtr, v in sub_true.items():
            meter_kwh[mtr] = v * (1 + rng.normal(0, 0.002, n_int))
        plant_ctx[pid] = {"occupied": occupied, "period": period}

    # spike GT rows point at the machine's meter at that time
    mp = maps.copy()
    for g in gt:
        if g["issue_type"] == "PEAK_DEMAND_SPIKE":
            g["entity_id"] = mp[mp["machine_id"] == g.pop("machine_id")]["meter_id"].iloc[0]

    states = pd.DataFrame(state_rows, columns=["machine_id", "state", "start_min", "end_min"])
    states = states.sort_values(["start_min", "machine_id"], kind="stable").reset_index(drop=True)
    states.insert(0, "state_interval_id", [ids.state_interval(i + 1) for i in range(len(states))])
    states["duration_min"] = states["end_min"] - states["start_min"]
    states["source"] = "PLC"
    return meter_kwh, states, gt, plant_ctx
