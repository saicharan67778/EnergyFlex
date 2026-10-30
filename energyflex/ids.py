"""Deterministic, immutable ID builders and the regex each one must satisfy.

IDs are derived from natural keys or from zero-padded counters assigned after a deterministic sort,
so the same seed always yields the same IDs and references stay consistent across every export.
"""
import re

from .config import ID_YEAR

Y = ID_YEAR


def plant(n): return f"PLT{n:02d}"
def meter(plant_id, n): return f"MTR-{plant_id}-{n:03d}"
def machine(plant_id, n): return f"MCH-{plant_id}-{n:03d}"
def shift(plant_id, code): return f"SHF-{plant_id}-{code}"
def shift_instance(plant_id, date, code): return f"SHI-{plant_id}-{date:%Y%m%d}-{code}"
def tariff(n): return f"TAR-{Y}-{n:03d}"
def tariff_window(tariff_id, n): return f"{tariff_id}-W{n:02d}"
def reading(meter_id, ts): return f"ENG-{meter_id}-{ts:%Y%m%dT%H%M}Z"
def weather(plant_id, ts): return f"WTH-{plant_id}-{ts:%Y%m%dT%H}Z"
def batch(n): return f"BATCH-{Y}-{n:06d}"
def batch_event(n): return f"BEV-{Y}-{n:07d}"
def maintenance(n): return f"MNT-{Y}-{n:06d}"
def maintenance_event(n): return f"MSE-{Y}-{n:06d}"
def machine_event(n): return f"MCE-{Y}-{n:06d}"
def meter_event(n): return f"MTE-{Y}-{n:06d}"
def state_interval(n): return f"MSI-{Y}-{n:07d}"
def mapping(n): return f"MMAP-{n:04d}"
def ground_truth(n): return f"GT-{Y}-{n:05d}"
def finding(n): return f"FND-{Y}-{n:06d}"
def recommendation(n): return f"REC-{Y}-{n:06d}"
def recommendation_event(n): return f"REV-{Y}-{n:06d}"


PATTERNS = {
    "plant_id": r"PLT\d{2}",
    "meter_id": r"MTR-PLT\d{2}-\d{3}",
    "machine_id": r"MCH-PLT\d{2}-\d{3}",
    "shift_id": r"SHF-PLT\d{2}-[ABC]",
    "shift_instance_id": r"SHI-PLT\d{2}-\d{8}-[ABC]",
    "tariff_id": rf"TAR-{Y}-\d{{3}}",
    "window_id": rf"TAR-{Y}-\d{{3}}-W\d{{2}}",
    "reading_id": r"ENG-MTR-PLT\d{2}-\d{3}-\d{8}T\d{4}Z",
    "observation_id": r"WTH-PLT\d{2}-\d{8}T\d{2}Z",
    "batch_id": rf"BATCH-{Y}-\d{{6}}",
    "batch_event_id": rf"BEV-{Y}-\d{{7}}",
    "maintenance_id": rf"MNT-{Y}-\d{{6}}",
    "maintenance_event_id": rf"MSE-{Y}-\d{{6}}",
    "machine_event_id": rf"MCE-{Y}-\d{{6}}",
    "meter_event_id": rf"MTE-{Y}-\d{{6}}",
    "state_interval_id": rf"MSI-{Y}-\d{{7}}",
    "map_id": r"MMAP-\d{4}",
    "gt_id": rf"GT-{Y}-\d{{5}}",
    "finding_id": rf"FND-{Y}-\d{{6}}",
    "rec_id": rf"REC-{Y}-\d{{6}}",
    "rec_event_id": rf"REV-{Y}-\d{{6}}",
}

COMPILED = {k: re.compile(rf"^{v}$") for k, v in PATTERNS.items()}
