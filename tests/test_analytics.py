"""Analytics: acceptance criteria, tariff correctness across DST/timezones, detection quality, no label leakage."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from energyflex import config, tariffs
from energyflex.generate import master


def _tables():
    m, _ = master.build(config.SCALES["full"], np.random.default_rng(0))
    return m


@pytest.mark.parametrize("utc, plant, period", [
    ("2026-03-06T19:00:00Z", "PLT02", "SHOULDER"),  # 13:00 CST (UTC-6) before DST
    ("2026-03-09T19:00:00Z", "PLT02", "PEAK"),      # 14:00 CDT (UTC-5) after DST began 2026-03-08
    ("2026-03-07T19:00:00Z", "PLT02", "OFFPEAK"),   # Saturday
    ("2026-01-05T12:30:00Z", "PLT01", "PEAK"),      # 18:00 IST
    ("2026-01-05T16:30:00Z", "PLT01", "OFFPEAK"),   # 22:00 IST
    ("2026-03-30T04:00:00Z", "PLT04", "PEAK"),      # 06:00 CEST after DST 2026-03-29
    ("2026-03-27T04:00:00Z", "PLT04", "OFFPEAK"),   # 05:00 CET before DST
])
def test_tariff_window_lookup_is_local_and_dst_aware(utc, plant, period):
    m = _tables()
    tz = m["plant"].set_index("plant_id").loc[plant, "timezone"]
    lk = tariffs.lookup(pd.Series([pd.Timestamp(utc)]), m["tariff"][m["tariff"]["plant_id"] == plant],
                        m["tariff_window"], tz)
    assert lk["period"].iloc[0] == period
    assert lk["match_count"].iloc[0] == 1


def test_tariff_version_switch_uses_effective_dates():
    m = _tables()
    pt = m["tariff"][m["tariff"]["plant_id"] == "PLT02"]
    lk = tariffs.lookup(pd.Series(pd.to_datetime(["2026-02-28T20:00:00Z", "2026-03-02T20:00:00Z"], utc=True)),
                        pt, m["tariff_window"], "America/Chicago")
    assert list(lk["tariff_id"]) == ["TAR-2026-002", "TAR-2026-003"]


def test_all_tariffs_cover_the_week_exactly_once():
    assert tariffs.coverage_issues(_tables()["tariff_window"]) == []


def test_acceptance_criteria(starter):
    acc = starter["res"]["acceptance"]
    assert all(v["pass"] for v in acc.values()), acc


def test_energy_totals_reconcile(starter):
    bal = pd.read_csv(starter["out"] / "energy_balance_meter.csv")
    assert bal["difference_pct"].abs().max() <= 0.1


def test_cost_equals_kwh_times_window_rate(starter):
    cr = starter["res"]["cr"]
    x = cr.dropna(subset=["rate"])
    assert (abs(x["cost"] - x["interval_kwh"] * x["rate"]) < 1e-9).all()
    bills = starter["res"]["bills"]
    main = cr[cr["meter_type"] == "MAIN"]
    assert abs(bills["energy_cost"].sum() - main["cost"].sum()) < 1.0


def test_intensity_normalised_by_output(starter):
    bi = starter["res"]["bi"]
    done = bi[bi["status"] == "COMPLETED"]
    assert (abs(done["kwh_per_unit"] - done["kwh"] / done["produced_units"]) < 1e-9).all()


def test_recommendations_cite_baseline_savings_and_evidence(starter):
    r = starter["res"]["recs"]
    assert len(r) > 0
    assert r["baseline_value"].notna().all() and r["savings_formula"].str.len().gt(10).all()
    assert ((r["expected_savings_cost_yr"] > 0) | (r["expected_savings_kw"] > 0)).all()
    ev = set(starter["res"]["findings"]["finding_id"])
    for e in r["evidence_ids"]:
        assert all(x in ev for x in e.split(";") if x)


def test_detection_quality(starter):
    pt = starter["res"]["per_type"]
    assert (pt["recall"] >= 0.9).all(), pt
    assert (pt["precision"] >= 0.8).all(), pt


def test_analytics_never_read_ground_truth():
    src = Path(__file__).resolve().parents[1] / "energyflex" / "analytics"
    for p in src.glob("*.py"):
        if p.name in ("pipeline.py", "evaluate.py"):
            continue
        assert "ground_truth" not in p.read_text(), p.name
