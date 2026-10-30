"""Render docs/DATA_DICTIONARY.md from energyflex/schema.py (the dictionary is never edited by hand)."""
from pathlib import Path

from . import ids, schema


def _row(f):
    allowed = ", ".join(f"`{a}`" for a in f.allowed) if f.allowed else ""
    rule = "; ".join(x for x in [f"pattern `{ids.PATTERNS[f.pattern]}`" if f.pattern else "",
                                 f"FK → `{f.fk}`" if f.fk else "", f.rule] if x)
    return (f"| `{f.name}` | {f.type} | {'yes' if f.required else 'no'} | {'yes' if f.unique else ''} | "
            f"{allowed} | {f.unit} | {rule} | {f.desc} |")


def render(path):
    out = ["# Data dictionary", "",
           "Generated from `energyflex/schema.py` by `python cli.py generate` — the same definitions drive the SQL DDL "
           "and the validator, so the three cannot drift apart.", "",
           "Conventions: every timestamp is UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`); local wall-clock values (shift and "
           "tariff windows) are `HH:MM` in the plant timezone; energy in kWh, demand in kW (15-minute average).", ""]
    for t in schema.TABLES:
        out += [f"## {t.entity} — `{t.name}`", "", f"{t.desc}", "",
                f"*Primary key:* `{t.pk}` · *Kind:* {t.kind}", "",
                "| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |",
                "|---|---|---|---|---|---|---|---|"] + [_row(f) for f in t.fields] + [""]
    out += ["## Ground truth — `ground_truth/ground_truth.csv`", "",
            "Kept outside `csv/`, never loaded by the analytics (only by `evaluate.py` after all findings exist).", "",
            "| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |",
            "|---|---|---|---|---|---|---|---|"] + [_row(f) for f in schema.GROUND_TRUTH_FIELDS] + [""]
    Path(path).write_text("\n".join(out), encoding="utf-8")
