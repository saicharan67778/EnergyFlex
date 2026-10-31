# EnergyFlex — energy waste & peak demand correlation

**Live dashboard:** https://energyflex.vercel.app · **Repository:** https://github.com/saicharan67778/EnergyFlex

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
- `docs/DATA_DICTIONARY.md` — every table and column, generated from `energyflex/schema.py`
- `docs/ERD.md` — entity-relationship diagram (Mermaid)
- `docs/RULES.md` — generation, labelling and detection rules with their thresholds
- `docs/PROVENANCE.md` — data sources (none external) and lawful-use notes
- `site/` — static dashboard (`index.html`, `styles.css`, `app.js`, `data/dashboard.json`), deployed on Vercel

## How the data is generated
Everything comes from `python cli.py generate --scale full --seed 20261022`. Nothing is downloaded.
1. **Configuration** (`energyflex/config.py`): plants (Pune, Houston, Chennai, Stuttgart, each with its own timezone and currency), machine types
   with nameplate kW and idle/standby fractions, shift templates, synthetic time-of-use tariffs, climate parameters, fixed FX.
2. **Modules run in order**, each with its own seeded random stream, so changing one module never reshuffles another:
   `master` (plants, meters, machines, hierarchy, shifts, tariffs) → `weather` (hourly: seasonal + diurnal + AR(1) anomaly) →
   `maintenance` (Sunday work orders, drift plan) → `production` (batches inside shifts, full lifecycle history) →
   `telemetry` (minute-level machine states → kW → 15-min meter energy) → `anomalies` (raw meter records + data errors).
3. **Labelled problems.** Waste scenarios (idle, peak spikes, intensity drift, air leak, HVAC override) and data errors are injected
   on purpose. Each one writes a row to `ground_truth.csv` with its window and kWh impact. The analytics never read that file;
   it's used only to score detection.
4. **Reproducible.** Same seed → byte-identical files; `python cli.py repro-check` regenerates twice and compares SHA-256 checksums.

## Dashboard
Dark theme by default (◐ Theme switches to light). The sidebar has one view per role:
- **Overview** — KPI ring tiles (energy, cost, savings, detection F1, validation), findings by issue type, stacked daily energy,
  plant comparison, top recommendations, detection quality, acceptance criteria, summary strip
- **Plant operator** — load profile by local hour, idle energy above standby, idle episodes
- **Maintenance / quality** — kWh/unit vs baseline with maintenance markers, off-shift utilities vs weather-normalised expectation
- **Production planner** — daily energy by tariff period, monthly bills, peak demand spikes
- **OT / IT admin** — data-quality exceptions, detection vs ground truth, validation checks, per-meter energy balance
- **Recommendations** — every action with baseline, savings formula and evidence, filterable by owner and plant

Rebuild the data with `python cli.py all --scale full` (writes `site/data/dashboard.json`). To deploy: `cd site && npx vercel deploy --prod`.

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
