"""Synthetic data generator entry point. Order: masters -> weather -> maintenance -> batches -> telemetry -> anomalies."""
import json

import numpy as np
import pandas as pd

from .. import config, ids
from ..timeutil import START, from_min, mins_to_ts
from . import anomalies, maintenance, master, production, telemetry, weather

# Named sub-streams: adding a plant or changing one module's draws never reshuffles another module.
STREAMS = {"master": 1, "weather": 2, "maintenance": 3, "production": 4, "telemetry": 5, "anomalies": 6}


def generate(scale_name="starter", seed=config.SEED):
    scale = config.SCALES[scale_name]
    days = scale["days"]

    def rng_for(name, sub=0):
        return np.random.default_rng([seed, STREAMS[name], sub])

    masters, swap = master.build(scale, rng_for("master"))
    wx = weather.build(masters["plant"], days, rng_for)
    drifts = maintenance.plan_drifts(masters, days)
    maint, maint_ev, machine_ev = maintenance.build(masters, drifts, days, rng_for("maintenance"))
    batches, batch_ev = production.build(masters, scale["n_batches"], rng_for("production"))
    meter_kwh, states, scen_gt, _ = telemetry.build(masters, batches, maint, drifts, swap, wx, days, rng_for)
    readings, edge_gt, meter_ev = anomalies.build(masters, meter_kwh, scen_gt, swap, days, rng_for("anomalies"))

    # minutes -> timestamps for export; generator-internal columns are dropped
    for c in ("planned_start", "planned_end", "actual_start", "actual_end"):
        batches[f"{c}_utc"] = [from_min(v) if pd.notna(v) else pd.NaT for v in batches[f"{c}_min"]]
    batches = batches[["batch_id", "plant_id", "machine_id", "shift_instance_id", "product_code", "unit_of_measure",
                       "planned_start_utc", "planned_end_utc", "actual_start_utc", "actual_end_utc",
                       "planned_units", "produced_units", "good_units", "scrap_units", "status"]]
    states["start_utc"] = mins_to_ts(states["start_min"]).values
    states["end_utc"] = mins_to_ts(states["end_min"]).values
    states = states[["state_interval_id", "machine_id", "state", "start_utc", "end_utc", "duration_min", "source"]]

    gt = pd.DataFrame(scen_gt + edge_gt)
    gt["window_start_utc"] = mins_to_ts(gt["start_min"]).values
    gt["window_end_utc"] = mins_to_ts(gt["end_min"]).values
    gt = gt.sort_values(["window_start_utc", "issue_type", "entity_id"], kind="stable").reset_index(drop=True)
    gt.insert(0, "gt_id", [ids.ground_truth(i + 1) for i in range(len(gt))])
    gt["params"] = [json.dumps(p, sort_keys=True) for p in gt["params"]]
    gt = gt[["gt_id", "issue_type", "category", "plant_id", "entity_type", "entity_id", "window_start_utc",
             "window_end_utc", "impact_kwh", "params", "expected_detection", "expected_decision"]]

    tables = dict(masters)
    tables["shift_instance"] = tables["shift_instance"].drop(columns=["start_min", "end_min"])
    tables.update({
        "weather_observation": wx, "production_batch": batches, "batch_status_event": batch_ev,
        "maintenance_event": maint, "maintenance_status_event": maint_ev, "machine_status_event": machine_ev,
        "meter_status_event": meter_ev, "machine_state_interval": states, "energy_reading": readings,
    })
    meta = {"scale": scale_name, "seed": seed, "days": days, "start_utc": config.START_UTC,
            "end_utc": str((START + pd.Timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")),
            "swap": {k: str(v) for k, v in (swap or {}).items()}}
    return tables, gt, meta
