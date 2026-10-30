"""Central configuration: seed, scale profiles, plant/machine templates, tariffs and scenario rates.

Everything the generator needs to be deterministic lives here. Starter and full datasets use the
same code path; only the SCALES profile differs.
"""

SEED = 20261022
START_UTC = "2026-01-05T00:00:00Z"  # a Monday; every timestamp is stored in UTC
INTERVAL_MIN = 15
ID_YEAR = 2026

SCALES = {
    # 2 plants x 5 meters = 10 meters, one week
    "starter": {"n_plants": 2, "days": 7, "n_batches": 150},
    # 4 plants x 5 meters = 20 meters, 90 days x 96 readings/day
    "full": {"n_plants": 4, "days": 90, "n_batches": 2000},
}

# Fixed, documented FX used only to roll local-currency savings up to one reporting currency.
REPORTING_CURRENCY = "USD"
FX_TO_USD = {"INR": 0.012, "USD": 1.0, "EUR": 1.08}

SHIFT_TEMPLATES = {
    "A": ("06:00", "14:00"),
    "B": ("14:00", "22:00"),
    "C": ("22:00", "06:00"),
}

# Machine type library. Fractions are of rated (nameplate) kW. Product rates are units per running hour.
MACHINE_TYPES = {
    "INDUCTION_FURNACE": {"production": True, "idle_frac": 0.42, "standby_frac": 0.10, "off_frac": 0.012,
                          "load_factor": (0.78, 0.92),
                          "products": {"BILLET-42CRMO4": (38, "pcs"), "BILLET-C45": (30, "pcs")}},
    "FORGING_PRESS": {"production": True, "idle_frac": 0.30, "standby_frac": 0.07, "off_frac": 0.010,
                      "load_factor": (0.70, 0.88),
                      "products": {"GEAR-BLANK-40": (55, "pcs"), "SHAFT-BLANK-25": (42, "pcs")}},
    "CNC_CELL": {"production": True, "idle_frac": 0.25, "standby_frac": 0.06, "off_frac": 0.010,
                 "load_factor": (0.62, 0.85),
                 "products": {"FLANGE-M12": (22, "pcs"), "HOUSING-H7": (14, "pcs")}},
    "INJECTION_MOLDER": {"production": True, "idle_frac": 0.33, "standby_frac": 0.08, "off_frac": 0.010,
                         "load_factor": (0.68, 0.90),
                         "products": {"CAP-28MM": (1800, "pcs"), "CLIP-PA6": (950, "pcs")}},
    "EXTRUDER": {"production": True, "idle_frac": 0.38, "standby_frac": 0.09, "off_frac": 0.010,
                 "load_factor": (0.72, 0.90),
                 "products": {"PIPE-32MM": (240, "m"), "PROFILE-W12": (160, "m")}},
    "PAINT_OVEN": {"production": True, "idle_frac": 0.45, "standby_frac": 0.10, "off_frac": 0.012,
                   "load_factor": (0.75, 0.92),
                   "products": {"PANEL-RAL7035": (60, "pcs"), "BRACKET-RAL9005": (110, "pcs")}},
    "AIR_COMPRESSOR": {"production": False, "idle_frac": 0.22, "standby_frac": 0.22, "off_frac": 0.22,
                       "load_factor": (0.55, 0.55), "products": {}},
    "HVAC_AHU": {"production": False, "idle_frac": 0.04, "standby_frac": 0.04, "off_frac": 0.04,
                 "load_factor": (1.0, 1.0), "products": {}},
}

ALL_DAYS = "MON,TUE,WED,THU,FRI,SAT,SUN"
WEEKDAYS = "MON,TUE,WED,THU,FRI"
WEEKEND = "SAT,SUN"


def _india_windows(off, normal, peak):
    return [("OFFPEAK", ALL_DAYS, "00:00", "06:00", off), ("NORMAL", ALL_DAYS, "06:00", "09:00", normal),
            ("PEAK", ALL_DAYS, "09:00", "12:00", peak), ("NORMAL", ALL_DAYS, "12:00", "18:00", normal),
            ("PEAK", ALL_DAYS, "18:00", "22:00", peak), ("OFFPEAK", ALL_DAYS, "22:00", "24:00", off)]


def _us_windows(off, shoulder, peak):
    return [("OFFPEAK", WEEKDAYS, "00:00", "07:00", off), ("SHOULDER", WEEKDAYS, "07:00", "14:00", shoulder),
            ("PEAK", WEEKDAYS, "14:00", "21:00", peak), ("OFFPEAK", WEEKDAYS, "21:00", "24:00", off),
            ("OFFPEAK", WEEKEND, "00:00", "24:00", off)]


def _de_windows(nt, ht):
    return [("OFFPEAK", WEEKDAYS, "00:00", "06:00", nt), ("PEAK", WEEKDAYS, "06:00", "22:00", ht),
            ("OFFPEAK", WEEKDAYS, "22:00", "24:00", nt), ("OFFPEAK", WEEKEND, "00:00", "24:00", nt)]


# Plants in the order they are included by scale (starter = first two: one IST, one US-Central w/ DST).
PLANTS = [
    {"plant_id": "PLT01", "name": "Pune Forge Works", "city": "Pune", "country": "IN",
     "timezone": "Asia/Kolkata", "currency": "INR", "lat": 18.52, "lon": 73.86,
     "shifts": ["A", "B", "C"], "saturday_shifts": ["A"], "holidays": ["2026-01-26"],
     "machines": [("INDUCTION_FURNACE", 260), ("FORGING_PRESS", 160), ("CNC_CELL", 55)],
     "compressor_kw": 90, "hvac_kw": 45, "lighting_kw": (32.0, 9.0),
     "climate": {"t_start": 22.0, "t_end": 29.5, "diurnal": 7.5, "rh": 45, "noise": 1.2},
     "tariffs": [{"from": "2026-01-01", "to": None, "utility": "State DISCOM HT-I (synthetic)",
                  "demand": 450.0, "windows": _india_windows(6.20, 7.50, 8.90)}]},
    {"plant_id": "PLT02", "name": "Houston Fabrication", "city": "Houston", "country": "US",
     "timezone": "America/Chicago", "currency": "USD", "lat": 29.76, "lon": -95.37,
     "shifts": ["A", "B"], "saturday_shifts": [], "holidays": [],
     "machines": [("CNC_CELL", 65), ("PAINT_OVEN", 190), ("FORGING_PRESS", 140)],
     "compressor_kw": 75, "hvac_kw": 70, "lighting_kw": (28.0, 7.0),
     "climate": {"t_start": 12.0, "t_end": 22.0, "diurnal": 6.0, "rh": 70, "noise": 2.5},
     "tariffs": [{"from": "2026-01-01", "to": "2026-02-28", "utility": "Gulf Coast Retail TOU-GS (synthetic)",
                  "demand": 14.50, "windows": _us_windows(0.072, 0.098, 0.165)},
                 {"from": "2026-03-01", "to": None, "utility": "Gulf Coast Retail TOU-GS (synthetic)",
                  "demand": 15.20, "windows": _us_windows(0.075, 0.104, 0.178)}]},
    {"plant_id": "PLT03", "name": "Chennai Polymer Plant", "city": "Chennai", "country": "IN",
     "timezone": "Asia/Kolkata", "currency": "INR", "lat": 13.08, "lon": 80.27,
     "shifts": ["A", "B"], "saturday_shifts": ["A"], "holidays": ["2026-01-26"],
     "machines": [("INJECTION_MOLDER", 130), ("INJECTION_MOLDER", 110), ("EXTRUDER", 150)],
     "compressor_kw": 110, "hvac_kw": 60, "lighting_kw": (26.0, 8.0),
     "climate": {"t_start": 25.5, "t_end": 30.5, "diurnal": 5.0, "rh": 75, "noise": 0.9},
     "tariffs": [{"from": "2026-01-01", "to": None, "utility": "State DISCOM HT-II (synthetic)",
                  "demand": 475.0, "windows": _india_windows(6.40, 7.70, 9.20)}]},
    {"plant_id": "PLT04", "name": "Stuttgart Components", "city": "Stuttgart", "country": "DE",
     "timezone": "Europe/Berlin", "currency": "EUR", "lat": 48.78, "lon": 9.18,
     "shifts": ["A", "B"], "saturday_shifts": [], "holidays": ["2026-04-03"],
     "machines": [("CNC_CELL", 70), ("INDUCTION_FURNACE", 220), ("INJECTION_MOLDER", 120)],
     "compressor_kw": 90, "hvac_kw": 80, "lighting_kw": (30.0, 8.0),
     "climate": {"t_start": 0.5, "t_end": 10.0, "diurnal": 6.0, "rh": 78, "noise": 3.0},
     "tariffs": [{"from": "2026-01-01", "to": None, "utility": "Stadtwerke Gewerbe HT/NT (synthetic)",
                  "demand": 11.00, "windows": _de_windows(0.17, 0.24)}]},
]

# Machine swap: shows bridge-table effective dating and machine lifecycle. New unit is ~10% more efficient.
SWAP = {"plant_index": 1, "machine_no": 3, "new_rated_kw": 150, "efficiency": 0.90}

# Behavioural thresholds used by the generator (documented in docs/RULES.md).
COOLDOWN_IDLE_MIN = 20       # normal idle after a batch before auto-standby
PREHEAT_IDLE_MIN = 10        # normal idle before the next batch
CHANGEOVER_MAX_MIN = 45      # gaps up to this stay idle (changeover)
INRUSH_MIN = 10
INRUSH_FACTOR = 1.20
UNMETERED_LOSS_FRAC = 0.018  # distribution / transformer losses seen by the main meter only

def baseline_days(days):
    """Leading clean window the analytics use as a baseline; scenarios that need a baseline start after it."""
    return max(3, min(14, days // 3))


# Scenario rates (real behaviour, labelled in ground truth). Counts scale with days.
SCENARIO = {
    "excess_idle_shift_prob": 0.06,   # machine-shift where auto-standby is bypassed
    "overnight_idle_prob": 0.025,     # machine left idling after its last shift
    "spikes_per_plant_per_30d": 1.5,  # coincident heat-up spikes in a tariff peak window
    "drift_frac_start": 0.25,         # intensity drift #1 starts at 25% of the period
    "leak_frac_start": 0.45,          # compressed-air leak develops at 45% of the period
    "gaps_per_meter_per_30d": 0.5,
}

# Data-error injection rates (edge cases, labelled in ground truth).
EDGE = {
    "register_jumps_per_30d": 1.0,
    "register_drifts_per_30d": 0.7,
    "unit_windows_per_30d": 1.0,
    "ct_windows_per_30d": 0.7,
    "tag_windows_per_30d": 1.0,
    "duplicate_rate": 0.002,
}
