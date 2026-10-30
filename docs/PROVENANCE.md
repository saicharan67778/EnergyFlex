# Provenance and lawful use

- **No external data was retrieved, copied or redistributed.** `energyflex/generate` produces every record from the
  fixed seed `20261022` (`python cli.py generate --scale full --seed 20261022`).
- **Climate parameters** (`config.PLANTS[*].climate`): hand-set seasonal means and diurnal ranges that only
  approximate general climate; they don't come from any dataset.
- **Tariffs**: synthetic TOU structures, labelled "(synthetic)". The window shapes follow the general pattern of
  public industrial TOU tariffs (peak / normal / off-peak plus a monthly demand charge), but no published tariff's
  numbers are copied.
- **Equipment**: nameplate kW and idle/standby fractions are plausible engineering assumptions.
- **FX** (`config.FX_TO_USD`): fixed assumptions, used only to roll savings up into USD.
- **Personal data**: none. People appear only as roles (operator, planner, …).
- **Reproducibility**: `data/<scale>/manifest.json` lists the SHA-256 checksums, row counts and library versions;
  `python cli.py repro-check --scale full` regenerates the data twice and compares the checksums.
