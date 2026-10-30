"""Load an exported dataset back from CSV with dictionary types (the analytics and validator only read files)."""
from pathlib import Path

import pandas as pd

from . import schema


def _typed(df, fields):
    for f in fields:
        if f.name not in df:
            continue
        s = df[f.name]
        if f.type == "datetime":
            df[f.name] = pd.to_datetime(s, utc=True, format="%Y-%m-%dT%H:%M:%SZ")
        elif f.type == "date":
            df[f.name] = pd.to_datetime(s, format="%Y-%m-%d").dt.date.where(s.notna(), None)
        elif f.type == "boolean":
            df[f.name] = s.astype(str).str.lower().eq("true")
        elif f.type == "integer":
            df[f.name] = pd.to_numeric(s).astype("Int64")
        elif f.type == "string" or f.type == "time":
            df[f.name] = s.astype(object).where(s.notna(), None)
    return df


def load_table(root, name):
    t = schema.BY_NAME[name]
    df = pd.read_csv(Path(root) / "csv" / f"{name}.csv", dtype=str, keep_default_na=False, na_values=[""])
    for f in t.fields:
        if f.type == "decimal":
            df[f.name] = pd.to_numeric(df[f.name])
    return _typed(df, t.fields)


def load_dataset(root):
    root = Path(root)
    return {name: load_table(root, name) for name in schema.GENERATED if (root / "csv" / f"{name}.csv").exists()}


def load_ground_truth(root):
    df = pd.read_csv(Path(root) / "ground_truth" / "ground_truth.csv", dtype=str, keep_default_na=False,
                     na_values=[""])
    df["impact_kwh"] = pd.to_numeric(df["impact_kwh"])
    return _typed(df, schema.GROUND_TRUTH_FIELDS)
