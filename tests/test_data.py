"""Generated data: IDs, integrity, lifecycle, SQL loadability and reproducibility."""
import sqlite3

import pandas as pd

from energyflex import ids, io, schema, validate
from energyflex.export import write_dataset
from energyflex.generate import generate


def test_id_conventions():
    ts = pd.Timestamp("2026-01-05T00:15:00Z")
    assert ids.meter("PLT01", 1) == "MTR-PLT01-001"
    assert ids.reading("MTR-PLT01-001", ts) == "ENG-MTR-PLT01-001-20260105T0015Z"
    assert ids.batch(1) == "BATCH-2026-000001"
    assert ids.tariff(1) == "TAR-2026-001"
    assert ids.recommendation(1) == "REC-2026-000001"


def test_volumes_match_spec(starter):
    rc = starter["manifest"]["row_counts"]
    assert rc["production_batch"] == 150 and rc["meter"] == 10
    # 10 meters x 7 days x 96 intervals, minus gaps, plus duplicates
    assert 6500 < rc["energy_reading"] < 6800


def test_validation_has_no_unexplained_failures(starter):
    rows = validate.run(io.load_dataset(starter["data"]), io.load_ground_truth(starter["data"]))
    fails = [r for r in rows if r["status"] == "FAIL"]
    assert not fails, fails
    expected = {r["check"] for r in rows if r["status"] == "EXPECTED_FAIL"}
    # the labelled edge cases must actually show up in validation
    assert "energy_reading.reading_id.unique_natural_key" in expected
    assert "tariff.timezone=plant.timezone" in expected
    assert "energy_reading.machine_in_meter_hierarchy" in expected


def test_every_required_edge_case_is_labelled(starter):
    types = set(starter["gt"]["issue_type"])
    for t in ["REGISTER_INTERVAL_MISMATCH", "HIERARCHY_TOTAL_MISMATCH", "UNIT_KW_AS_KWH", "TARIFF_TZ_MISMATCH",
              "DUPLICATE_READING", "MACHINE_OUTSIDE_HIERARCHY", "METER_GAP", "PEAK_DEMAND_SPIKE",
              "HIGH_IDLE_CONSUMPTION", "INTENSITY_DRIFT", "OFF_SHIFT_WASTE"]:
        assert t in types, t


def test_derived_status_comes_from_events(starter):
    t = starter["tables"]
    last = t["batch_status_event"].sort_values("event_ts", kind="stable").groupby("batch_id")["to_status"].last()
    assert (t["production_batch"]["batch_id"].map(last) == t["production_batch"]["status"]).all()


def test_ground_truth_not_in_inputs(starter):
    csvs = {p.stem for p in (starter["data"] / "csv").glob("*.csv")}
    assert "ground_truth" not in csvs
    assert set(schema.GENERATED) - {"finding", "recommendation"} >= csvs - {"finding", "recommendation"}
    for name in csvs:
        cols = set(pd.read_csv(starter["data"] / "csv" / f"{name}.csv", nrows=1).columns)
        assert not cols & {"issue_type", "gt_id", "expected_decision", "label"}, name


def test_sql_seed_loads_with_foreign_keys(starter):
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript((starter["data"] / "sql" / "schema.sql").read_text())
    con.executescript((starter["data"] / "sql" / "seed.sql").read_text())
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    n = con.execute("SELECT COUNT(*) FROM energy_reading").fetchone()[0]
    assert n == starter["manifest"]["row_counts"]["energy_reading"]


def test_same_seed_same_bytes(starter, tmp_path):
    tables, gt, meta = generate("starter")
    m2 = write_dataset(tables, gt, meta, tmp_path)
    a = {f["path"]: f["sha256"] for f in starter["manifest"]["files"]}
    b = {f["path"]: f["sha256"] for f in m2["files"]}
    assert a == b


def test_different_seed_differs(tmp_path):
    t1, _, _ = generate("starter", seed=1)
    t2, _, _ = generate("starter", seed=2)
    assert not t1["energy_reading"]["interval_kwh"].equals(t2["energy_reading"]["interval_kwh"])
