# Data dictionary

Generated from `energyflex/schema.py` by `python cli.py generate` — the same definitions drive the SQL DDL and the validator, so the three cannot drift apart.

Conventions: every timestamp is UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`); local wall-clock values (shift and tariff windows) are `HH:MM` in the plant timezone; energy in kWh, demand in kW (15-minute average).

## Plant — `plant`

A manufacturing site; owns meters, machines, shifts and tariffs.

*Primary key:* `plant_id` · *Kind:* master

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `plant_id` | string | yes | yes |  |  | pattern `PLT\d{2}`; PLT + 2 digits | Plant identifier |
| `plant_name` | string | yes |  |  |  |  | Display name |
| `city` | string | yes |  |  |  |  | City |
| `country_code` | string | yes |  | `IN`, `US`, `DE` |  |  | ISO 3166-1 alpha-2 |
| `timezone` | string | yes |  |  |  |  | IANA timezone of plant wall clock; tariffs and shifts are defined in it |
| `currency` | string | yes |  | `INR`, `USD`, `EUR` |  |  | ISO 4217 billing currency |
| `latitude` | decimal | yes |  |  | deg | -90..90 | WGS84 latitude |
| `longitude` | decimal | yes |  |  | deg | -180..180 | WGS84 longitude |
| `status` | string | yes |  | `ACTIVE`, `INACTIVE` |  |  | Lifecycle state |

## Meter — `meter`

Energy meter. MAIN incomer is parent of SUB meters (self-referencing hierarchy).

*Primary key:* `meter_id` · *Kind:* master

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `meter_id` | string | yes | yes |  |  | pattern `MTR-PLT\d{2}-\d{3}` | MTR-<plant-id>-NNN |
| `plant_id` | string | yes |  |  |  | FK → `plant.plant_id` | Owning plant |
| `parent_meter_id` | string | no |  |  |  | FK → `meter.meter_id`; MAIN has null parent; SUB parent must be the MAIN of the same plant | Upstream meter (null for MAIN) |
| `meter_type` | string | yes |  | `MAIN`, `SUB` |  |  | Position in hierarchy |
| `measured_scope` | string | yes |  | `PLANT_INCOMER`, `MACHINE`, `UTILITIES` |  |  | What the meter measures |
| `serial_no` | string | yes | yes |  |  |  | Device serial |
| `source_system` | string | yes |  | `AMI`, `SCADA` |  |  | Telemetry source |
| `energy_unit` | string | yes |  | `kWh` |  |  | Unit of interval/register energy |
| `demand_unit` | string | yes |  | `kW` |  |  | Unit of avg demand |
| `sampling_interval_min` | integer | yes |  | `15` | min |  | Reading cadence |
| `ct_ratio` | string | yes |  |  |  |  | Installed current-transformer ratio |
| `installed_at` | datetime | yes |  |  |  |  | Installation timestamp (UTC) |
| `status` | string | yes |  | `ACTIVE`, `COMM_LOSS`, `RETIRED` |  |  | Current lifecycle state (latest meter_status_event) |

## Machine — `machine`

Production or utility equipment with nameplate power.

*Primary key:* `machine_id` · *Kind:* master

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `machine_id` | string | yes | yes |  |  | pattern `MCH-PLT\d{2}-\d{3}` | MCH-<plant-id>-NNN |
| `plant_id` | string | yes |  |  |  | FK → `plant.plant_id` | Owning plant |
| `machine_type` | string | yes |  | `INDUCTION_FURNACE`, `FORGING_PRESS`, `CNC_CELL`, `INJECTION_MOLDER`, `EXTRUDER`, `PAINT_OVEN`, `AIR_COMPRESSOR`, `HVAC_AHU` |  |  | Equipment class |
| `machine_name` | string | yes |  |  |  |  | Display name |
| `is_production` | boolean | yes |  |  |  |  | True if it runs production batches |
| `rated_kw` | decimal | yes |  |  | kW | > 0 | Nameplate power |
| `idle_kw` | decimal | yes |  |  | kW | 0 < idle_kw < rated_kw | Expected idle (ready, not producing) power |
| `standby_kw` | decimal | yes |  |  | kW | 0 < standby_kw < idle_kw (utilities: <=) | Expected standby power |
| `commissioned_at` | datetime | yes |  |  |  |  | Start of service (UTC) |
| `decommissioned_at` | datetime | no |  |  |  | > commissioned_at | End of service (UTC) |
| `status` | string | yes |  | `INSTALLED`, `ACTIVE`, `UNDER_MAINTENANCE`, `DECOMMISSIONED` |  |  | Current lifecycle state (latest machine_status_event) |

## MeterMachineMap (bridge) — `meter_machine_map`

Effective-dated N:M bridge between meters and machines. History rows are closed, never overwritten.

*Primary key:* `map_id` · *Kind:* master

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `map_id` | string | yes | yes |  |  | pattern `MMAP-\d{4}` | Bridge row id |
| `meter_id` | string | yes |  |  |  | FK → `meter.meter_id`; must be a SUB meter | Meter |
| `machine_id` | string | yes |  |  |  | FK → `machine.machine_id`; same plant as meter | Machine |
| `allocation_pct` | decimal | yes |  |  | % | 0 < x <= 100 | Share of machine energy measured by this meter |
| `effective_from` | datetime | yes |  |  |  |  | Mapping valid from (UTC, inclusive) |
| `effective_to` | datetime | no |  |  |  | > effective_from; no overlapping open mappings for a single-machine meter | Mapping valid to (UTC, exclusive); null = open |

## Shift — `shift`

Shift template in plant local time.

*Primary key:* `shift_id` · *Kind:* master

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `shift_id` | string | yes | yes |  |  | pattern `SHF-PLT\d{2}-[ABC]` | SHF-<plant-id>-<code> |
| `plant_id` | string | yes |  |  |  | FK → `plant.plant_id` | Plant |
| `shift_code` | string | yes |  | `A`, `B`, `C` |  |  | Shift code |
| `start_local` | time | yes |  |  |  |  | Local start HH:MM |
| `end_local` | time | yes |  |  |  |  | Local end HH:MM |
| `crosses_midnight` | boolean | yes |  |  |  |  | True if end_local <= start_local |
| `working_days` | string | yes |  |  |  |  | Comma list of MON..SUN |

## Shift calendar — `shift_instance`

One dated occurrence of a shift (DST-aware UTC bounds).

*Primary key:* `shift_instance_id` · *Kind:* master

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `shift_instance_id` | string | yes | yes |  |  | pattern `SHI-PLT\d{2}-\d{8}-[ABC]` | SHI-<plant>-<yyyymmdd>-<code> |
| `shift_id` | string | yes |  |  |  | FK → `shift.shift_id` | Template |
| `plant_id` | string | yes |  |  |  | FK → `plant.plant_id` | Plant |
| `business_date` | date | yes |  |  |  |  | Local business date |
| `start_utc` | datetime | yes |  |  |  |  | Start (UTC) |
| `end_utc` | datetime | yes |  |  |  | > start_utc | End (UTC) |
| `calendar_status` | string | yes |  | `WORKING`, `HOLIDAY` |  |  | Working day or plant holiday |

## Tariff — `tariff`

Time-of-use tariff version for a plant (effective-dated).

*Primary key:* `tariff_id` · *Kind:* master

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `tariff_id` | string | yes | yes |  |  | pattern `TAR-2026-\d{3}` | TAR-2026-NNN |
| `plant_id` | string | yes |  |  |  | FK → `plant.plant_id` | Plant |
| `utility_name` | string | yes |  |  |  |  | Utility / tariff name (synthetic) |
| `tariff_version` | integer | yes |  |  |  | >= 1 | Version number per plant |
| `currency` | string | yes |  | `INR`, `USD`, `EUR` |  | = plant.currency | Billing currency |
| `timezone` | string | yes |  |  |  | should equal plant.timezone (R-TZ-01) | Timezone windows are expressed in |
| `effective_from` | date | yes |  |  |  |  | Local date, inclusive |
| `effective_to` | date | no |  |  |  | >= effective_from; versions of one plant must not overlap | Local date, inclusive; null = open |
| `demand_charge_per_kw_month` | decimal | yes |  |  | currency/kW-month |  | Demand charge on monthly max 15-min kW |

## TariffWindow — `tariff_window`

TOU price window; each tariff must cover 7x24h exactly once.

*Primary key:* `window_id` · *Kind:* master

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `window_id` | string | yes | yes |  |  | pattern `TAR-2026-\d{3}-W\d{2}` | <tariff_id>-WNN |
| `tariff_id` | string | yes |  |  |  | FK → `tariff.tariff_id` | Tariff |
| `period` | string | yes |  | `PEAK`, `SHOULDER`, `NORMAL`, `OFFPEAK` |  |  | TOU period |
| `days_of_week` | string | yes |  |  |  |  | Comma list of MON..SUN |
| `start_local` | time | yes |  |  |  |  | Local start HH:MM (inclusive) |
| `end_local` | time | yes |  |  |  | > start_local | Local end HH:MM (exclusive, 24:00 allowed) |
| `rate_per_kwh` | decimal | yes |  |  | currency/kWh | > 0 | Energy rate |

## WeatherObservation — `weather_observation`

Hourly synthetic weather per plant.

*Primary key:* `observation_id` · *Kind:* transaction

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `observation_id` | string | yes | yes |  |  | pattern `WTH-PLT\d{2}-\d{8}T\d{2}Z` | WTH-<plant>-<yyyymmddThh>Z |
| `plant_id` | string | yes |  |  |  | FK → `plant.plant_id` | Plant |
| `ts_utc` | datetime | yes |  |  |  |  | Observation hour start (UTC) |
| `temp_c` | decimal | yes |  |  | degC | -40..55 | Dry-bulb temperature |
| `rel_humidity_pct` | decimal | yes |  |  | % | 0..100 | Relative humidity |
| `wind_speed_ms` | decimal | yes |  |  | m/s | >= 0 | Wind speed |
| `condition` | string | yes |  | `CLEAR`, `CLOUDY`, `RAIN`, `SNOW` |  |  | Sky condition |
| `source` | string | yes |  | `SYNTHETIC` |  |  | Provenance |

## ProductionBatch — `production_batch`

Production run on one machine within one shift.

*Primary key:* `batch_id` · *Kind:* transaction

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `batch_id` | string | yes | yes |  |  | pattern `BATCH-2026-\d{6}` | BATCH-2026-NNNNNN |
| `plant_id` | string | yes |  |  |  | FK → `plant.plant_id` | Plant (= machine.plant_id) |
| `machine_id` | string | yes |  |  |  | FK → `machine.machine_id`; machine in service; is_production | Production machine |
| `shift_instance_id` | string | yes |  |  |  | FK → `shift_instance.shift_instance_id` | Shift it was scheduled in |
| `product_code` | string | yes |  |  |  |  | Product / SKU |
| `unit_of_measure` | string | yes |  | `pcs`, `m` |  |  | Output unit |
| `planned_start_utc` | datetime | yes |  |  |  |  | Planned start |
| `planned_end_utc` | datetime | yes |  |  |  | > planned_start_utc | Planned end |
| `actual_start_utc` | datetime | no |  |  |  |  | Actual start (null if CANCELLED) |
| `actual_end_utc` | datetime | no |  |  |  | > actual_start_utc | Actual end (null if CANCELLED) |
| `planned_units` | integer | yes |  |  |  | >= 0 | Planned output |
| `produced_units` | integer | yes |  |  |  | >= 0; 0 if CANCELLED | Total output |
| `good_units` | integer | yes |  |  |  | <= produced_units | Output passing QC |
| `scrap_units` | integer | yes |  |  |  | = produced_units - good_units | Rejected output |
| `status` | string | yes |  | `PLANNED`, `RELEASED`, `RUNNING`, `COMPLETED`, `SCRAPPED`, `CANCELLED` |  |  | Derived = last batch_status_event.to_status |

## BatchStatusEvent — `batch_status_event`

Append-only batch lifecycle history.

*Primary key:* `batch_event_id` · *Kind:* event

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `batch_event_id` | string | yes | yes |  |  | pattern `BEV-2026-\d{7}` | BEV-2026-NNNNNNN |
| `batch_id` | string | yes |  |  |  | FK → `production_batch.batch_id` | Batch |
| `from_status` | string | no |  | `PLANNED`, `RELEASED`, `RUNNING`, `COMPLETED`, `SCRAPPED`, `CANCELLED` |  |  | Previous status (null for first) |
| `to_status` | string | yes |  | `PLANNED`, `RELEASED`, `RUNNING`, `COMPLETED`, `SCRAPPED`, `CANCELLED` |  | PLANNED>RELEASED>RUNNING>COMPLETED|SCRAPPED; PLANNED|RELEASED>CANCELLED | New status |
| `event_ts` | datetime | yes |  |  |  | non-decreasing per batch | When it happened |
| `actor_role` | string | yes |  | `planner`, `operator`, `quality_engineer` |  |  | Who |

## MaintenanceEvent — `maintenance_event`

Maintenance work order on a machine.

*Primary key:* `maintenance_id` · *Kind:* transaction

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `maintenance_id` | string | yes | yes |  |  | pattern `MNT-2026-\d{6}` | MNT-2026-NNNNNN |
| `machine_id` | string | yes |  |  |  | FK → `machine.machine_id` | Machine |
| `plant_id` | string | yes |  |  |  | FK → `plant.plant_id` | Plant |
| `maintenance_type` | string | yes |  | `PREVENTIVE`, `CORRECTIVE` |  |  | Type |
| `reason` | string | yes |  |  |  |  | Reason / symptom |
| `opened_at` | datetime | yes |  |  |  |  | Work order opened |
| `started_at` | datetime | yes |  |  |  | >= opened_at | Lock-out start |
| `closed_at` | datetime | yes |  |  |  | > started_at | Returned to service |
| `raised_by_role` | string | yes |  | `maintenance_engineer` |  |  | Raised by |
| `downtime_min` | integer | yes |  |  | min |  | Derived closed_at - started_at |
| `status` | string | yes |  | `OPEN`, `IN_PROGRESS`, `CLOSED` |  |  | Derived = last maintenance_status_event |

## MaintenanceStatusEvent — `maintenance_status_event`

Work-order lifecycle history.

*Primary key:* `maintenance_event_id` · *Kind:* event

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `maintenance_event_id` | string | yes | yes |  |  | pattern `MSE-2026-\d{6}` | MSE-2026-NNNNNN |
| `maintenance_id` | string | yes |  |  |  | FK → `maintenance_event.maintenance_id` | Work order |
| `from_status` | string | no |  | `OPEN`, `IN_PROGRESS`, `CLOSED` |  |  | Previous |
| `to_status` | string | yes |  | `OPEN`, `IN_PROGRESS`, `CLOSED` |  | OPEN>IN_PROGRESS>CLOSED | New |
| `event_ts` | datetime | yes |  |  |  |  | When |

## MachineStatusEvent — `machine_status_event`

Machine lifecycle history.

*Primary key:* `machine_event_id` · *Kind:* event

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `machine_event_id` | string | yes | yes |  |  | pattern `MCE-2026-\d{6}` | MCE-2026-NNNNNN |
| `machine_id` | string | yes |  |  |  | FK → `machine.machine_id` | Machine |
| `from_status` | string | no |  | `INSTALLED`, `ACTIVE`, `UNDER_MAINTENANCE`, `DECOMMISSIONED` |  |  | Previous |
| `to_status` | string | yes |  | `INSTALLED`, `ACTIVE`, `UNDER_MAINTENANCE`, `DECOMMISSIONED` |  | INSTALLED>ACTIVE; ACTIVE<>UNDER_MAINTENANCE; ACTIVE>DECOMMISSIONED | New |
| `event_ts` | datetime | yes |  |  |  |  | When |
| `maintenance_id` | string | no |  |  |  | FK → `maintenance_event.maintenance_id` | Related work order |

## MeterStatusEvent — `meter_status_event`

Meter lifecycle / communication history.

*Primary key:* `meter_event_id` · *Kind:* event

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `meter_event_id` | string | yes | yes |  |  | pattern `MTE-2026-\d{6}` | MTE-2026-NNNNNN |
| `meter_id` | string | yes |  |  |  | FK → `meter.meter_id` | Meter |
| `from_status` | string | no |  | `ACTIVE`, `COMM_LOSS`, `RETIRED` |  |  | Previous |
| `to_status` | string | yes |  | `ACTIVE`, `COMM_LOSS`, `RETIRED` |  |  | New |
| `event_ts` | datetime | yes |  |  |  |  | When |
| `note` | string | yes |  |  |  |  | Free text |

## MachineStateInterval — `machine_state_interval`

PLC machine-state history (idle-state periods), contiguous and non-overlapping per machine.

*Primary key:* `state_interval_id` · *Kind:* event

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `state_interval_id` | string | yes | yes |  |  | pattern `MSI-2026-\d{7}` | MSI-2026-NNNNNNN |
| `machine_id` | string | yes |  |  |  | FK → `machine.machine_id` | Production machine |
| `state` | string | yes |  | `OFF`, `STANDBY`, `IDLE`, `RUNNING`, `MAINTENANCE`, `OUT_OF_SERVICE` |  |  | Operating state |
| `start_utc` | datetime | yes |  |  |  |  | Start (inclusive) |
| `end_utc` | datetime | yes |  |  |  | > start_utc; next interval starts here | End (exclusive) |
| `duration_min` | integer | yes |  |  | min |  | Derived end - start |
| `source` | string | yes |  | `PLC` |  |  | Telemetry source |

## EnergyReading (raw landing) — `energy_reading`

15-minute meter readings as ingested. reading_id is the natural key and SHOULD be unique; duplicates are retained here and resolved by the analytics (R-DUP-01).

*Primary key:* `ingest_seq` · *Kind:* transaction

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `ingest_seq` | integer | yes | yes |  |  |  | Ingestion sequence (landing PK) |
| `reading_id` | string | yes |  |  |  | pattern `ENG-MTR-PLT\d{2}-\d{3}-\d{8}T\d{4}Z`; unique after de-duplication | ENG-<meter-id>-<yyyymmddThhmm>Z (natural key) |
| `meter_id` | string | yes |  |  |  | FK → `meter.meter_id` | Meter |
| `machine_id` | string | no |  |  |  | FK → `machine.machine_id`; must be mapped to meter_id at ts_utc in meter_machine_map (R-HIER-02) | Machine attribution (MACHINE-scope meters only) |
| `ts_utc` | datetime | yes |  |  |  |  | Interval start (UTC), aligned to :00/:15/:30/:45 |
| `interval_kwh` | decimal | yes |  |  | kWh | >= 0; = avg_kw x 0.25 (R-UNIT-01); = register delta (R-REG-01) | Energy in the 15-min interval |
| `avg_kw` | decimal | yes |  |  | kW | >= 0 | Average demand over the interval |
| `register_kwh` | decimal | yes |  |  | kWh | non-decreasing | Cumulative energy register |
| `unit` | string | yes |  | `kWh` |  |  | Declared unit of interval_kwh |
| `source_system` | string | yes |  | `AMI`, `SCADA` |  |  | AMI or SCADA |
| `ingested_at` | datetime | yes |  |  |  | > ts_utc + 15 min | Landing time (UTC) |

## Recommendation — `recommendation`

Analytics output: an energy-saving action with baseline and savings.

*Primary key:* `rec_id` · *Kind:* output

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `rec_id` | string | yes | yes |  |  | pattern `REC-2026-\d{6}` | REC-2026-NNNNNN |
| `plant_id` | string | yes |  |  |  | FK → `plant.plant_id` | Plant |
| `scope_type` | string | yes |  | `plant`, `machine`, `meter` |  |  | Target entity type |
| `scope_id` | string | yes |  |  |  |  | Target entity id |
| `rule_id` | string | yes |  |  |  |  | Rule that produced it (docs/RULES.md) |
| `title` | string | yes |  |  |  |  | Action |
| `owner_role` | string | yes |  | `plant_operator`, `maintenance_engineer`, `production_planner`, `ot_it_admin` |  |  | Persona expected to act |
| `baseline_metric` | string | yes |  |  |  |  | What was measured |
| `baseline_value` | decimal | yes |  |  |  |  | Measured baseline over the analysis window |
| `baseline_unit` | string | yes |  |  |  |  | Unit of baseline_value |
| `baseline_window_start_utc` | datetime | yes |  |  |  |  | Analysis window start |
| `baseline_window_end_utc` | datetime | yes |  |  |  |  | Analysis window end |
| `expected_savings_kwh_yr` | decimal | yes |  |  | kWh/yr | >= 0 | Annualised energy savings |
| `expected_savings_kw` | decimal | yes |  |  | kW | >= 0 | Peak demand reduction |
| `expected_savings_cost_yr` | decimal | yes |  |  | currency/yr | >= 0 | Annualised cost savings |
| `currency` | string | yes |  | `INR`, `USD`, `EUR` |  |  | Plant currency |
| `expected_savings_usd_yr` | decimal | yes |  |  | USD/yr |  | Annualised savings in USD (fixed FX) |
| `savings_formula` | string | yes |  |  |  |  | How savings were computed |
| `confidence` | string | yes |  | `HIGH`, `MEDIUM`, `LOW` |  |  | Confidence band |
| `evidence_ids` | string | yes |  |  |  |  | Semicolon list of finding ids |
| `status` | string | yes |  | `PROPOSED`, `ACCEPTED`, `REJECTED`, `IMPLEMENTED`, `VERIFIED` |  |  | Derived = last recommendation_event |

## Finding — `finding`

Analytics output: one detected exception or waste event.

*Primary key:* `finding_id` · *Kind:* output

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `finding_id` | string | yes | yes |  |  | pattern `FND-2026-\d{6}` | FND-2026-NNNNNN |
| `issue_type` | string | yes |  |  |  |  | Detected issue type |
| `category` | string | yes |  | `DATA_QUALITY`, `WASTE` |  |  | DATA_QUALITY or WASTE |
| `plant_id` | string | yes |  |  |  | FK → `plant.plant_id` | Plant |
| `entity_type` | string | yes |  | `meter`, `machine`, `tariff`, `reading`, `plant` |  |  | Entity kind |
| `entity_id` | string | yes |  |  |  |  | Entity id |
| `window_start_utc` | datetime | yes |  |  |  |  | Start |
| `window_end_utc` | datetime | yes |  |  |  |  | End |
| `rule_id` | string | yes |  |  |  |  | Detection rule |
| `decision` | string | yes |  |  |  |  | Action taken by the pipeline |
| `metric_value` | decimal | no |  |  |  |  | Key measured quantity |
| `metric_unit` | string | no |  |  |  |  | Unit of metric_value |
| `impact_kwh` | decimal | no |  |  | kWh |  | Energy affected / wasted |
| `owner_role` | string | yes |  | `plant_operator`, `maintenance_engineer`, `production_planner`, `ot_it_admin` |  |  | Persona |
| `detail` | string | yes |  |  |  |  | Human-readable evidence |

## Ground truth — `ground_truth/ground_truth.csv`

Kept outside `csv/`, never loaded by the analytics (only by `evaluate.py` after all findings exist).

| Field | Type | Required | Unique | Allowed values | Unit | Validation rule | Description |
|---|---|---|---|---|---|---|---|
| `gt_id` | string | yes | yes |  |  | pattern `GT-2026-\d{5}` | GT-2026-NNNNN |
| `issue_type` | string | yes |  |  |  |  | Injected issue / scenario |
| `category` | string | yes |  |  |  |  | DATA_ERROR | TELEMETRY_GAP | WASTE_SCENARIO |
| `plant_id` | string | yes |  |  |  |  | Plant |
| `entity_type` | string | yes |  |  |  |  | meter | machine | tariff | reading |
| `entity_id` | string | yes |  |  |  |  | Affected entity |
| `window_start_utc` | datetime | yes |  |  |  |  | Start of affected window |
| `window_end_utc` | datetime | yes |  |  |  |  | End (exclusive) |
| `impact_kwh` | decimal | yes |  |  | kWh |  | True energy affected |
| `params` | string | yes |  |  |  |  | JSON of injection parameters |
| `expected_detection` | string | yes |  |  |  |  | Rule expected to catch it |
| `expected_decision` | string | yes |  |  |  |  | Decision the pipeline should take |
