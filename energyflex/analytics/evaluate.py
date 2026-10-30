"""Score findings against ground truth (precision / recall / F1 per issue type, decision accuracy, impact error)."""
import numpy as np
import pandas as pd

TOL = pd.Timedelta(minutes=15)


def _overlap(f, g):
    return (f.window_start_utc < g.window_end_utc + TOL) and (g.window_start_utc < f.window_end_utc + TOL)


def score(findings, gt):
    types = sorted(set(gt["issue_type"]) | set(findings["issue_type"]))
    rows, matches = [], []
    for t in types:
        G = gt[gt["issue_type"] == t]
        Fd = findings[findings["issue_type"] == t]
        g_hit, f_hit = set(), set()
        loose_hit = set()
        for f in Fd.itertuples():
            for g in G.itertuples():
                if not _overlap(f, g):
                    continue
                if f.plant_id == g.plant_id:
                    loose_hit.add(g.gt_id)
                if f.entity_id == g.entity_id:
                    g_hit.add(g.gt_id)
                    f_hit.add(f.finding_id)
                    matches.append({"issue_type": t, "gt_id": g.gt_id, "finding_id": f.finding_id,
                                    "decision_match": f.decision == g.expected_decision,
                                    "gt_impact_kwh": g.impact_kwh, "found_impact_kwh": f.impact_kwh})
        p = len(f_hit) / len(Fd) if len(Fd) else (1.0 if not len(G) else 0.0)
        r = len(g_hit) / len(G) if len(G) else 1.0
        rows.append({"issue_type": t, "ground_truth": len(G), "findings": len(Fd), "gt_detected": len(g_hit),
                     "gt_detected_plant_window": len(loose_hit), "true_positive_findings": len(f_hit),
                     "precision": round(p, 3), "recall": round(r, 3),
                     "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0})
    per_type = pd.DataFrame(rows)
    m = pd.DataFrame(matches)
    if not m.empty:
        dec = m.drop_duplicates("gt_id").groupby("issue_type")["decision_match"].mean().round(3)
        per_type["decision_accuracy"] = per_type["issue_type"].map(dec)
        m_imp = m[m["gt_impact_kwh"] > 0]
        imp = m_imp.drop_duplicates("gt_id").groupby("issue_type").apply(
            lambda x: float(np.abs(x["found_impact_kwh"].sum() - x["gt_impact_kwh"].sum()) / max(x["gt_impact_kwh"].sum(), 1e-9)),
            include_groups=False)
        per_type["impact_rel_error"] = per_type["issue_type"].map(imp).round(3)
    tot_tp = per_type["true_positive_findings"].sum()
    overall = {"macro_precision": round(per_type["precision"].mean(), 3), "macro_recall": round(per_type["recall"].mean(), 3),
               "macro_f1": round(per_type["f1"].mean(), 3),
               "micro_precision": round(tot_tp / max(per_type["findings"].sum(), 1), 3),
               "micro_recall": round(per_type["gt_detected"].sum() / max(per_type["ground_truth"].sum(), 1), 3)}
    return per_type, m, overall
