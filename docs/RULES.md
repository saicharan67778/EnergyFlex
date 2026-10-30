# Business, labelling and detection rules

Each threshold lives in the code next to its rule; the module is named in each section heading. The generator
produces ground-truth labels from these same documented rules, never by random assignment.

## Generation rules (`energyflex/generate`)
| Area | Rule |
|---|---|
| Hierarchy | Per plant: `MTR-<plant>-001` MAIN incomer → SUB `002–004` (one production machine each) and `005` utilities (compressor + HVAC). The bridge `meter_machine_map` is effective-dated; the PLT02 machine swap closes one row and opens another, so history is kept. |
| Cadence/units | 15-min intervals; `interval_kwh` (kWh), `avg_kw` = kWh × 4 (kW), cumulative `register_kwh`. All timestamps are UTC. |
| Shifts | A 06–14, B 14–22, C 22–06 local; Mon–Fri, plus Saturday A where configured. Holidays become `HOLIDAY` instances with no batches. UTC bounds are DST-aware. |
| Batches | 2,000 batches over (machine, shift) slots, weighted A > B > C, at most 3 per slot, run back-to-back with 15–50 min changeovers. 1.5 % CANCELLED, 2 % SCRAPPED. Status = last lifecycle event. |
| Machine states | Warm-up IDLE ≤ 60 min; RUNNING during batches; IDLE through changeovers ≤ 45 min; 20-min cooldown, then STANDBY; OFF outside staffed shifts; MAINTENANCE during work orders. |
| Power | RUNNING = rated × product load factor (±2.5 %) × drift × 1.2 inrush (first 10 min). IDLE/STANDBY/OFF use nameplate fractions. The compressor follows production; HVAC follows degree-hours and occupancy. Main = Σ subs × 1.018 + lighting. |
| Tariffs | Windows are in plant local time; each tariff covers 7 × 24 h exactly once; versions are effective-dated (PLT02 changes on 2026-03-01). Demand charge applies to the monthly max 15-min kW. |

## Labelled scenarios and edge cases (`ground_truth.csv`)
| issue_type | How it is produced | Expected decision |
|---|---|---|
| HIGH_IDLE_CONSUMPTION | Auto-standby bypassed (6 % of staffed shifts) or machine left idling overnight (2.5 %); labelled when a continuous IDLE run ≥ 75 min contains ≥ 30 scenario minutes | RECOMMEND_AUTO_STANDBY |
| PEAK_DEMAND_SPIKE | 1–2 intervals at 1.35–1.6 × nameplate inside a PEAK tariff window | RECOMMEND_STAGGERED_START |
| INTENSITY_DRIFT | Running kW ramps to ×1.25 over 14 days and is repaired by a CORRECTIVE work order (full scale also has one unrepaired drift) | RAISE_CORRECTIVE_MAINTENANCE |
| OFF_SHIFT_WASTE | Compressed-air leak (+16 % of rated, persistent), or HVAC left in occupied mode for a weekend | RECOMMEND_LEAK_SURVEY / RECOMMEND_BMS_SCHEDULE_LOCK |
| METER_GAP | 1–16 h of missing sub-meter rows; the register keeps counting | BACKFILL_FROM_REGISTER_DELTA |
| REGISTER_INTERVAL_MISMATCH | Register jump (+500–5,000 kWh) or 3 % register drift | USE_INTERVAL_SUM_AND_RAISE_METER_TICKET |
| HIERARCHY_TOTAL_MISMATCH | Sub-meter CT ratio ×2 (interval and register both scaled) | QUARANTINE_SUBMETER_AND_VERIFY_CT |
| UNIT_KW_AS_KWH | `interval_kwh` holds the kW value for 6–36 h | DIVIDE_BY_4_AND_FIX_CONFIG |
| DUPLICATE_READING | 0.2 % of rows re-sent; half exact copies, half with a value off by ±1–5 % | DROP_LATER_COPY / KEEP_REGISTER_CONSISTENT_ROW |
| MACHINE_OUTSIDE_HIERARCHY | Readings tagged with a machine from another meter, or with the old machine after the swap | REATTRIBUTE_TO_MAPPED_MACHINE |
| TARIFF_TZ_MISMATCH | One tariff is recorded with timezone `UTC` although its windows are plant-local | REINTERPRET_WINDOWS_IN_PLANT_LOCAL_TIME |

Injection windows never overlap each other or a scenario window on the same meter, so unrelated rows are never touched.

## Detection rules (`energyflex/analytics`)
| Rule | Logic | Owner |
|---|---|---|
| R-DUP-01 | Same `reading_id` more than once → for exact copies keep the first ingested row; for conflicting copies keep the row whose kWh equals the register delta | OT/IT |
| R-UNIT-01 | `interval_kwh == avg_kw` (±0.002) → kW was written into the kWh field; corrected kWh = kW / 4 | OT/IT |
| R-GAP-01 | Non-contiguous timestamps → gap energy = Δregister − next interval; backfill shaped on (incomer − other sub-meters) | OT/IT |
| R-REG-01 | Contiguous rows with abs(Δregister − kWh) > max(0.01 kWh, 0.5 %) → mismatch (JUMP if 1 interval, else DRIFT); interval sums are authoritative | OT/IT |
| R-HIER-01 | Σ sub > incomer (beyond 1 % + 2 kW), or the residual falls below a robust model (lighting by occupancy + load-proportional losses) by more than max(4·MAD, 6 kW) → the sub-meter that best explains it is quarantined for the window | OT/IT |
| R-HIER-02 | Reading tag not mapped to its meter at that time in the bridge → re-attributed to the mapped machine | OT/IT |
| R-TZ-01 | `tariff.timezone ≠ plant.timezone` → cost in plant-local time; the finding reports the cost delta and the kWh that would land in the wrong period | OT/IT |
| R-COST-01/02 | Each interval is priced by exactly one window of the version effective on its local date; demand charge = monthly max kW × rate × share of the month covered | Planner |
| R-IDLE-01 | Machine meter within [0.7, 1.4] × idle_kw, no batch overlap, not quarantined, for ≥ 5 intervals; waste = (kW − standby) after a 30-min grace period | Operator |
| R-PEAK-01 | Machine meter > 1.3 × nameplate (nameplate + inrush allowance) for ≤ 4 intervals | Planner |
| R-INT-01 | kWh per produced unit ÷ (machine, product) baseline (median over the baseline window); flagged when the rolling median of 5 batches > 1.10 | Maintenance |
| R-OFF-01 | Utilities off-shift kWh vs a piecewise degree-hour model with non-negative slopes, fitted on the baseline window; flag days > 1.4 × expected and > 60 kWh excess; ≥ 4 days = structural (leak), otherwise a schedule override | Maintenance / OT/IT |

Baseline window = the first `max(3, min(14, days // 3))` days.

## Recommendation rules (`recommend.py`)
| Rule | Savings formula |
|---|---|
| R-REC-IDLE | 0.85 × idle-above-standby kWh × 365/days; cost at each interval's TOU rate |
| R-REC-PEAK | mean monthly (peak kW − peak kW without spike intervals) × demand rate × 12 |
| R-REC-SHIFT | 0.5 × min(PEAK batch kWh, free non-PEAK staffed capacity) × (PEAK − staffed non-PEAK rate) × 365/days; skipped when a plant has no non-PEAK staffed hours |
| R-REC-MAINT | Ongoing drift: (ratio − 1)/ratio × last-14-day machine kWh × 365/14. Repaired drift: the episode's excess kWh (assumes one recurrence per year) |
| R-REC-OFF | Leak: 0.8 × excess kWh/day × 365. Override: excess per episode × 12 per year |

Lifecycle: PROPOSED → ACCEPTED or REJECTED; ACCEPTED → IMPLEMENTED → VERIFIED (append-only `recommendation_events.csv`).
