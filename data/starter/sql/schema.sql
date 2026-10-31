-- Generated from energyflex/schema.py. Portable across PostgreSQL and SQLite.

CREATE TABLE plant (
  plant_id VARCHAR(160) PRIMARY KEY,
  plant_name VARCHAR(160) NOT NULL,
  city VARCHAR(160) NOT NULL,
  country_code VARCHAR(160) NOT NULL,
  timezone VARCHAR(160) NOT NULL,
  currency VARCHAR(160) NOT NULL,
  latitude NUMERIC(16,3) NOT NULL,
  longitude NUMERIC(16,3) NOT NULL,
  status VARCHAR(160) NOT NULL
);

CREATE TABLE meter (
  meter_id VARCHAR(160) PRIMARY KEY,
  plant_id VARCHAR(160) NOT NULL,
  parent_meter_id VARCHAR(160),
  meter_type VARCHAR(160) NOT NULL,
  measured_scope VARCHAR(160) NOT NULL,
  serial_no VARCHAR(160) NOT NULL UNIQUE,
  source_system VARCHAR(160) NOT NULL,
  energy_unit VARCHAR(160) NOT NULL,
  demand_unit VARCHAR(160) NOT NULL,
  sampling_interval_min INTEGER NOT NULL,
  ct_ratio VARCHAR(160) NOT NULL,
  installed_at TIMESTAMPTZ NOT NULL,
  status VARCHAR(160) NOT NULL,
  FOREIGN KEY (plant_id) REFERENCES plant(plant_id),
  FOREIGN KEY (parent_meter_id) REFERENCES meter(meter_id)
);

CREATE TABLE machine (
  machine_id VARCHAR(160) PRIMARY KEY,
  plant_id VARCHAR(160) NOT NULL,
  machine_type VARCHAR(160) NOT NULL,
  machine_name VARCHAR(160) NOT NULL,
  is_production BOOLEAN NOT NULL,
  rated_kw NUMERIC(16,3) NOT NULL,
  idle_kw NUMERIC(16,3) NOT NULL,
  standby_kw NUMERIC(16,3) NOT NULL,
  commissioned_at TIMESTAMPTZ NOT NULL,
  decommissioned_at TIMESTAMPTZ,
  status VARCHAR(160) NOT NULL,
  FOREIGN KEY (plant_id) REFERENCES plant(plant_id)
);

CREATE TABLE meter_machine_map (
  map_id VARCHAR(160) PRIMARY KEY,
  meter_id VARCHAR(160) NOT NULL,
  machine_id VARCHAR(160) NOT NULL,
  allocation_pct NUMERIC(16,3) NOT NULL,
  effective_from TIMESTAMPTZ NOT NULL,
  effective_to TIMESTAMPTZ,
  FOREIGN KEY (meter_id) REFERENCES meter(meter_id),
  FOREIGN KEY (machine_id) REFERENCES machine(machine_id)
);

CREATE TABLE shift (
  shift_id VARCHAR(160) PRIMARY KEY,
  plant_id VARCHAR(160) NOT NULL,
  shift_code VARCHAR(160) NOT NULL,
  start_local VARCHAR(5) NOT NULL,
  end_local VARCHAR(5) NOT NULL,
  crosses_midnight BOOLEAN NOT NULL,
  working_days VARCHAR(160) NOT NULL,
  FOREIGN KEY (plant_id) REFERENCES plant(plant_id)
);

CREATE TABLE shift_instance (
  shift_instance_id VARCHAR(160) PRIMARY KEY,
  shift_id VARCHAR(160) NOT NULL,
  plant_id VARCHAR(160) NOT NULL,
  business_date DATE NOT NULL,
  start_utc TIMESTAMPTZ NOT NULL,
  end_utc TIMESTAMPTZ NOT NULL,
  calendar_status VARCHAR(160) NOT NULL,
  FOREIGN KEY (shift_id) REFERENCES shift(shift_id),
  FOREIGN KEY (plant_id) REFERENCES plant(plant_id)
);

CREATE TABLE tariff (
  tariff_id VARCHAR(160) PRIMARY KEY,
  plant_id VARCHAR(160) NOT NULL,
  utility_name VARCHAR(160) NOT NULL,
  tariff_version INTEGER NOT NULL,
  currency VARCHAR(160) NOT NULL,
  timezone VARCHAR(160) NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE,
  demand_charge_per_kw_month NUMERIC(16,3) NOT NULL,
  FOREIGN KEY (plant_id) REFERENCES plant(plant_id)
);

CREATE TABLE tariff_window (
  window_id VARCHAR(160) PRIMARY KEY,
  tariff_id VARCHAR(160) NOT NULL,
  period VARCHAR(160) NOT NULL,
  days_of_week VARCHAR(160) NOT NULL,
  start_local VARCHAR(5) NOT NULL,
  end_local VARCHAR(5) NOT NULL,
  rate_per_kwh NUMERIC(16,3) NOT NULL,
  FOREIGN KEY (tariff_id) REFERENCES tariff(tariff_id)
);

CREATE TABLE weather_observation (
  observation_id VARCHAR(160) PRIMARY KEY,
  plant_id VARCHAR(160) NOT NULL,
  ts_utc TIMESTAMPTZ NOT NULL,
  temp_c NUMERIC(16,3) NOT NULL,
  rel_humidity_pct NUMERIC(16,3) NOT NULL,
  wind_speed_ms NUMERIC(16,3) NOT NULL,
  condition VARCHAR(160) NOT NULL,
  source VARCHAR(160) NOT NULL,
  FOREIGN KEY (plant_id) REFERENCES plant(plant_id)
);

CREATE TABLE production_batch (
  batch_id VARCHAR(160) PRIMARY KEY,
  plant_id VARCHAR(160) NOT NULL,
  machine_id VARCHAR(160) NOT NULL,
  shift_instance_id VARCHAR(160) NOT NULL,
  product_code VARCHAR(160) NOT NULL,
  unit_of_measure VARCHAR(160) NOT NULL,
  planned_start_utc TIMESTAMPTZ NOT NULL,
  planned_end_utc TIMESTAMPTZ NOT NULL,
  actual_start_utc TIMESTAMPTZ,
  actual_end_utc TIMESTAMPTZ,
  planned_units INTEGER NOT NULL,
  produced_units INTEGER NOT NULL,
  good_units INTEGER NOT NULL,
  scrap_units INTEGER NOT NULL,
  status VARCHAR(160) NOT NULL,
  FOREIGN KEY (plant_id) REFERENCES plant(plant_id),
  FOREIGN KEY (machine_id) REFERENCES machine(machine_id),
  FOREIGN KEY (shift_instance_id) REFERENCES shift_instance(shift_instance_id)
);

CREATE TABLE batch_status_event (
  batch_event_id VARCHAR(160) PRIMARY KEY,
  batch_id VARCHAR(160) NOT NULL,
  from_status VARCHAR(160),
  to_status VARCHAR(160) NOT NULL,
  event_ts TIMESTAMPTZ NOT NULL,
  actor_role VARCHAR(160) NOT NULL,
  FOREIGN KEY (batch_id) REFERENCES production_batch(batch_id)
);

CREATE TABLE maintenance_event (
  maintenance_id VARCHAR(160) PRIMARY KEY,
  machine_id VARCHAR(160) NOT NULL,
  plant_id VARCHAR(160) NOT NULL,
  maintenance_type VARCHAR(160) NOT NULL,
  reason VARCHAR(160) NOT NULL,
  opened_at TIMESTAMPTZ NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  closed_at TIMESTAMPTZ NOT NULL,
  raised_by_role VARCHAR(160) NOT NULL,
  downtime_min INTEGER NOT NULL,
  status VARCHAR(160) NOT NULL,
  FOREIGN KEY (machine_id) REFERENCES machine(machine_id),
  FOREIGN KEY (plant_id) REFERENCES plant(plant_id)
);

CREATE TABLE maintenance_status_event (
  maintenance_event_id VARCHAR(160) PRIMARY KEY,
  maintenance_id VARCHAR(160) NOT NULL,
  from_status VARCHAR(160),
  to_status VARCHAR(160) NOT NULL,
  event_ts TIMESTAMPTZ NOT NULL,
  FOREIGN KEY (maintenance_id) REFERENCES maintenance_event(maintenance_id)
);

CREATE TABLE machine_status_event (
  machine_event_id VARCHAR(160) PRIMARY KEY,
  machine_id VARCHAR(160) NOT NULL,
  from_status VARCHAR(160),
  to_status VARCHAR(160) NOT NULL,
  event_ts TIMESTAMPTZ NOT NULL,
  maintenance_id VARCHAR(160),
  FOREIGN KEY (machine_id) REFERENCES machine(machine_id),
  FOREIGN KEY (maintenance_id) REFERENCES maintenance_event(maintenance_id)
);

CREATE TABLE meter_status_event (
  meter_event_id VARCHAR(160) PRIMARY KEY,
  meter_id VARCHAR(160) NOT NULL,
  from_status VARCHAR(160),
  to_status VARCHAR(160) NOT NULL,
  event_ts TIMESTAMPTZ NOT NULL,
  note VARCHAR(160) NOT NULL,
  FOREIGN KEY (meter_id) REFERENCES meter(meter_id)
);

CREATE TABLE machine_state_interval (
  state_interval_id VARCHAR(160) PRIMARY KEY,
  machine_id VARCHAR(160) NOT NULL,
  state VARCHAR(160) NOT NULL,
  start_utc TIMESTAMPTZ NOT NULL,
  end_utc TIMESTAMPTZ NOT NULL,
  duration_min INTEGER NOT NULL,
  source VARCHAR(160) NOT NULL,
  FOREIGN KEY (machine_id) REFERENCES machine(machine_id)
);

CREATE TABLE energy_reading (
  ingest_seq INTEGER PRIMARY KEY,
  reading_id VARCHAR(160) NOT NULL,
  meter_id VARCHAR(160) NOT NULL,
  machine_id VARCHAR(160),
  ts_utc TIMESTAMPTZ NOT NULL,
  interval_kwh NUMERIC(16,3) NOT NULL,
  avg_kw NUMERIC(16,3) NOT NULL,
  register_kwh NUMERIC(16,3) NOT NULL,
  unit VARCHAR(160) NOT NULL,
  source_system VARCHAR(160) NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL,
  FOREIGN KEY (meter_id) REFERENCES meter(meter_id),
  FOREIGN KEY (machine_id) REFERENCES machine(machine_id)
);
CREATE INDEX ix_energy_reading_natural ON energy_reading(reading_id);
CREATE INDEX ix_energy_reading_meter_ts ON energy_reading(meter_id, ts_utc);
