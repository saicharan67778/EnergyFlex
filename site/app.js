/* EnergyFlex static dashboard. Reads data/dashboard.json produced by `python cli.py build-site --scale full`. */
(function () {
  "use strict";
  let D = null;
  const charts = {};
  const $ = (s) => document.querySelector(s);
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fmt = (v, d = 0) => (v === null || v === undefined || v === "" || isNaN(v)) ? "—" :
    Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const day = (s) => String(s).slice(0, 16).replace("T", " ");
  const PERIODS = ["OFFPEAK", "SHOULDER", "NORMAL", "PEAK"];          // fixed identity order
  const PERIOD_VAR = { OFFPEAK: "--s1", SHOULDER: "--s3", NORMAL: "--s4", PEAK: "--s2" };
  const ROLE = { plant_operator: "Plant operator", maintenance_engineer: "Maintenance / quality engineer",
    production_planner: "Production planner", ot_it_admin: "OT/IT admin" };
  const plantVar = (pid) => `--s${D.plants.findIndex((p) => p.plant_id === pid) + 1}`;
  const plantName = (pid) => (D.plants.find((p) => p.plant_id === pid) || {}).plant_name || pid;
  const state = { operator: null, engineer: null, planner: null };

  function table(el, cols, rows) {
    const head = "<tr>" + cols.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.label)}</th>`).join("") + "</tr>";
    const body = rows.map((r) => "<tr>" + cols.map((c) => {
      const v = c.render ? c.render(r) : esc(r[c.key]);
      return `<td class="${c.num ? "num" : ""}">${v}</td>`;
    }).join("") + "</tr>").join("");
    el.innerHTML = `<thead>${head}</thead><tbody>${body || `<tr><td colspan="${cols.length}" class="hint">No rows</td></tr>`}</tbody>`;
  }

  function baseOpts(extra = {}) {
    const text = css("--text-2"), grid = css("--grid");
    return Object.assign({
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "top", align: "start", labels: { color: text, boxWidth: 10, boxHeight: 10, usePointStyle: true } },
        tooltip: { backgroundColor: css("--surface"), titleColor: css("--text"), bodyColor: css("--text-2"),
          borderColor: css("--border"), borderWidth: 1, padding: 8 },
      },
      scales: {
        x: { ticks: { color: text, maxRotation: 0, autoSkipPadding: 18 }, grid: { display: false }, border: { color: grid } },
        y: { ticks: { color: text }, grid: { color: grid }, border: { display: false }, beginAtZero: true },
      },
    }, extra);
  }

  function draw(id, config) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(document.getElementById(id), config);
  }

  // ---------------- overview ----------------
  function overview() {
    const h = D.headline, ev = D.evaluation_overall, v = D.validation.summary;
    const kwh = D.daily.reduce((a, r) => a + r.kwh, 0);
    const k = [
      ["Energy at incomers", `${fmt(kwh / 1000, 0)} MWh`, `${D.plants.length} plants · ${h.days} days`],
      ["Energy + demand cost", `$${fmt(h.total_cost_usd)}`, "fixed FX to USD"],
      ["Expected savings", `$${fmt(h.annual_savings_usd)}/yr`, `${h.recommendations} recommendations`],
      ["Detection F1 (macro)", fmt(ev.macro_f1, 3), `recall ${fmt(ev.micro_recall, 3)} · precision ${fmt(ev.micro_precision, 3)}`],
      ["Validation checks", `${v.pass + v.expected_fail}/${v.checks}`, `${v.fail} unexplained failures`],
      ["Readings", fmt(h.raw_readings), `${fmt(h.curated_readings)} after cleaning`],
    ];
    $("#kpis").innerHTML = k.map(([l, val, f]) => `<div class="kpi"><div class="label">${l}</div><div class="value">${val}</div><div class="foot">${f}</div></div>`).join("");

    const a = D.acceptance;
    const items = [
      ["Energy totals reconcile", a.energy_totals_reconcile.pass,
        `${a.energy_totals_reconcile.meters_within_0_1pct ?? a.energy_totals_reconcile["meters_within_0.1pct"]}/${a.energy_totals_reconcile.meters} meters within 0.1 % of register; unmetered share ${a.energy_totals_reconcile.plant_unmetered_pct_range.join("–")} %`],
      ["Cost uses the correct tariff interval", a.cost_uses_correct_tariff_interval.pass,
        `${a.cost_uses_correct_tariff_interval.intervals_priced_by_exactly_one_window_pct}% of intervals priced by exactly one window (plant-local, DST aware); ${a.cost_uses_correct_tariff_interval.tariff_timezone_mismatches_corrected} timezone mismatch corrected`],
      ["Intensity normalised by output", a.intensity_normalized_by_output.pass,
        `${fmt(a.intensity_normalized_by_output.completed_batches)} completed batches with kWh/unit; ${a.intensity_normalized_by_output.with_baseline_pct}% have a (machine, product) baseline`],
      ["Recommendations cite baseline & savings", a.recommendations_cite_baseline_and_savings.pass,
        `${a.recommendations_cite_baseline_and_savings.with_baseline_value}/${a.recommendations_cite_baseline_and_savings.recommendations} with measured baseline, savings formula and evidence`],
    ];
    $("#acceptance").innerHTML = items.map(([t, ok, d]) => `<li><span class="icon ${ok ? "" : "fail"}">${ok ? "✓" : "✕"}</span><div><div>${t} — <b>${ok ? "pass" : "fail"}</b></div><div class="detail">${esc(d)}</div></div></li>`).join("");

    const rows = D.plants.map((p) => {
      const b = D.bills.filter((x) => x.plant_id === p.plant_id);
      const bal = D.plant_balance.find((x) => x.plant_id === p.plant_id) || {};
      return { ...p, kwh: b.reduce((s, x) => s + x.kwh, 0), peak: Math.max(...b.map((x) => x.peak_kw)),
        cost: b.reduce((s, x) => s + x.total_cost_usd, 0), unmetered: bal.unmetered_pct };
    });
    table($("#plantTable"), [
      { label: "Plant", render: (r) => `<span class="badge" style="border-color:var(${plantVar(r.plant_id)})">${esc(r.plant_id)}</span> ${esc(r.plant_name)}` },
      { label: "Timezone", key: "timezone" },
      { label: "MWh", num: true, render: (r) => fmt(r.kwh / 1000, 1) },
      { label: "Peak kW", num: true, render: (r) => fmt(r.peak, 0) },
      { label: "Cost USD", num: true, render: (r) => fmt(r.cost) },
      { label: "Unmetered %", num: true, render: (r) => fmt(r.unmetered, 1) },
    ], rows);

    const days = [...new Set(D.daily.map((r) => r.day))].sort();
    draw("dailyChart", { type: "line", data: { labels: days, datasets: D.plants.map((p) => {
      const m = Object.fromEntries(D.daily.filter((r) => r.plant_id === p.plant_id).map((r) => [r.day, r.kwh]));
      return { label: `${p.plant_id} ${p.city}`, data: days.map((d) => m[d] ?? null), borderColor: css(plantVar(p.plant_id)),
        backgroundColor: css(plantVar(p.plant_id)), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.2 };
    }) }, options: baseOpts() });
  }

  // ---------------- operator ----------------
  function operator() {
    const pid = state.operator;
    const pr = D.profile[pid];
    const hours = [...Array(24).keys()].map((h) => `${String(h).padStart(2, "0")}:00`);
    draw("profileChart", { type: "line", data: { labels: hours, datasets: [
      { label: "Weekday", data: pr.weekday_kw, borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 },
      { label: "Weekend", data: pr.weekend_kw, borderColor: css("--s2"), backgroundColor: css("--s2"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, borderDash: [5, 4] },
    ] }, options: baseOpts({ plugins: { ...baseOpts().plugins, tooltip: { ...baseOpts().plugins.tooltip,
      callbacks: { afterTitle: (it) => `Weekday tariff: ${pr.weekday_period[it[0].dataIndex] || "—"}` } } } }) });
    const peakHours = pr.weekday_period.map((p, i) => p === "PEAK" ? i : null).filter((x) => x !== null);
    $("#profileNote").textContent = `Weekday PEAK tariff hours (local): ${peakHours.length ? peakHours.map((h) => `${h}:00`).join(", ") : "none"}.`;

    const ms = D.machines.filter((m) => m.plant_id === pid && m.is_production);
    draw("idleChart", { type: "bar", data: { labels: ms.map((m) => m.name.replace(/^\S+\s/, "")), datasets: [{
      label: "Idle kWh above standby", data: ms.map((m) => m.idle_waste_kwh), backgroundColor: css("--s1"),
      borderRadius: 4, maxBarThickness: 36 }] },
      options: baseOpts({ plugins: { ...baseOpts().plugins, legend: { display: false },
        tooltip: { ...baseOpts().plugins.tooltip, callbacks: { afterLabel: (c) => `${ms[c.dataIndex].idle_events} episodes · idle ${ms[c.dataIndex].idle_kw} kW vs standby ${ms[c.dataIndex].standby_kw} kW` } } } }) });

    const rows = D.findings.filter((f) => f.issue_type === "HIGH_IDLE_CONSUMPTION" && f.plant_id === pid)
      .sort((a, b) => b.impact_kwh - a.impact_kwh);
    table($("#idleTable"), [
      { label: "Finding", key: "finding_id" }, { label: "Machine", key: "entity_id" },
      { label: "Start (UTC)", render: (r) => day(r.window_start_utc) }, { label: "Minutes", num: true, render: (r) => fmt(r.metric_value) },
      { label: "kWh wasted", num: true, render: (r) => fmt(r.impact_kwh, 1) }, { label: "Evidence", render: (r) => esc(r.detail) },
    ], rows);
  }

  // ---------------- engineer ----------------
  function engineer() {
    const mid = $("#machineSel").value;
    const pts = D.intensity.filter((r) => r.machine_id === mid && r.ratio !== null);
    const ok = pts.filter((r) => r.reliable), bad = pts.filter((r) => !r.reliable);
    const xs = pts.map((r) => Date.parse(r.t));
    const xmin = Math.min(...xs), xmax = Math.max(...xs);
    const mt = D.maintenance.filter((m) => m.machine_id === mid);
    const ymax = Math.max(1.4, ...ok.map((r) => r.ratio)) * 1.05;
    const ds = [
      { type: "scatter", label: "Batch kWh/unit ÷ baseline", data: ok.map((r) => ({ x: Date.parse(r.t), y: r.ratio, r })),
        backgroundColor: css("--s1"), pointRadius: 3.5, pointHoverRadius: 6 },
      { type: "line", label: "Drift threshold 1.10×", data: [{ x: xmin, y: 1.1 }, { x: xmax, y: 1.1 }],
        borderColor: css("--critical"), borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0 },
    ];
    if (bad.length) ds.push({ type: "scatter", label: "Quarantined meter (excluded)", data: bad.map((r) => ({ x: Date.parse(r.t), y: Math.min(r.ratio, ymax), r })),
      backgroundColor: "transparent", borderColor: css("--muted"), pointRadius: 3.5, pointStyle: "crossRot" });
    if (mt.length) ds.push({ type: "scatter", label: "Maintenance", data: mt.map((m) => ({ x: Date.parse(m.started), y: 0.84, m })),
      backgroundColor: css("--s3"), pointStyle: "triangle", pointRadius: 7 });
    const o = baseOpts({ interaction: { mode: "nearest", intersect: true } });
    o.scales.x = { type: "linear", min: xmin, max: xmax, grid: { display: false },
      ticks: { color: css("--text-2"), maxTicksLimit: 8, callback: (v) => new Date(v).toISOString().slice(5, 10) } };
    o.scales.y = { ...o.scales.y, beginAtZero: false, min: 0.8, max: Math.ceil(ymax * 10) / 10, ticks: { color: css("--text-2"), stepSize: 0.1 } };
    o.plugins.tooltip.callbacks = { label: (c) => {
      const raw = c.raw;
      if (raw.m) return `${raw.m.maintenance_id} ${raw.m.type}: ${raw.m.reason}`;
      if (raw.r) return `${raw.r.batch_id} ${raw.r.product}: ${raw.r.kwh_per_unit} kWh/unit (×${raw.r.ratio})`;
      return c.dataset.label;
    }, title: (it) => new Date(it[0].raw.x).toISOString().slice(0, 16).replace("T", " ") + " UTC" };
    draw("intensityChart", { type: "scatter", data: { datasets: ds }, options: o });
    const fd = D.findings.filter((f) => f.issue_type === "INTENSITY_DRIFT" && f.entity_id === mid);
    $("#intensityNote").textContent = fd.length ? fd.map((f) => `${f.finding_id}: ${f.detail}`).join(" · ") :
      "No intensity drift detected on this machine.";

    const pid = state.engineer;
    const off = D.offshift.filter((r) => r.plant_id === pid);
    draw("offChart", { type: "line", data: { labels: off.map((r) => r.day), datasets: [
      { label: "Actual", data: off.map((r) => r.actual), borderColor: css("--s2"), backgroundColor: css("--s2"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, order: 2 },
      { label: "Expected (weather-normalised)", data: off.map((r) => r.expected), borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, borderDash: [5, 4], order: 1 },
    ] }, options: baseOpts() });
    table($("#engFindings"), [
      { label: "Type", key: "issue_type" }, { label: "Entity", key: "entity_id" },
      { label: "Start", render: (r) => day(r.window_start_utc) }, { label: "kWh", num: true, render: (r) => fmt(r.impact_kwh, 0) },
      { label: "Evidence", render: (r) => esc(r.detail) },
    ], D.findings.filter((f) => ["INTENSITY_DRIFT", "OFF_SHIFT_WASTE"].includes(f.issue_type)));
  }

  // ---------------- planner ----------------
  function planner() {
    const pid = state.planner;
    const rows = D.period_daily.filter((r) => r.plant_id === pid);
    const present = PERIODS.filter((p) => rows.some((r) => r[p]));
    draw("touChart", { type: "bar", data: { labels: rows.map((r) => r.day), datasets: present.map((p) => ({
      label: p, data: rows.map((r) => r[p] || 0), backgroundColor: css(PERIOD_VAR[p]), borderColor: css("--surface"),
      borderWidth: { top: 2 }, borderSkipped: false, stack: "s" })) },
      options: baseOpts({ scales: { ...baseOpts().scales, x: { ...baseOpts().scales.x, stacked: true }, y: { ...baseOpts().scales.y, stacked: true } } }) });
    const cur = D.plants.find((p) => p.plant_id === pid).currency;
    table($("#billTable"), [
      { label: "Month", key: "month" }, { label: "kWh", num: true, render: (r) => fmt(r.kwh) },
      { label: `Energy ${cur}`, num: true, render: (r) => fmt(r.energy_cost) },
      { label: "Peak kW", num: true, render: (r) => fmt(r.peak_kw, 1) }, { label: "Peak in", key: "peak_period" },
      { label: `Demand ${cur}`, num: true, render: (r) => fmt(r.demand_charge) },
      { label: `Total ${cur}`, num: true, render: (r) => fmt(r.total_cost) },
    ], D.bills.filter((b) => b.plant_id === pid));
    table($("#spikeTable"), [
      { label: "Finding", key: "finding_id" }, { label: "Meter", key: "entity_id" },
      { label: "Start (UTC)", render: (r) => day(r.window_start_utc) }, { label: "Peak kW", num: true, render: (r) => fmt(r.metric_value, 1) },
      { label: "Evidence", render: (r) => esc(r.detail) },
    ], D.findings.filter((f) => f.issue_type === "PEAK_DEMAND_SPIKE" && f.plant_id === pid));
  }

  // ---------------- OT/IT ----------------
  function otit() {
    const dq = D.findings.filter((f) => f.category === "DATA_QUALITY");
    const counts = {};
    dq.forEach((f) => { counts[f.issue_type] = (counts[f.issue_type] || 0) + 1; });
    const label = { DUPLICATE_READING: "Duplicate readings", METER_GAP: "Meter gaps", UNIT_KW_AS_KWH: "kW written as kWh",
      REGISTER_INTERVAL_MISMATCH: "Register ≠ interval sum", HIERARCHY_TOTAL_MISMATCH: "Σ sub-meters > incomer",
      MACHINE_OUTSIDE_HIERARCHY: "Tag outside hierarchy", TARIFF_TZ_MISMATCH: "Tariff timezone" };
    $("#dqKpis").innerHTML = Object.keys(label).map((k) => `<div class="kpi"><div class="label">${label[k]}</div><div class="value">${fmt(counts[k] || 0)}</div><div class="foot">${k}</div></div>`).join("");
    table($("#evalTable"), [
      { label: "Issue type", key: "issue_type" }, { label: "Labelled", num: true, key: "ground_truth" },
      { label: "Found", num: true, key: "findings" }, { label: "Precision", num: true, render: (r) => fmt(r.precision, 3) },
      { label: "Recall", num: true, render: (r) => fmt(r.recall, 3) }, { label: "F1", num: true, render: (r) => fmt(r.f1, 3) },
      { label: "Decision acc.", num: true, render: (r) => fmt(r.decision_accuracy, 3) },
    ], D.evaluation);
    const v = D.validation.summary;
    $("#valHint").textContent = `${v.pass} pass · ${v.expected_fail} expected (labelled) · ${v.fail} fail${D.repro ? ` · reproducible: ${D.repro.reproducible ? "yes" : "no"} (${D.repro.files_compared} files)` : ""}`;
    const rank = { FAIL: 0, EXPECTED_FAIL: 1, PASS: 2 };
    table($("#valTable"), [
      { label: "Status", render: (r) => `<span class="badge ${r.status === "PASS" ? "ok" : r.status === "FAIL" ? "bad" : "exp"}">${r.status === "EXPECTED_FAIL" ? "expected" : r.status.toLowerCase()}</span>` },
      { label: "Check", render: (r) => `<code>${esc(r.check)}</code>` }, { label: "Category", key: "category" },
      { label: "Failures", num: true, key: "failures" }, { label: "Labelled", num: true, key: "explained_by_ground_truth" },
    ], [...D.validation.checks].sort((a, b) => rank[a.status] - rank[b.status]));
    const sel = $("#dqSel");
    if (!sel.options.length) {
      sel.innerHTML = `<option value="">All</option>` + Object.keys(label).map((k) => `<option value="${k}">${label[k]}</option>`).join("");
      sel.addEventListener("change", otit);
    }
    table($("#dqTable"), [
      { label: "Finding", key: "finding_id" }, { label: "Type", key: "issue_type" }, { label: "Entity", key: "entity_id" },
      { label: "Start (UTC)", render: (r) => day(r.window_start_utc) }, { label: "Decision", render: (r) => `<code>${esc(r.decision)}</code>` },
      { label: "Evidence", render: (r) => esc(r.detail) },
    ], dq.filter((f) => !sel.value || f.issue_type === sel.value));
    table($("#balTable"), [
      { label: "Meter", key: "meter_id" }, { label: "Type", key: "meter_type" },
      { label: "Interval sum kWh", num: true, render: (r) => fmt(r.interval_sum_kwh, 1) },
      { label: "Register span kWh", num: true, render: (r) => fmt(r.register_span_kwh, 1) },
      { label: "Detected offsets", num: true, render: (r) => fmt(r.detected_register_offsets_kwh, 1) },
      { label: "Diff %", num: true, render: (r) => fmt(r.difference_pct, 3) },
      { label: "Backfilled", num: true, key: "estimated_intervals" },
    ], D.energy_balance);
  }

  // ---------------- recommendations ----------------
  function recs() {
    const owner = $("#ownerSel").value, pid = $("#recPlantSel").value;
    const rows = D.recommendations.filter((r) => (!owner || r.owner_role === owner) && (!pid || r.plant_id === pid));
    $("#recList").innerHTML = rows.map((r) => `
      <article class="rec">
        <div><h3>${esc(r.title)}</h3>
          <div class="meta">${esc(r.rec_id)} · ${esc(plantName(r.plant_id))} · ${esc(ROLE[r.owner_role] || r.owner_role)} · ${esc(r.rule_id)} · confidence ${esc(r.confidence)} · ${esc(r.status)}</div></div>
        <div class="save"><div class="big">$${fmt(r.expected_savings_usd_yr)}/yr</div>
          <div class="meta">${fmt(r.expected_savings_cost_yr)} ${esc(r.currency)}${r.expected_savings_kwh_yr ? ` · ${fmt(r.expected_savings_kwh_yr)} kWh/yr` : ""}${r.expected_savings_kw ? ` · −${fmt(r.expected_savings_kw, 1)} kW` : ""}</div></div>
        <div class="body">
          <div><b>Baseline:</b> ${esc(r.baseline_metric)} = ${fmt(r.baseline_value, 2)} ${esc(r.baseline_unit)} (${day(r.baseline_window_start_utc)} → ${day(r.baseline_window_end_utc)} UTC)</div>
          <div><b>Savings formula:</b> ${esc(r.savings_formula)}</div>
          ${r.evidence_ids ? `<div><b>Evidence:</b> <code>${esc(String(r.evidence_ids).split(";").slice(0, 8).join(", "))}${String(r.evidence_ids).split(";").length > 8 ? " …" : ""}</code></div>` : ""}
        </div>
      </article>`).join("") || `<p class="hint">No recommendations for this filter.</p>`;
  }

  // ---------------- wiring ----------------
  const renderers = { overview, operator, engineer, planner, otit, recs };
  let active = "overview";
  function show(tab) {
    active = tab;
    document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === tab));
    renderers[tab]();
    try { localStorage.setItem("ef-tab", tab); } catch (e) { /* storage unavailable */ }
    history.replaceState(null, "", `#${tab}`);
  }

  function init() {
    $("#subtitle").textContent = `${D.plants.length} plants · ${D.meta.row_counts.meter} meters · ${D.headline.days} days of 15-min readings · ${fmt(D.meta.row_counts.production_batch)} batches · seed ${D.meta.seed}`;
    $("#footMeta").textContent = `Window ${D.meta.window_utc.join(" → ")} · ${D.meta.generator_command}`;
    const popts = D.plants.map((p) => `<option value="${p.plant_id}">${p.plant_id} · ${esc(p.plant_name)}</option>`).join("");
    document.querySelectorAll(".plantSel").forEach((s) => {
      s.innerHTML = popts;
      state[s.dataset.target] = D.plants[0].plant_id;
      s.addEventListener("change", () => { state[s.dataset.target] = s.value; renderers[active](); });
    });
    const machines = D.machines.filter((m) => m.is_production);
    const drift = new Set(D.findings.filter((f) => f.issue_type === "INTENSITY_DRIFT").map((f) => f.entity_id));
    $("#machineSel").innerHTML = machines.map((m) => `<option value="${m.machine_id}">${m.machine_id} · ${esc(m.name)}${drift.has(m.machine_id) ? " ⚠ drift" : ""}</option>`).join("");
    $("#machineSel").value = [...drift][0] || machines[0].machine_id;
    $("#machineSel").addEventListener("change", engineer);
    $("#ownerSel").innerHTML = `<option value="">All</option>` + Object.entries(ROLE).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
    $("#recPlantSel").innerHTML = `<option value="">All</option>` + popts;
    $("#ownerSel").addEventListener("change", recs);
    $("#recPlantSel").addEventListener("change", recs);
    document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
    $("#theme").addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") ||
        (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      document.documentElement.setAttribute("data-theme", cur === "dark" ? "light" : "dark");
      renderers[active]();
    });
    let start = location.hash.slice(1);
    if (!renderers[start]) { try { start = localStorage.getItem("ef-tab") || "overview"; } catch (e) { start = "overview"; } }
    show(renderers[start] ? start : "overview");
  }

  fetch("data/dashboard.json").then((r) => r.json()).then((d) => { D = d; init(); })
    .catch((e) => { document.querySelector("main").innerHTML = `<p class="card">Could not load data/dashboard.json: ${esc(e)}</p>`; });
})();
