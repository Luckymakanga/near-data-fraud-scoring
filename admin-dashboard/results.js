// Research results page. Reads the condensed benchmark results from the API
// (GET /api/research/results, login required) and draws tables and SVG charts.
//
// Everything is built with DOM calls and text nodes, never by assigning markup
// strings, so no value from the API can be interpreted as markup.

const API_BASE = window.FRAUD_API_BASE ||
  (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://localhost:5000"
    : `${window.location.protocol}//${window.location.hostname}:5000`);

const TOKEN_KEY = "fraudAdmin.token";
const SVG_NS = "http://www.w3.org/2000/svg";

const MODE_LABEL = {
  external_batch: "External batch",
  in_database: "In-database",
  application: "Application tier",
};
const MODE_COLOR = {
  external_batch: "var(--yellow)",
  in_database: "var(--blue)",
  application: "var(--accent)",
};

// ---------- small DOM helpers ----------

function h(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (key === "class") node.className = value;
    else if (value !== undefined && value !== null) node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function svg(tag, attrs, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
  for (const child of children.flat()) {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function table(headers, rows, extraClass) {
  return h("table", { class: `results-table ${extraClass || ""}`.trim() },
    h("thead", {}, h("tr", {}, headers.map((text) => h("th", {}, text)))),
    h("tbody", {}, rows.map((cells) => h("tr", {}, cells.map((cell) => {
      const td = h("td", {});
      td.append(cell instanceof Node ? cell : document.createTextNode(String(cell)));
      return td;
    })))));
}

// ---------- formatting ----------

function fmtMs(ms) {
  if (typeof ms !== "number") return "–";
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)} s`;
  return `${ms >= 100 ? Math.round(ms) : ms.toFixed(ms >= 10 ? 0 : 1)} ms`;
}

function fmtNum(n, digits) {
  return typeof n === "number" ? n.toFixed(digits) : "–";
}

function pct(x) {
  return typeof x === "number" ? `${Math.round(x * 100)}%` : "–";
}

// "23 ms inside the database and 23 ms in the application" reads badly when the two are the same
function onArrivalPhrase(inDatabase, application) {
  const a = fmtMs(inDatabase), b = fmtMs(application);
  return a === b ? `about ${a}, whether inside the database or in the application`
    : `about ${a} inside the database and ${b} in the application`;
}

function latencyCell(row) {
  const text = `${fmtMs(row.p50_ms)} / ${fmtMs(row.p99_ms)}`;
  if (!row.saturated) return text;
  return h("span", {}, text, " ", h("span", { class: "sat-badge" }, `kept up with only ${Math.round(row.achieved_rate_per_s)}/s`));
}

// ---------- charts ----------

function cssColor(value) {
  // Resolve a CSS variable such as "var(--blue)" to a colour for SVG attributes
  const name = value.match(/var\((--[a-z-]+)\)/);
  return name ? getComputedStyle(document.documentElement).getPropertyValue(name[1]).trim() : value;
}

function lineChart(container, options) {
  const { categories, series, yTicks, yFormat, yMin, yMax, logY, xTitle, yTitle, label } = options;
  const W = 560, H = 310, left = 64, right = 18, top = 14, bottom = 58;
  const plotW = W - left - right, plotH = H - top - bottom;

  const scaleY = (v) => {
    const clamped = Math.max(yMin, Math.min(yMax, v));
    const t = logY
      ? (Math.log10(clamped) - Math.log10(yMin)) / (Math.log10(yMax) - Math.log10(yMin))
      : (clamped - yMin) / (yMax - yMin);
    return top + plotH * (1 - t);
  };
  const scaleX = (i) => left + (categories.length === 1 ? plotW / 2 : (plotW * i) / (categories.length - 1));

  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label, class: "chart-svg" });
  const grid = cssColor("var(--border)"), dim = cssColor("var(--text-dim)");

  yTicks.forEach((tick) => {
    const y = scaleY(tick);
    root.append(svg("line", { x1: left, x2: W - right, y1: y, y2: y, stroke: grid, "stroke-width": 1 }));
    root.append(svg("text", { x: left - 8, y: y + 4, "text-anchor": "end", fill: dim, "font-size": 11 }, yFormat(tick)));
  });
  categories.forEach((text, i) => {
    root.append(svg("text", { x: scaleX(i), y: H - bottom + 18, "text-anchor": "middle", fill: dim, "font-size": 11 }, text));
  });
  root.append(svg("text", { x: left + plotW / 2, y: H - 10, "text-anchor": "middle", fill: dim, "font-size": 12 }, xTitle));
  root.append(svg("text", { x: 14, y: top + plotH / 2, "text-anchor": "middle", fill: dim, "font-size": 12,
    transform: `rotate(-90 14 ${top + plotH / 2})` }, yTitle));

  series.forEach((s) => {
    const color = cssColor(s.color);
    const points = s.points.filter((p) => typeof p.y === "number");
    if (points.length > 1) {
      root.append(svg("polyline", {
        points: points.map((p) => `${scaleX(p.i)},${scaleY(p.y)}`).join(" "),
        fill: "none", stroke: color, "stroke-width": 2.5, "stroke-linejoin": "round",
        "stroke-dasharray": s.dashed ? "6 4" : "none",
      }));
    }
    points.forEach((p) => {
      root.append(svg("circle", { cx: scaleX(p.i), cy: scaleY(p.y), r: 4, fill: color }));
      if (p.saturated) {
        root.append(svg("circle", { cx: scaleX(p.i), cy: scaleY(p.y), r: 9, fill: "none",
          stroke: cssColor("var(--red)"), "stroke-width": 2 }));
      }
    });
  });

  clear(container);
  container.append(root);
}

function legend(container, entries, note) {
  clear(container);
  entries.forEach((e) => container.append(h("span", { class: "legend-item" },
    h("span", { class: `swatch${e.dashed ? " dashed" : ""}`, style: `--swatch: ${e.color}` }), e.name)));
  if (note) container.append(h("span", { class: "legend-item legend-note" }, note));
}

// ---------- sections ----------

function renderDetection(d) {
  const panel = document.getElementById("detectionPanel");
  const labels = { precision: "Precision", recall: "Recall", f1: "F1 score", pr_auc: "PR-AUC", fpr: "False-positive rate" };
  document.getElementById("detectionTake").textContent =
    `The model found ${pct(d.metrics.recall.value)} of the frauds in the test. About ${pct(d.metrics.precision.value)} of the transactions it flagged were really fraud.`;
  document.getElementById("detectionHint").textContent =
    `Measured on the later ${d.test_transactions.toLocaleString()} transactions (${d.test_frauds} frauds), after training on the earlier ones, with the real fraud prevalence restored. ` +
    `With so few frauds the intervals are wide. Precision is ${fmtNum(d.precision_before_prevalence_restored, 2)} before the prevalence is restored, which is why that step matters.`;
  const grid = document.getElementById("detectionCards");
  clear(grid);
  Object.entries(labels).forEach(([key, text]) => {
    const m = d.metrics[key];
    const digits = key === "fpr" ? 4 : 2;
    grid.append(h("div", { class: "stat-card" },
      h("span", { class: "stat-label" }, text),
      h("span", { class: "stat-value" }, fmtNum(m.value, digits)),
      h("span", { class: "stat-range" }, `95% interval ${fmtNum(m.low, digits)} to ${fmtNum(m.high, digits)}`)));
  });
  panel.hidden = false;
}

function renderBaseline(b) {
  document.getElementById("baselineTake").textContent =
    `A batch job took about ${fmtMs(b.architectures.external_batch.p50_ms)} to decide, because it waits for its timer. ` +
    `Scoring as the transaction arrives took ${onArrivalPhrase(b.architectures.in_database.p50_ms, b.architectures.application.p50_ms)}.`;
  document.getElementById("baselineHint").textContent =
    `${b.transactions.toLocaleString()} transactions at ${b.rate_per_s} per second over one connection; median of ${b.runs} runs. ` +
    `A batch job that polls every ${b.batch_interval_s} seconds cannot decide faster than its polling interval; scoring on arrival decides in tens of milliseconds. The scores were identical in all three.`;
  const rows = [
    ["Decision latency, median", ...Object.keys(MODE_LABEL).map((m) => fmtMs(b.architectures[m].p50_ms))],
    ["Decision latency, 99th percentile", ...Object.keys(MODE_LABEL).map((m) => fmtMs(b.architectures[m].p99_ms))],
    ["Processor seconds per 1,000 transactions", ...Object.keys(MODE_LABEL).map((m) => fmtNum(b.architectures[m].cpu_s_per_1000, 2))],
    ["Peak memory, application / database", ...Object.keys(MODE_LABEL).map((m) =>
      `${Math.round(b.architectures[m].peak_memory_application_mb)} / ${Math.round(b.architectures[m].peak_memory_database_mb)} MB`)],
  ];
  const holder = document.getElementById("baselineTable");
  clear(holder);
  holder.append(table(["", ...Object.values(MODE_LABEL)], rows));
  document.getElementById("baselinePanel").hidden = false;
}

function renderSweep(s) {
  const connectionsAvailable = [...new Set(s.points.map((p) => p.connections))].sort((a, b) => a - b);
  let selected = connectionsAvailable[0];
  const pills = document.getElementById("connectionPills");

  // one sentence, read from the data: where the two designs that score on arrival stopped keeping up with the fewest connections
  const fewest = connectionsAvailable[0];
  const firstSaturated = (mode) => {
    const hit = s.points.filter((p) => p.connections === fewest).sort((a, b) => a.rate_per_s - b.rate_per_s)
      .find((p) => p.architectures[mode].saturated);
    return hit ? hit.rate_per_s : null;
  };
  const inDb = firstSaturated("in_database"), inApp = firstSaturated("application");
  const conn = `${fewest} connection${fewest === 1 ? "" : "s"}`;
  let take;
  if (inDb && inApp) {
    take = inDb === inApp
      ? `With ${conn}, scoring in the database and in the application stopped keeping up at ${inDb} transactions a second.`
      : `With ${conn}, scoring stopped keeping up at ${inDb} a second inside the database and at ${inApp} a second in the application.`;
  } else if (inDb || inApp) {
    take = `With ${conn}, scoring ${inDb ? "inside the database" : "in the application"} stopped keeping up at ${inDb || inApp} transactions a second.`;
  } else {
    take = `With ${conn}, both designs that score on arrival kept up at every load tested.`;
  }
  const limit = Math.min(...[inDb, inApp].filter(Boolean));
  if (Number.isFinite(limit) && s.points.some((p) => p.connections > fewest && p.rate_per_s >= limit && !p.architectures.in_database.saturated && !p.architectures.application.saturated)) {
    take += " More connections let them keep up.";
  }
  document.getElementById("sweepTake").textContent = take;

  function draw() {
    clear(pills);
    connectionsAvailable.forEach((c) => {
      const pill = h("button", { type: "button", class: `pill${c === selected ? " active" : ""}`, "aria-pressed": String(c === selected) },
        `${c} connection${c === 1 ? "" : "s"}`);
      pill.addEventListener("click", () => { selected = c; draw(); });
      pills.append(pill);
    });

    const points = s.points.filter((p) => p.connections === selected).sort((a, b) => a.rate_per_s - b.rate_per_s);
    const categories = points.map((p) => `${p.rate_per_s}/s`);
    lineChart(document.getElementById("sweepChart"), {
      categories,
      series: Object.keys(MODE_LABEL).map((mode) => ({
        color: MODE_COLOR[mode],
        points: points.map((p, i) => ({ i, y: p.architectures[mode].p50_ms, saturated: p.architectures[mode].saturated })),
      })),
      yTicks: [10, 100, 1000, 10000, 100000], yFormat: fmtMs, yMin: 10, yMax: 100000, logY: true,
      xTitle: "Transactions arriving per second", yTitle: "Median decision latency",
      label: `Median decision latency against arrival rate with ${selected} connection${selected === 1 ? "" : "s"}, for three architectures`,
    });
    legend(document.getElementById("sweepLegend"),
      Object.keys(MODE_LABEL).map((m) => ({ name: MODE_LABEL[m], color: MODE_COLOR[m] })),
      "A red ring marks a load the architecture could not keep up with: a backlog built up, so delays grew.");

    document.getElementById("sweepHint").textContent =
      `${selected} connection${selected === 1 ? "" : "s"} sharing the arrivals; about ${s.duration_s} seconds of transactions per run, median of ${s.runs_per_cell} runs. ` +
      "The vertical scale is logarithmic: each gridline is ten times the one below.";

    const holder = document.getElementById("sweepTable");
    clear(holder);
    holder.append(table(["Arrivals per second", "External batch", "In-database", "Application tier"],
      points.map((p) => [`${p.rate_per_s}`, ...Object.keys(MODE_LABEL).map((m) => latencyCell(p.architectures[m]))])));
    holder.append(h("p", { class: "table-note" }, "Each cell: median / 99th percentile decision latency."));
  }
  draw();

  // memory and processor cost against connections, at the one rate every connection count was tested
  const reference = s.points.filter((p) => p.rate_per_s === 80).sort((a, b) => a.connections - b.connections);
  const cost = document.getElementById("costTable");
  clear(cost);
  if (reference.length) {
    cost.append(table(["Connections", "Batch: memory / CPU", "In-database: memory / CPU", "Application tier: memory / CPU"],
      reference.map((p) => [`${p.connections}`, ...Object.keys(MODE_LABEL).map((m) =>
        `${Math.round(p.architectures[m].memory_mb)} MB / ${fmtNum(p.architectures[m].cpu_s_per_1000, 1)} s per 1,000`)])));
  }
  document.getElementById("sweepPanel").hidden = false;
}

function renderNetwork(n) {
  const roundTrips = [...new Set(n.points.map((p) => Math.round(p.round_trip_ms)))].sort((a, b) => a - b);
  const find = (rt, reads) => n.points.find((p) => Math.round(p.round_trip_ms) === rt && p.reads === reads);
  const farthest = find(roundTrips[roundTrips.length - 1], 3);
  document.getElementById("networkTake").textContent = farthest
    ? `With 3 lookups per transaction and a round trip of ${roundTrips[roundTrips.length - 1]} ms, the application tier took ${fmtMs(farthest.architectures.application.p50_ms)} against ${fmtMs(farthest.architectures.in_database.p50_ms)} for the in-database design.`
    : "The further the database is from the application, the longer the application tier waits on each lookup.";
  const line = (mode, reads, dashed) => ({
    color: MODE_COLOR[mode], dashed,
    points: roundTrips.map((rt, i) => ({ i, y: (find(rt, reads) || { architectures: {} }).architectures[mode]?.p50_ms })),
  });
  lineChart(document.getElementById("networkChart"), {
    categories: roundTrips.map((rt) => `${rt} ms`),
    series: [line("in_database", 0, true), line("application", 0, true), line("in_database", 3, false), line("application", 3, false)],
    yTicks: [0, 100, 200, 300, 400, 500], yFormat: (v) => `${v} ms`, yMin: 0, yMax: 500, logY: false,
    xTitle: "Round trip between application and database", yTitle: "Median decision latency",
    label: "Median decision latency against network round trip, with and without database reads before scoring",
  });
  legend(document.getElementById("networkLegend"), [
    { name: "In-database, no reads", color: MODE_COLOR.in_database, dashed: true },
    { name: "Application tier, no reads", color: MODE_COLOR.application, dashed: true },
    { name: "In-database, 3 reads", color: MODE_COLOR.in_database },
    { name: "Application tier, 3 reads", color: MODE_COLOR.application },
  ], "The in-database lines overlap.");
  document.getElementById("networkHint").textContent =
    `A delaying relay was placed between the application and the database. ${n.transactions} transactions per run at ${n.rate_per_s} per second over ${n.connections} connections; median of ${n.runs_per_cell} runs. ` +
    "“Reads” are stored-data lookups each transaction needs before scoring: the application tier pays one round trip for each, the in-database trigger reads them locally. " +
    "The reads are stand-ins chosen by the study, not a measurement of any bank.";

  const rows = [];
  roundTrips.forEach((rt) => [0, 3].forEach((reads) => {
    const p = find(rt, reads);
    if (!p) return;
    rows.push([`${rt} ms`, `${reads}`, ...Object.keys(MODE_LABEL).map((m) => fmtMs(p.architectures[m].p50_ms))]);
  }));
  const holder = document.getElementById("networkTable");
  clear(holder);
  holder.append(table(["Round trip", "Reads", "External batch", "In-database", "Application tier"], rows));
  holder.append(h("p", { class: "table-note" }, "Each cell: median decision latency."));
  document.getElementById("networkPanel").hidden = false;
}

// A few plain lines at the top, built from the same result files as everything below
function renderSummary(results) {
  const items = [];
  const b = results.baseline && results.baseline.architectures;
  if (b) {
    items.push(`A batch job takes about ${fmtMs(b.external_batch.p50_ms)} to reach a decision.`);
    items.push(`Scoring as the transaction arrives takes ${onArrivalPhrase(b.in_database.p50_ms, b.application.p50_ms)}.`);
  }
  if (results.network) {
    const trips = [...new Set(results.network.points.map((p) => Math.round(p.round_trip_ms)))].sort((a, c) => a - c);
    const far = results.network.points.find((p) => Math.round(p.round_trip_ms) === trips[trips.length - 1] && p.reads === 3);
    if (far) {
      items.push(`Far from the database, the application waits on every lookup: ${fmtMs(far.architectures.application.p50_ms)} against ${fmtMs(far.architectures.in_database.p50_ms)} at a ${trips[trips.length - 1]} ms round trip.`);
    }
  }
  if (results.detection) {
    items.push(`The model found ${pct(results.detection.metrics.recall.value)} of the frauds in a test of ${results.detection.test_transactions.toLocaleString()} transactions.`);
  }
  if (items.length) items.push("All three use the same model and give the same scores, so only the timing differs.");
  const list = document.getElementById("summaryList");
  clear(list);
  items.forEach((text) => list.append(h("li", {}, text)));
  document.getElementById("summaryPanel").hidden = !items.length;
}

function renderNotes(summary) {
  const items = [
    "The data are a public dataset of European card transactions with anonymised features. They stand in for bank data and say nothing about fraud rates or patterns in Uganda.",
    summary.detection ? `The detection figures rest on ${summary.detection.test_frauds} frauds in the test set, so they are uncertain, as the intervals show.` : null,
    summary.sweep ? `All timings come from ${summary.sweep.machine}. The application and the database ran on the same machine except in the distance test.` : null,
    summary.sweep ? `The machine was not fully quiet: in the load sweep, ${summary.sweep.runs_started_busy} of ${summary.sweep.runs_total} runs started with the processor more than 25% busy. Medians held up better than the 99th-percentile figures at low loads.` : null,
    summary.network && summary.network.median_other_programs_cpu_percent !== null
      ? `In the distance test, other programs used a median of about ${summary.network.median_other_programs_cpu_percent}% of the processor during runs (a lower bound).` : null,
    "The distance test adds a fixed delay only: no bandwidth limit, jitter or packet loss. The round trips are measured values, not figures from any Ugandan network.",
    "These results describe scoring architectures under stated conditions. They are not predictions for a particular bank, and drift, explanations and real bank systems were not tested.",
    summary.missing && summary.missing.length ? `Some result files could not be read: ${summary.missing.join(", ")}.` : null,
  ].filter(Boolean);
  const list = document.getElementById("notesList");
  clear(list);
  items.forEach((text) => list.append(h("li", {}, text)));
  document.getElementById("notesPanel").hidden = false;
}

// ---------- start-up ----------

function goToLogin() {
  sessionStorage.removeItem(TOKEN_KEY);
  window.location.replace("index.html");
}

document.getElementById("logoutBtn").addEventListener("click", goToLogin);

async function load() {
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (!token) return goToLogin();

  const status = document.getElementById("status");
  try {
    const response = await fetch(`${API_BASE}/api/research/results`, { headers: { Authorization: `Bearer ${token}` } });
    if (response.status === 401) return goToLogin();
    if (!response.ok) throw new Error(`The server answered ${response.status}`);
    const { results } = await response.json();

    renderSummary(results);
    if (results.detection) renderDetection(results.detection);
    if (results.baseline) renderBaseline(results.baseline);
    if (results.sweep) renderSweep(results.sweep);
    if (results.network) renderNetwork(results.network);
    renderNotes(results);
    status.textContent = results.missing.length ? "Some results are not available." : "";
    status.hidden = !results.missing.length;
  } catch (err) {
    status.textContent = `Could not load the results: ${err.message}. If the service has been idle, wait a minute and reload.`;
  }
}

load();
