"""Single source of truth for the data dictionary.

Drives: docs/DATA_DICTIONARY.md, SQL DDL (schema.sql), and the type / required / enum / pattern / FK checks
in validate.py. Types: string, integer, decimal, boolean, date, time, datetime (UTC ISO-8601 'Z').
"""
from dataclasses import dataclass, field


@dataclass
class F:
    name: str
    type: str
    desc: str
    required: bool = True
    unique: bool = False
    allowed: tuple = ()
    unit: str = ""
    fk: str = ""          # "table.column"
    pattern: str = ""     # key into ids.PATTERNS
    rule: str = ""        # human-readable validation rule


@dataclass
class T:
    name: str
    entity: str
    pk: str
    desc: str
    fields: list = field(default_factory=list)
    kind: str = "master"  # master | transaction | event | output


STATUS_PLANT = ("ACTIVE", "INACTIVE")
MACHINE_TYPES = ("INDUCTION_FURNACE", "FORGING_PRESS", "CNC_CELL", "INJECTION_MOLDER", "EXTRUDER", "PAINT_OVEN",
                 "AIR_COMPRESSOR", "HVAC_AHU")
MACHINE_STATUS = ("INSTALLED", "ACTIVE", "UNDER_MAINTENANCE", "DECOMMISSIONED")
BATCH_STATUS = ("PLANNED", "RELEASED", "RUNNING", "COMPLETED", "SCRAPPED", "CANCELLED")
MAINT_STATUS = ("OPEN", "IN_PROGRESS", "CLOSED")
METER_STATUS = ("ACTIVE", "COMM_LOSS", "RETIRED")
PERIODS = ("PEAK", "SHOULDER", "NORMAL", "OFFPEAK")
STATES = ("OFF", "STANDBY", "IDLE", "RUNNING", "MAINTENANCE", "OUT_OF_SERVICE")
REC_STATUS = ("PROPOSED", "ACCEPTED", "REJECTED", "IMPLEMENTED", "VERIFIED")

TABLES = [
    T("plant", "Plant", "plant_id", "A manufacturing site; owns meters, machines, shifts and tariffs.", [
        F("plant_id", "string", "Plant identifier", unique=True, pattern="plant_id", rule="PLT + 2 digits"),
        F("plant_name", "string", "Display name"),
        F("city", "string", "City"),
        F("country_code", "string", "ISO 3166-1 alpha-2", allowed=("IN", "US", "DE")),
        F("timezone", "string", "IANA timezone of plant wall clock; tariffs and shifts are defined in it"),
        F("currency", "string", "ISO 4217 billing currency", allowed=("INR", "USD", "EUR")),
        F("latitude", "decimal", "WGS84 latitude", unit="deg", rule="-90..90"),
        F("longitude", "decimal", "WGS84 longitude", unit="deg", rule="-180..180"),
        F("status", "string", "Lifecycle state", allowed=STATUS_PLANT),
    ]),
    T("meter", "Meter", "meter_id", "Energy meter. MAIN incomer is parent of SUB meters (self-referencing hierarchy).", [
        F("meter_id", "string", "MTR-<plant-id>-NNN", unique=True, pattern="meter_id"),
        F("plant_id", "string", "Owning plant", fk="plant.plant_id"),
        F("parent_meter_id", "string", "Upstream meter (null for MAIN)", required=False, fk="meter.meter_id",
          rule="MAIN has null parent; SUB parent must be the MAIN of the same plant"),
        F("meter_type", "string", "Position in hierarchy", allowed=("MAIN", "SUB")),
        F("measured_scope", "string", "What the meter measures", allowed=("PLANT_INCOMER", "MACHINE", "UTILITIES")),
        F("serial_no", "string", "Device serial", unique=True),
        F("source_system", "string", "Telemetry source", allowed=("AMI", "SCADA")),
        F("energy_unit", "string", "Unit of interval/register energy", allowed=("kWh",)),
        F("demand_unit", "string", "Unit of avg demand", allowed=("kW",)),
        F("sampling_interval_min", "integer", "Reading cadence", unit="min", allowed=(15,)),
        F("ct_ratio", "string", "Installed current-transformer ratio"),
        F("installed_at", "datetime", "Installation timestamp (UTC)"),
        F("status", "string", "Current lifecycle state (latest meter_status_event)", allowed=METER_STATUS),
    ]),
    T("machine", "Machine", "machine_id", "Production or utility equipment with nameplate power.", [
        F("machine_id", "string", "MCH-<plant-id>-NNN", unique=True, pattern="machine_id"),
        F("plant_id", "string", "Owning plant", fk="plant.plant_id"),
        F("machine_type", "string", "Equipment class", allowed=MACHINE_TYPES),
        F("machine_name", "string", "Display name"),
        F("is_production", "boolean", "True if it runs production batches"),
        F("rated_kw", "decimal", "Nameplate power", unit="kW", rule="> 0"),
        F("idle_kw", "decimal", "Expected idle (ready, not producing) power", unit="kW", rule="0 < idle_kw < rated_kw"),
        F("standby_kw", "decimal", "Expected standby power", unit="kW", rule="0 < standby_kw < idle_kw (utilities: <=)"),
        F("commissioned_at", "datetime", "Start of service (UTC)"),
        F("decommissioned_at", "datetime", "End of service (UTC)", required=False, rule="> commissioned_at"),
        F("status", "string", "Current lifecycle state (latest machine_status_event)", allowed=MACHINE_STATUS),
    ]),
    T("meter_machine_map", "MeterMachineMap (bridge)", "map_id",
      "Effective-dated N:M bridge between meters and machines. History rows are closed, never overwritten.", [
          F("map_id", "string", "Bridge row id", unique=True, pattern="map_id"),
          F("meter_id", "string", "Meter", fk="meter.meter_id", rule="must be a SUB meter"),
          F("machine_id", "string", "Machine", fk="machine.machine_id", rule="same plant as meter"),
          F("allocation_pct", "decimal", "Share of machine energy measured by this meter", unit="%", rule="0 < x <= 100"),
          F("effective_from", "datetime", "Mapping valid from (UTC, inclusive)"),
          F("effective_to", "datetime", "Mapping valid to (UTC, exclusive); null = open", required=False,
            rule="> effective_from; no overlapping open mappings for a single-machine meter"),
      ]),
    T("shift", "Shift", "shift_id", "Shift template in plant local time.", [
        F("shift_id", "string", "SHF-<plant-id>-<code>", unique=True, pattern="shift_id"),
        F("plant_id", "string", "Plant", fk="plant.plant_id"),
        F("shift_code", "string", "Shift code", allowed=("A", "B", "C")),
        F("start_local", "time", "Local start HH:MM"),
        F("end_local", "time", "Local end HH:MM"),
        F("crosses_midnight", "boolean", "True if end_local <= start_local"),
        F("working_days", "string", "Comma list of MON..SUN"),
    ], kind="master"),
    T("shift_instance", "Shift calendar", "shift_instance_id", "One dated occurrence of a shift (DST-aware UTC bounds).", [
        F("shift_instance_id", "string", "SHI-<plant>-<yyyymmdd>-<code>", unique=True, pattern="shift_instance_id"),
        F("shift_id", "string", "Template", fk="shift.shift_id"),
        F("plant_id", "string", "Plant", fk="plant.plant_id"),
        F("business_date", "date", "Local business date"),
        F("start_utc", "datetime", "Start (UTC)"),
        F("end_utc", "datetime", "End (UTC)", rule="> start_utc"),
        F("calendar_status", "string", "Working day or plant holiday", allowed=("WORKING", "HOLIDAY")),
    ], kind="master"),
    T("tariff", "Tariff", "tariff_id", "Time-of-use tariff version for a plant (effective-dated).", [
        F("tariff_id", "string", "TAR-2026-NNN", unique=True, pattern="tariff_id"),
        F("plant_id", "string", "Plant", fk="plant.plant_id"),
        F("utility_name", "string", "Utility / tariff name (synthetic)"),
        F("tariff_version", "integer", "Version number per plant", rule=">= 1"),
        F("currency", "string", "Billing currency", allowed=("INR", "USD", "EUR"), rule="= plant.currency"),
        F("timezone", "string", "Timezone windows are expressed in", rule="should equal plant.timezone (R-TZ-01)"),
        F("effective_from", "date", "Local date, inclusive"),
        F("effective_to", "date", "Local date, inclusive; null = open", required=False,
          rule=">= effective_from; versions of one plant must not overlap"),
        F("demand_charge_per_kw_month", "decimal", "Demand charge on monthly max 15-min kW", unit="currency/kW-month"),
    ]),
    T("tariff_window", "TariffWindow", "window_id", "TOU price window; each tariff must cover 7x24h exactly once.", [
        F("window_id", "string", "<tariff_id>-WNN", unique=True, pattern="window_id"),
        F("tariff_id", "string", "Tariff", fk="tariff.tariff_id"),
        F("period", "string", "TOU period", allowed=PERIODS),
        F("days_of_week", "string", "Comma list of MON..SUN"),
        F("start_local", "time", "Local start HH:MM (inclusive)"),
        F("end_local", "time", "Local end HH:MM (exclusive, 24:00 allowed)", rule="> start_local"),
        F("rate_per_kwh", "decimal", "Energy rate", unit="currency/kWh", rule="> 0"),
    ]),
    T("weather_observation", "WeatherObservation", "observation_id", "Hourly synthetic weather per plant.", [
        F("observation_id", "string", "WTH-<plant>-<yyyymmddThh>Z", unique=True, pattern="observation_id"),
        F("plant_id", "string", "Plant", fk="plant.plant_id"),
        F("ts_utc", "datetime", "Observation hour start (UTC)"),
        F("temp_c", "decimal", "Dry-bulb temperature", unit="degC", rule="-40..55"),
        F("rel_humidity_pct", "decimal", "Relative humidity", unit="%", rule="0..100"),
        F("wind_speed_ms", "decimal", "Wind speed", unit="m/s", rule=">= 0"),
        F("condition", "string", "Sky condition", allowed=("CLEAR", "CLOUDY", "RAIN", "SNOW")),
        F("source", "string", "Provenance", allowed=("SYNTHETIC",)),
    ], kind="transaction"),
    T("production_batch", "ProductionBatch", "batch_id", "Production run on one machine within one shift.", [
        F("batch_id", "string", "BATCH-2026-NNNNNN", unique=True, pattern="batch_id"),
        F("plant_id", "string", "Plant (= machine.plant_id)", fk="plant.plant_id"),
        F("machine_id", "string", "Production machine", fk="machine.machine_id", rule="machine in service; is_production"),
        F("shift_instance_id", "string", "Shift it was scheduled in", fk="shift_instance.shift_instance_id"),
        F("product_code", "string", "Product / SKU"),
        F("unit_of_measure", "string", "Output unit", allowed=("pcs", "m")),
        F("planned_start_utc", "datetime", "Planned start"),
        F("planned_end_utc", "datetime", "Planned end", rule="> planned_start_utc"),
        F("actual_start_utc", "datetime", "Actual start (null if CANCELLED)", required=False),
        F("actual_end_utc", "datetime", "Actual end (null if CANCELLED)", required=False, rule="> actual_start_utc"),
        F("planned_units", "integer", "Planned output", rule=">= 0"),
        F("produced_units", "integer", "Total output", rule=">= 0; 0 if CANCELLED"),
        F("good_units", "integer", "Output passing QC", rule="<= produced_units"),
        F("scrap_units", "integer", "Rejected output", rule="= produced_units - good_units"),
        F("status", "string", "Derived = last batch_status_event.to_status", allowed=BATCH_STATUS),
    ], kind="transaction"),
    T("batch_status_event", "BatchStatusEvent", "batch_event_id", "Append-only batch lifecycle history.", [
        F("batch_event_id", "string", "BEV-2026-NNNNNNN", unique=True, pattern="batch_event_id"),
        F("batch_id", "string", "Batch", fk="production_batch.batch_id"),
        F("from_status", "string", "Previous status (null for first)", required=False, allowed=BATCH_STATUS),
        F("to_status", "string", "New status", allowed=BATCH_STATUS,
          rule="PLANNED>RELEASED>RUNNING>COMPLETED|SCRAPPED; PLANNED|RELEASED>CANCELLED"),
        F("event_ts", "datetime", "When it happened", rule="non-decreasing per batch"),
        F("actor_role", "string", "Who", allowed=("planner", "operator", "quality_engineer")),
    ], kind="event"),
    T("maintenance_event", "MaintenanceEvent", "maintenance_id", "Maintenance work order on a machine.", [
        F("maintenance_id", "string", "MNT-2026-NNNNNN", unique=True, pattern="maintenance_id"),
        F("machine_id", "string", "Machine", fk="machine.machine_id"),
        F("plant_id", "string", "Plant", fk="plant.plant_id"),
        F("maintenance_type", "string", "Type", allowed=("PREVENTIVE", "CORRECTIVE")),
        F("reason", "string", "Reason / symptom"),
        F("opened_at", "datetime", "Work order opened"),
        F("started_at", "datetime", "Lock-out start", rule=">= opened_at"),
        F("closed_at", "datetime", "Returned to service", rule="> started_at"),
        F("raised_by_role", "string", "Raised by", allowed=("maintenance_engineer",)),
        F("downtime_min", "integer", "Derived closed_at - started_at", unit="min"),
        F("status", "string", "Derived = last maintenance_status_event", allowed=MAINT_STATUS),
    ], kind="transaction"),
    T("maintenance_status_event", "MaintenanceStatusEvent", "maintenance_event_id", "Work-order lifecycle history.", [
        F("maintenance_event_id", "string", "MSE-2026-NNNNNN", unique=True, pattern="maintenance_event_id"),
        F("maintenance_id", "string", "Work order", fk="maintenance_event.maintenance_id"),
        F("from_status", "string", "Previous", required=False, allowed=MAINT_STATUS),
        F("to_status", "string", "New", allowed=MAINT_STATUS, rule="OPEN>IN_PROGRESS>CLOSED"),
        F("event_ts", "datetime", "When"),
    ], kind="event"),
    T("machine_status_event", "MachineStatusEvent", "machine_event_id", "Machine lifecycle history.", [
        F("machine_event_id", "string", "MCE-2026-NNNNNN", unique=True, pattern="machine_event_id"),
        F("machine_id", "string", "Machine", fk="machine.machine_id"),
        F("from_status", "string", "Previous", required=False, allowed=MACHINE_STATUS),
        F("to_status", "string", "New", allowed=MACHINE_STATUS,
          rule="INSTALLED>ACTIVE; ACTIVE<>UNDER_MAINTENANCE; ACTIVE>DECOMMISSIONED"),
        F("event_ts", "datetime", "When"),
        F("maintenance_id", "string", "Related work order", required=False, fk="maintenance_event.maintenance_id"),
    ], kind="event"),
    T("meter_status_event", "MeterStatusEvent", "meter_event_id", "Meter lifecycle / communication history.", [
        F("meter_event_id", "string", "MTE-2026-NNNNNN", unique=True, pattern="meter_event_id"),
        F("meter_id", "string", "Meter", fk="meter.meter_id"),
        F("from_status", "string", "Previous", required=False, allowed=METER_STATUS),
        F("to_status", "string", "New", allowed=METER_STATUS),
        F("event_ts", "datetime", "When"),
        F("note", "string", "Free text"),
    ], kind="event"),
    T("machine_state_interval", "MachineStateInterval", "state_interval_id",
      "PLC machine-state history (idle-state periods), contiguous and non-overlapping per machine.", [
          F("state_interval_id", "string", "MSI-2026-NNNNNNN", unique=True, pattern="state_interval_id"),
          F("machine_id", "string", "Production machine", fk="machine.machine_id"),
          F("state", "string", "Operating state", allowed=STATES),
          F("start_utc", "datetime", "Start (inclusive)"),
          F("end_utc", "datetime", "End (exclusive)", rule="> start_utc; next interval starts here"),
          F("duration_min", "integer", "Derived end - start", unit="min"),
          F("source", "string", "Telemetry source", allowed=("PLC",)),
      ], kind="event"),
    T("energy_reading", "EnergyReading (raw landing)", "ingest_seq",
      "15-minute meter readings as ingested. reading_id is the natural key and SHOULD be unique; "
      "duplicates are retained here and resolved by the analytics (R-DUP-01).", [
          F("ingest_seq", "integer", "Ingestion sequence (landing PK)", unique=True),
          F("reading_id", "string", "ENG-<meter-id>-<yyyymmddThhmm>Z (natural key)", pattern="reading_id",
            rule="unique after de-duplication"),
          F("meter_id", "string", "Meter", fk="meter.meter_id"),
          F("machine_id", "string", "Machine attribution (MACHINE-scope meters only)", required=False,
            fk="machine.machine_id", rule="must be mapped to meter_id at ts_utc in meter_machine_map (R-HIER-02)"),
          F("ts_utc", "datetime", "Interval start (UTC), aligned to :00/:15/:30/:45"),
          F("interval_kwh", "decimal", "Energy in the 15-min interval", unit="kWh",
            rule=">= 0; = avg_kw x 0.25 (R-UNIT-01); = register delta (R-REG-01)"),
          F("avg_kw", "decimal", "Average demand over the interval", unit="kW", rule=">= 0"),
          F("register_kwh", "decimal", "Cumulative energy register", unit="kWh", rule="non-decreasing"),
          F("unit", "string", "Declared unit of interval_kwh", allowed=("kWh",)),
          F("source_system", "string", "AMI or SCADA", allowed=("AMI", "SCADA")),
          F("ingested_at", "datetime", "Landing time (UTC)", rule="> ts_utc + 15 min"),
      ], kind="transaction"),
    T("recommendation", "Recommendation", "rec_id", "Analytics output: an energy-saving action with baseline and savings.", [
        F("rec_id", "string", "REC-2026-NNNNNN", unique=True, pattern="rec_id"),
        F("plant_id", "string", "Plant", fk="plant.plant_id"),
        F("scope_type", "string", "Target entity type", allowed=("plant", "machine", "meter")),
        F("scope_id", "string", "Target entity id"),
        F("rule_id", "string", "Rule that produced it (docs/RULES.md)"),
        F("title", "string", "Action"),
        F("owner_role", "string", "Persona expected to act",
          allowed=("plant_operator", "maintenance_engineer", "production_planner", "ot_it_admin")),
        F("baseline_metric", "string", "What was measured"),
        F("baseline_value", "decimal", "Measured baseline over the analysis window"),
        F("baseline_unit", "string", "Unit of baseline_value"),
        F("baseline_window_start_utc", "datetime", "Analysis window start"),
        F("baseline_window_end_utc", "datetime", "Analysis window end"),
        F("expected_savings_kwh_yr", "decimal", "Annualised energy savings", unit="kWh/yr", rule=">= 0"),
        F("expected_savings_kw", "decimal", "Peak demand reduction", unit="kW", rule=">= 0"),
        F("expected_savings_cost_yr", "decimal", "Annualised cost savings", unit="currency/yr", rule=">= 0"),
        F("currency", "string", "Plant currency", allowed=("INR", "USD", "EUR")),
        F("expected_savings_usd_yr", "decimal", "Annualised savings in USD (fixed FX)", unit="USD/yr"),
        F("savings_formula", "string", "How savings were computed"),
        F("confidence", "string", "Confidence band", allowed=("HIGH", "MEDIUM", "LOW")),
        F("evidence_ids", "string", "Semicolon list of finding ids"),
        F("status", "string", "Derived = last recommendation_event", allowed=REC_STATUS),
    ], kind="output"),
    T("finding", "Finding", "finding_id", "Analytics output: one detected exception or waste event.", [
        F("finding_id", "string", "FND-2026-NNNNNN", unique=True, pattern="finding_id"),
        F("issue_type", "string", "Detected issue type"),
        F("category", "string", "DATA_QUALITY or WASTE", allowed=("DATA_QUALITY", "WASTE")),
        F("plant_id", "string", "Plant", fk="plant.plant_id"),
        F("entity_type", "string", "Entity kind", allowed=("meter", "machine", "tariff", "reading", "plant")),
        F("entity_id", "string", "Entity id"),
        F("window_start_utc", "datetime", "Start"),
        F("window_end_utc", "datetime", "End"),
        F("rule_id", "string", "Detection rule"),
        F("decision", "string", "Action taken by the pipeline"),
        F("metric_value", "decimal", "Key measured quantity", required=False),
        F("metric_unit", "string", "Unit of metric_value", required=False),
        F("impact_kwh", "decimal", "Energy affected / wasted", required=False, unit="kWh"),
        F("owner_role", "string", "Persona", allowed=("plant_operator", "maintenance_engineer", "production_planner",
                                                     "ot_it_admin")),
        F("detail", "string", "Human-readable evidence"),
    ], kind="output"),
]

BY_NAME = {t.name: t for t in TABLES}
GENERATED = [t.name for t in TABLES if t.kind != "output"]

GROUND_TRUTH_FIELDS = [
    F("gt_id", "string", "GT-2026-NNNNN", unique=True, pattern="gt_id"),
    F("issue_type", "string", "Injected issue / scenario"),
    F("category", "string", "DATA_ERROR | TELEMETRY_GAP | WASTE_SCENARIO"),
    F("plant_id", "string", "Plant"),
    F("entity_type", "string", "meter | machine | tariff | reading"),
    F("entity_id", "string", "Affected entity"),
    F("window_start_utc", "datetime", "Start of affected window"),
    F("window_end_utc", "datetime", "End (exclusive)"),
    F("impact_kwh", "decimal", "True energy affected", unit="kWh"),
    F("params", "string", "JSON of injection parameters"),
    F("expected_detection", "string", "Rule expected to catch it"),
    F("expected_decision", "string", "Decision the pipeline should take"),
]
