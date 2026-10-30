# EnergyFlex — energy waste & peak demand correlation

Correlates machine telemetry, production batches, time-of-use tariffs and weather across 4 plants / 20 meters /
90 days of 15-minute readings / 2,000 batches to find energy waste and peak demand. The data is 100% synthetic and
generated with a fixed seed.

## Run it
```bash
pip install -r requirements.txt
python cli.py all --scale starter      # 2 plants, 7 days: generate, validate, repro-check, analyze
python cli.py all --scale full         # 20 meters, 90 days, 2,000 batches (+ builds site/data)
python -m pytest -q                    # 25 tests
python -m http.server -d site 8000     # dashboard
```
Seed: `20261022` (`--seed N` to change). Generator command and checksums: `data/<scale>/manifest.json`.

## Layout
- `energyflex/generate/` — masters → shift calendar → tariffs → weather → maintenance → batches → machine states → meters, then labelled edge cases (`anomalies.py`)
- `energyflex/validate.py` — 283 checks; every failure must match a ground-truth label (FAIL = unexplained)
- `energyflex/analytics/` — quality gate, reconciliation, tariff costing, intensity, waste, recommendations, evaluation
- `data/<scale>/` — `csv/`, `json/`, `sql/schema.sql` + `seed.sql`, `ground_truth/` (kept separate), `manifest.json`, `validation_summary.md`, `repro_report.json`
- `outputs/<scale>/` — findings, recommendations, monthly bills, batch intensity, energy balance, evaluation, `metrics.json`
- `docs/DATA_DICTIONARY.md` — generated from `energyflex/schema.py`
- `site/` — static dashboard (Vercel)

## Results (full scale)
- Acceptance: energy totals reconcile (20/20 meters, 0.0 % diff), 100 % of intervals priced by exactly one plant-local DST-aware window, kWh/unit for 1,934 completed batches, 25 recommendations, each with a baseline, savings formula and evidence
- Detection vs ground truth: macro-F1 0.98, micro recall 0.994, micro precision 0.998
- Reproducibility: 38 files are byte-identical when the data is regenerated with the same seed

## Edge cases (labelled in `ground_truth.csv`)
Register ≠ interval sum (jump/drift), Σ sub-meters > incomer (CT ratio), kW written as kWh, tariff timezone mismatch,
duplicate readings (exact/conflicting), machine tag outside the meter hierarchy, meter gaps; scenarios: idle,
peak spikes, intensity drift, compressed-air leak, HVAC weekend override.

## Provenance
No external data. Climate and tariff parameters are hand-set approximations labelled "synthetic". FX rates in `config.py` are fixed assumptions.
