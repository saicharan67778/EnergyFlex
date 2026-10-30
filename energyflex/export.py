"""Deterministic export: CSV + JSON + SQL (DDL + seed) + ground truth + manifest with SHA-256 checksums."""
import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd

from . import schema
from .timeutil import iso

SQL_TYPES = {"string": "VARCHAR(160)", "integer": "INTEGER", "decimal": "NUMERIC(16,3)", "boolean": "BOOLEAN",
             "date": "DATE", "time": "VARCHAR(5)", "datetime": "TIMESTAMPTZ"}
# FK-safe creation / insert order
ORDER = ["plant", "meter", "machine", "meter_machine_map", "shift", "shift_instance", "tariff", "tariff_window",
         "weather_observation", "production_batch", "batch_status_event", "maintenance_event",
         "maintenance_status_event", "machine_status_event", "meter_status_event", "machine_state_interval",
         "energy_reading", "finding", "recommendation"]


def format_table(df, table):
    """Typed frame -> export frame (ISO strings for time, lower-case booleans), columns in dictionary order."""
    spec = schema.BY_NAME[table] if isinstance(table, str) else None
    fields = spec.fields if spec else table
    out = pd.DataFrame(index=df.index)
    for f in fields:
        s = df[f.name]
        if f.type == "datetime":
            out[f.name] = iso(s) if not s.isna().all() else pd.Series([None] * len(s), index=s.index, dtype=object)
        elif f.type == "date":
            out[f.name] = s.map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v)
                                else pd.Timestamp(v).strftime("%Y-%m-%d"))
        elif f.type == "boolean":
            out[f.name] = s.map(lambda v: "true" if bool(v) else "false")
        elif f.type == "integer":
            out[f.name] = s.astype("Int64")
        else:
            out[f.name] = s.where(s.notna(), None) if s.dtype == object else s
    return out.reset_index(drop=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sql_literal(v, typ):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
        return "NULL"
    if typ == "boolean":
        return "TRUE" if v == "true" else "FALSE"
    if typ in ("integer", "decimal"):
        return repr(float(v)) if typ == "decimal" else str(int(v))
    return "'" + str(v).replace("'", "''") + "'"


def ddl(tables):
    lines = ["-- Generated from energyflex/schema.py. Portable across PostgreSQL and SQLite.", ""]
    for name in [t for t in ORDER if t in tables]:
        t = schema.BY_NAME[name]
        cols = []
        for f in t.fields:
            c = f"  {f.name} {SQL_TYPES[f.type]}"
            if f.name == t.pk:
                c += " PRIMARY KEY"
            elif f.required:
                c += " NOT NULL"
            if f.unique and f.name != t.pk:
                c += " UNIQUE"
            cols.append(c)
        for f in t.fields:
            if f.fk:
                rt, rc = f.fk.split(".")
                cols.append(f"  FOREIGN KEY ({f.name}) REFERENCES {rt}({rc})")
        lines.append(f"CREATE TABLE {name} (\n" + ",\n".join(cols) + "\n);")
        if name == "energy_reading":
            lines.append("CREATE INDEX ix_energy_reading_natural ON energy_reading(reading_id);")
            lines.append("CREATE INDEX ix_energy_reading_meter_ts ON energy_reading(meter_id, ts_utc);")
        lines.append("")
    return "\n".join(lines)


def seed_sql(frames, chunk=500):
    out = []
    for name in [t for t in ORDER if t in frames]:
        t = schema.BY_NAME[name]
        df = frames[name]
        cols = [f.name for f in t.fields]
        types = [f.type for f in t.fields]
        rows = df[cols].to_numpy(dtype=object)
        for i in range(0, len(rows), chunk):
            vals = ",\n".join("(" + ", ".join(_sql_literal(v, ty) for v, ty in zip(r, types)) + ")"
                              for r in rows[i:i + chunk])
            out.append(f"INSERT INTO {name} ({', '.join(cols)}) VALUES\n{vals};")
    return "\n".join(out) + "\n"


def write_dataset(tables, gt, meta, root, formats=("csv", "json", "sql")):
    root = Path(root)
    frames = {name: format_table(df, name) for name, df in tables.items()}
    files = []

    def record(path, rows=None):
        files.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                      "sha256": sha256(path), "rows": rows})

    for name in [t for t in ORDER if t in frames]:
        df = frames[name]
        if "csv" in formats:
            p = root / "csv" / f"{name}.csv"
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(p, index=False, lineterminator="\n")
            record(p, len(df))
        if "json" in formats:
            p = root / "json" / f"{name}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(df.to_json(orient="records", indent=None, double_precision=6), encoding="utf-8")
            record(p, len(df))
    if "sql" in formats:
        p = root / "sql" / "schema.sql"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ddl(frames), encoding="utf-8")
        record(p)
        p = root / "sql" / "seed.sql"
        p.write_text(seed_sql(frames), encoding="utf-8")
        record(p)

    gtf = format_table(gt, schema.GROUND_TRUTH_FIELDS)
    gdir = root / "ground_truth"
    gdir.mkdir(parents=True, exist_ok=True)
    gtf.to_csv(gdir / "ground_truth.csv", index=False, lineterminator="\n")
    record(gdir / "ground_truth.csv", len(gtf))
    (gdir / "ground_truth.json").write_text(gtf.to_json(orient="records", indent=1, double_precision=6),
                                            encoding="utf-8")
    record(gdir / "ground_truth.json", len(gtf))

    manifest = {
        "dataset": f"energyflex-{meta['scale']}", "scale": meta["scale"], "seed": meta["seed"],
        "generator_command": f"python cli.py generate --scale {meta['scale']} --seed {meta['seed']}",
        "window_utc": [meta["start_utc"], meta["end_utc"]],
        "provenance": "100% synthetic; no external data retrieved. See docs/PROVENANCE.md.",
        "environment": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__},
        "row_counts": {name: len(df) for name, df in frames.items()} | {"ground_truth": len(gtf)},
        "files": sorted(files, key=lambda f: f["path"]),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
