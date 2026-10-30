"""Tariff costing.

R-TZ-01: TOU windows are published in the plant's local prevailing time. A tariff whose `timezone` differs
from the plant timezone is flagged; costing always evaluates windows in plant-local time (DST aware) and the
finding quantifies what the mis-labelled timezone would have cost.
R-COST-01: every interval must match exactly one window of the tariff version effective on its local date.
R-COST-02: demand charge = max 15-min kW of the incomer per local calendar month x rate, pro-rated by days covered.
"""
import calendar

import numpy as np
import pandas as pd

from .. import config, tariffs as tl


def run(cr, d, F):
    plants, tariffs, windows = d["plant"], d["tariff"], d["tariff_window"]
    cr["tariff_id"] = None
    cr["window_id"] = None
    cr["period"] = None
    cr["rate"] = np.nan
    cr["cost"] = np.nan
    coverage = []
    for p in plants.itertuples():
        pt = tariffs[tariffs["plant_id"] == p.plant_id]
        sel = cr["plant_id"] == p.plant_id
        lk = tl.lookup(cr.loc[sel, "ts_utc"], pt, windows, p.timezone)
        lk.index = cr.index[sel]
        for c in ("tariff_id", "window_id", "period"):
            cr.loc[sel, c] = lk[c]
        cr.loc[sel, "rate"] = lk["rate_per_kwh"]
        cr.loc[sel, "cost"] = cr.loc[sel, "interval_kwh"] * lk["rate_per_kwh"]
        coverage.append({"plant_id": p.plant_id, "intervals": int(sel.sum()),
                         "exactly_one_window": int((lk["match_count"] == 1).sum()),
                         "unpriced": int((lk["match_count"] == 0).sum()),
                         "ambiguous": int((lk["match_count"] > 1).sum())})

        for t in pt[pt["timezone"] != p.timezone].itertuples():
            m = sel & (cr["tariff_id"] == t.tariff_id) & (cr["meter_type"] == "MAIN")
            if not m.any():
                continue
            naive = tl.lookup(cr.loc[m, "ts_utc"], pt[pt["tariff_id"] == t.tariff_id], windows, t.timezone)
            naive_cost = float(np.nansum(cr.loc[m, "interval_kwh"].to_numpy() * naive["rate_per_kwh"].to_numpy()))
            correct = float(cr.loc[m, "cost"].sum())
            moved = float(cr.loc[m, "interval_kwh"][cr.loc[m, "period"].to_numpy() != naive["period"].to_numpy()].sum())
            F.add("TARIFF_TZ_MISMATCH", "DATA_QUALITY", p.plant_id, "tariff", t.tariff_id, cr.loc[m, "ts_utc"].min(),
                  cr.loc[m, "ts_utc"].max() + pd.Timedelta(minutes=15), "R-TZ-01",
                  "REINTERPRET_WINDOWS_IN_PLANT_LOCAL_TIME", "ot_it_admin",
                  f"Tariff recorded in {t.timezone} but plant runs on {p.timezone}. Costed in plant-local time: "
                  f"{correct:,.2f} {t.currency}; the recorded timezone would give {naive_cost:,.2f} {t.currency} "
                  f"({naive_cost - correct:+,.2f}); {moved:,.0f} kWh would land in the wrong TOU period",
                  metric_value=naive_cost - correct, metric_unit=t.currency, impact_kwh=moved)

    # monthly incomer bill
    bills = []
    main = cr[cr["meter_type"] == "MAIN"]
    for p in plants.itertuples():
        g = main[main["plant_id"] == p.plant_id].copy()
        g["month"] = g["ts_utc"].dt.tz_convert(p.timezone).dt.strftime("%Y-%m")
        g["ldate"] = g["ts_utc"].dt.tz_convert(p.timezone).dt.date
        for month, mg in g.groupby("month"):
            pk = mg.loc[mg["avg_kw"].idxmax()]
            tar = tariffs[tariffs["tariff_id"] == pk["tariff_id"]].iloc[0]
            y, mo = (int(x) for x in month.split("-"))
            days_cov = mg["ldate"].nunique()
            prorate = len(mg) / (calendar.monthrange(y, mo)[1] * 96)  # share of the month's 15-min intervals covered
            demand = float(pk["avg_kw"]) * tar.demand_charge_per_kw_month * prorate
            energy = float(mg["cost"].sum())
            row = {"plant_id": p.plant_id, "month": month, "local_days_touched": days_cov, "kwh": round(mg["interval_kwh"].sum(), 1),
                   "energy_cost": round(energy, 2), "peak_kw": round(float(pk["avg_kw"]), 1),
                   "peak_ts_utc": pk["ts_utc"], "peak_period": pk["period"],
                   "demand_rate": tar.demand_charge_per_kw_month, "demand_prorate": round(prorate, 4),
                   "demand_charge": round(demand, 2), "total_cost": round(energy + demand, 2), "currency": p.currency}
            for per in ("PEAK", "SHOULDER", "NORMAL", "OFFPEAK"):
                row[f"kwh_{per.lower()}"] = round(float(mg.loc[mg["period"] == per, "interval_kwh"].sum()), 1)
            row["total_cost_usd"] = round(row["total_cost"] * config.FX_TO_USD[p.currency], 2)
            bills.append(row)
    return pd.DataFrame(bills), pd.DataFrame(coverage)
