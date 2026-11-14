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
const MODES = Object.keys(MODE_LABEL);

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
  return h("table", { class: `results-table stack ${extraClass || ""}`.trim() },
    h("thead", {}, h("tr", {}, headers.map((text) => h("th", {}, text)))),
    h("tbody", {}, rows.map((cells) => h("tr", {}, cells.map((cell, column) => {
      const td = h("td", { "data-label": headers[column] });
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

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
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

// A chart is drawn for the width it has: a phone gets a narrower drawing, so the text
// stays readable instead of shrinking with it. Charts redraw when the screen changes size.
function isNarrow(container) {
  const available = container.clientWidth || Math.min(window.innerWidth - 64, 800);
  return available < 480;
}

// Gridlines at round numbers from 0 up to the largest value
function niceTicks(max, count = 5) {
  const rough = max / count || 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough);
  const ticks = [];
  for (let v = 0; v <= max + step * 0.5; v += step) ticks.push(Math.round(v * 1000) / 1000);
  return { ticks, top: ticks[ticks.length - 1] };
}

function lineChart(container, options) {
  container._redraw = () => lineChart(container, options);
  const { categories, series, yTicks, yFormat, yMin, yMax, logY, xTitle, yTitle, label } = options;
  const narrow = isNarrow(container);
  const f = (size) => (narrow ? Math.round(size * 1.2) : size);     // a little larger text on a phone
  const W = narrow ? 380 : 560, H = narrow ? 300 : 310, left = narrow ? 58 : 64, right = 18, top = 14, bottom = 58;
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
    root.append(svg("text", { x: left - 8, y: y + 4, "text-anchor": "end", fill: dim, "font-size": f(11) }, yFormat(tick)));
  });
  categories.forEach((text, i) => {
    root.append(svg("text", { x: scaleX(i), y: H - bottom + 18, "text-anchor": "middle", fill: dim, "font-size": f(11) }, text));
  });
  root.append(svg("text", { x: left + plotW / 2, y: H - 10, "text-anchor": "middle", fill: dim, "font-size": f(12) }, xTitle));
  root.append(svg("text", { x: 14, y: top + plotH / 2, "text-anchor": "middle", fill: dim, "font-size": f(12),
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

// Horizontal bars from zero, one for each item, with its value written at the end of the bar
function barChart(container, options) {
  container._redraw = () => barChart(container, options);
  const { items, format, xTitle, yTitle, label } = options;
  const narrow = isNarrow(container);
  const f = (size) => (narrow ? Math.round(size * 1.2) : size);     // a little larger text on a phone
  const W = narrow ? 380 : 560, left = 30, right = 70, top = 8, rowH = 54, axisH = 46;
  const H = top + rowH * items.length + axisH;
  const plotW = W - left - right;
  const { ticks, top: axisMax } = niceTicks(Math.max(...items.map((i) => i.value)));
  const scaleX = (v) => left + (plotW * v) / axisMax;
  const grid = cssColor("var(--border)"), dim = cssColor("var(--text-dim)"), text = cssColor("var(--text)");

  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label, class: "chart-svg" });
  const bottom = top + rowH * items.length;
  ticks.forEach((tick) => {
    root.append(svg("line", { x1: scaleX(tick), x2: scaleX(tick), y1: top, y2: bottom, stroke: grid, "stroke-width": 1 }));
    root.append(svg("text", { x: scaleX(tick), y: bottom + 16, "text-anchor": "middle", fill: dim, "font-size": f(11) }, format(tick)));
  });
  items.forEach((item, i) => {
    const y = top + rowH * i;
    const width = Math.max(2, scaleX(item.value) - left);
    root.append(svg("text", { x: left, y: y + 15, fill: text, "font-size": f(12), "font-weight": 600 }, item.name));
    root.append(svg("rect", { x: left, y: y + 21, width, height: 22, rx: 3, fill: cssColor(item.color) }));
    root.append(svg("text", { x: left + width + 6, y: y + 37, fill: text, "font-size": f(12), "font-weight": 600 }, format(item.value)));
  });
  root.append(svg("text", { x: left + plotW / 2, y: H - 8, "text-anchor": "middle", fill: dim, "font-size": f(12) }, xTitle));
  root.append(svg("text", { x: 10, y: top + (rowH * items.length) / 2, "text-anchor": "middle", fill: dim, "font-size": f(12),
    transform: `rotate(-90 10 ${top + (rowH * items.length) / 2})` }, yTitle));

  clear(container);
  container.append(root);
}

function redrawCharts() {
  document.querySelectorAll(".chart-wrap").forEach((c) => { if (c._redraw) c._redraw(); });
}

let lastNarrow = null;
window.addEventListener("resize", () => {
  const narrow = window.innerWidth < 560;
  if (narrow !== lastNarrow) { lastNarrow = narrow; redrawCharts(); }
});

function legend(container, entries, note) {
  clear(container);
  entries.forEach((e) => container.append(h("span", { class: "legend-item" },
    h("span", { class: `swatch${e.dashed ? " dashed" : ""}`, style: `--swatch: ${e.color}` }), e.name)));
  if (note) container.append(h("span", { class: "legend-item legend-note" }, note));
}

// ---------- section 1: how well does the model detect fraud ----------

// What each measure means, in plain words
const METRICS = [
  ["precision", "Precision", 2, "Of the transactions the model flagged, the share that really were fraud."],
  ["recall", "Recall", 2, "Of all the real frauds, the share the model caught."],
  ["f1", "F1 score", 2, "One number that balances precision and recall."],
  ["roc_auc", "AUC-ROC", 3, "How well the model ranks frauds above genuine payments: 0.5 is no better than chance, 1 is perfect."],
  ["pr_auc", "PR-AUC", 2, "Like AUC-ROC, but it looks only at the rare frauds, so it falls when there are many false alarms."],
  ["fpr", "False-positive rate", 4, "The share of genuine transactions the model wrongly flagged."],
];

function renderDetection(d, baseline) {
  const panel = document.getElementById("detectionPanel");
  document.getElementById("detectionTake").textContent =
    `The model found ${pct(d.metrics.recall.value)} of the frauds in the test. About ${pct(d.metrics.precision.value)} of the transactions it flagged were really fraud.`;

  // detection belongs to the model; it does not depend on where the scoring runs
  const diffs = baseline ? MODES.map((m) => baseline.architectures[m].max_score_difference).filter((v) => typeof v === "number") : [];
  const identical = diffs.length === MODES.length && diffs.every((v) => v === 0);
  document.getElementById("detectionScope").textContent = identical
    ? "This section is about the model, not about where it runs. The three architectures produced identical scores, so these figures are the same for all three; where the scoring runs changes only how fast a decision arrives (sections 2 to 4)."
    : "This section is about the model, not about where it runs. Where the scoring runs changes how fast a decision arrives (sections 2 to 4).";

  document.getElementById("detectionBasis").textContent =
    `Measured on the later ${d.test_transactions.toLocaleString()} transactions (${d.test_frauds} frauds) after training on the earlier ones, with the real fraud prevalence restored. Each figure is shown with its 95% interval, the range the true value probably lies in.`;
  document.getElementById("detectionHint").textContent =
    `With so few frauds the intervals are wide. Precision is ${fmtNum(d.precision_before_prevalence_restored, 2)} before the prevalence is restored, which is why that step matters.`;

  const grid = document.getElementById("detectionCards");
  clear(grid);
  METRICS.forEach(([key, text, digits, meaning]) => {
    const m = d.metrics[key];
    if (!m) return;
    grid.append(h("div", { class: "stat-card" },
      h("span", { class: "stat-label" }, text),
      h("span", { class: "stat-value" }, fmtNum(m.value, digits)),
      h("span", { class: "stat-range" }, `95% interval ${fmtNum(m.low, digits)} to ${fmtNum(m.high, digits)}`),
      h("span", { class: "stat-help" }, meaning)));
  });
  panel.hidden = false;
}

// ---------- section 2: the architectures at a light load ----------

// Mark the lowest value in a row, and any within 10% of it (lower is better in every row of the table)
function bestFlags(values) {
  const numbers = values.filter((v) => typeof v === "number");
  if (numbers.length < 2) return values.map(() => false);
  const lowest = Math.min(...numbers);
  return values.map((v) => typeof v === "number" && v <= lowest * 1.1);
}

function renderBaseline(b) {
  const a = b.architectures;
  const arrival = Math.min(a.in_database.p50_ms, a.application.p50_ms);
  document.getElementById("baselineTake").textContent =
    `A batch job took about ${fmtMs(a.external_batch.p50_ms)} to decide, because it waits for its timer. ` +
    `Scoring as the transaction arrives took ${onArrivalPhrase(a.in_database.p50_ms, a.application.p50_ms)}.`;

  barChart(document.getElementById("baselineChart"), {
    items: MODES.map((m) => ({ name: MODE_LABEL[m], value: a[m].p50_ms, color: MODE_COLOR[m] })),
    format: (v) => (v === 0 ? "0" : fmtMs(v)), xTitle: "Median decision latency (shorter is better)", yTitle: "Architecture",
    label: `Median decision latency of the three architectures at ${b.rate_per_s} transactions per second: ` +
      MODES.map((m) => `${MODE_LABEL[m]} ${fmtMs(a[m].p50_ms)}`).join(", "),
  });
  const ratio = Math.round(a.external_batch.p50_ms / arrival / 10) * 10;
  document.getElementById("baselineRead").textContent =
    `On the same bar scale the two designs that score on arrival are barely visible: the batch job took about ${ratio} times as long at the median, because it only looks for new transactions every ${b.batch_interval_s} seconds. ` +
    "The bars are drawn from zero, so their lengths are in true proportion.";

  // one row of the side-by-side table: the value for each architecture, lowest marked
  const rows = [];
  const addRow = (name, get, show) => {
    const values = MODES.map((m) => get(a[m]));
    const flags = bestFlags(values);
    rows.push([name, ...values.map((v, i) => h("span", { class: flags[i] ? "best" : "" }, show(v, a[MODES[i]])))]);
  };
  addRow("Decision latency, mean", (r) => r.mean_ms, fmtMs);
  addRow("Decision latency, median", (r) => r.p50_ms, fmtMs);
  addRow("Decision latency, 95th percentile", (r) => r.p95_ms, fmtMs);
  addRow("Decision latency, 99th percentile", (r) => r.p99_ms, fmtMs);
  addRow("Processor seconds per 1,000 transactions", (r) => r.cpu_s_per_1000, (v) => fmtNum(v, 2));
  addRow("Processor utilization, average share of one core", (r) => (typeof r.cpu_s_per_1000 === "number" ? (r.cpu_s_per_1000 * b.rate_per_s) / 1000 : null),
    (v) => (typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "–"));
  addRow("Peak memory (application + database)", (r) => r.memory_mb,
    (v, r) => `${Math.round(r.peak_memory_application_mb)} + ${Math.round(r.peak_memory_database_mb)} = ${Math.round(v)} MB`);
  const holder = document.getElementById("baselineTable");
  clear(holder);
  holder.append(table(["", ...MODES.map((m) => MODE_LABEL[m])], rows, "compare"));
  document.getElementById("baselineKey").textContent =
    "Shaded: the lowest value in the row, or within 10% of it. Each row is judged on its own, so different designs lead on different rows. Processor figures are for the whole machine: the application and the database together.";

  const list = document.getElementById("baselineTradeoffs");
  clear(list);
  const li = (name, text) => list.append(h("li", {}, h("strong", {}, `${name}. `), text));
  li("External batch", `Decides in about ${fmtMs(a.external_batch.p50_ms)}, set by its ${b.batch_interval_s}-second timer, but used the least processor time (${fmtNum(a.external_batch.cpu_s_per_1000, 2)} seconds per 1,000 transactions against ${fmtNum(a.in_database.cpu_s_per_1000, 1)} and ${fmtNum(a.application.cpu_s_per_1000, 1)} for the others). It needs a second process to run and monitor.`);
  li("In-database", `Decides in ${fmtMs(a.in_database.p50_ms)} and the data never leave the database, but it needs the scoring code to run inside the database server, which a bank may not allow.`);
  li("Application tier", `Decides in ${fmtMs(a.application.p50_ms)} and needs nothing special in the database, but it fetches stored data across the network, which costs more the further away the database is (section 4).`);

  document.getElementById("baselineHint").textContent =
    `${b.transactions.toLocaleString()} transactions at ${b.rate_per_s} per second over one connection; median of ${b.runs} runs. ` +
    `A batch job that polls every ${b.batch_interval_s} seconds cannot decide faster than its polling interval; scoring on arrival decides in tens of milliseconds. The scores were identical in all three. ` +
    "Decision latency is the time from a transaction's scheduled arrival to the moment its score is saved. The 95th percentile is the delay that 19 transactions in 20 beat.";
  document.getElementById("baselinePanel").hidden = false;
}

// ---------- section 3: what happens as the load rises ----------

// One sentence, read from the data: where the two designs that score on arrival stopped keeping up with the fewest connections
function loadTake(s) {
  const connectionsAvailable = [...new Set(s.points.map((p) => p.connections))].sort((a, b) => a - b);
  const fewest = connectionsAvailable[0];
  const firstSaturated = (mode) => {
    const hit = s.points.filter((p) => p.connections === fewest).sort((a, b) => a.rate_per_s - b.rate_per_s)
      .find((p) => p.architectures[mode].saturated);
    return hit ? hit.rate_per_s : null;
  };
  const inDb = firstSaturated("in_database"), inApp = firstSaturated("application");
  const conn = plural(fewest, "connection");
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
  return take;
}

// What the chart shows for the connection count that is selected
function sweepReading(points, selected) {
  const rates = points.map((p) => p.rate_per_s);
  const batch = points.map((p) => p.architectures.external_batch.p50_ms);
  const arrivalOk = points.filter((p) => !p.architectures.in_database.saturated && !p.architectures.application.saturated);
  const behind = points.filter((p) => p.architectures.in_database.saturated || p.architectures.application.saturated);
  const parts = [];
  if (arrivalOk.length) {
    const medians = arrivalOk.flatMap((p) => [p.architectures.in_database.p50_ms, p.architectures.application.p50_ms]);
    parts.push(`Up to ${Math.max(...arrivalOk.map((p) => p.rate_per_s))} transactions a second, scoring inside the database and in the application both decided in ${fmtMs(Math.min(...medians))} to ${fmtMs(Math.max(...medians))}.`);
  }
  if (behind.length) {
    const first = behind[0];
    const who = [first.architectures.in_database.saturated ? "inside the database" : null, first.architectures.application.saturated ? "in the application" : null].filter(Boolean).join(" and ");
    parts.push(`At ${first.rate_per_s} a second, scoring ${who} fell behind: transactions queued, and the median delay grew to ${fmtMs(Math.max(...[first.architectures.in_database, first.architectures.application].filter((r) => r.saturated).map((r) => r.p50_ms)))}.`);
  } else {
    parts.push(`With ${plural(selected, "connection")}, both kept up at every rate tested.`);
  }
  parts.push(`The batch job stayed between ${fmtMs(Math.min(...batch))} and ${fmtMs(Math.max(...batch))}, set by its timer. Nothing above ${Math.max(...rates)} a second was tested.`);
  return parts.join(" ");
}

function renderSweep(s) {
  const connectionsAvailable = [...new Set(s.points.map((p) => p.connections))].sort((a, b) => a - b);
  let selected = connectionsAvailable[0];
  const pills = document.getElementById("connectionPills");
  document.getElementById("sweepTake").textContent = loadTake(s);

  function draw() {
    clear(pills);
    connectionsAvailable.forEach((c) => {
      const pill = h("button", { type: "button", class: `pill${c === selected ? " active" : ""}`, "aria-pressed": String(c === selected) },
        plural(c, "connection"));
      pill.addEventListener("click", () => { selected = c; draw(); });
      pills.append(pill);
    });

    const points = s.points.filter((p) => p.connections === selected).sort((a, b) => a.rate_per_s - b.rate_per_s);
    const categories = points.map((p) => `${p.rate_per_s}/s`);
    lineChart(document.getElementById("sweepChart"), {
      categories,
      series: MODES.map((mode) => ({
        color: MODE_COLOR[mode],
        points: points.map((p, i) => ({ i, y: p.architectures[mode].p50_ms, saturated: p.architectures[mode].saturated })),
      })),
      yTicks: [10, 100, 1000, 10000, 100000], yFormat: fmtMs, yMin: 10, yMax: 100000, logY: true,
      xTitle: "Transactions arriving per second", yTitle: "Median decision latency",
      label: `Median decision latency against arrival rate with ${plural(selected, "connection")}, for three architectures`,
    });
    legend(document.getElementById("sweepLegend"),
      MODES.map((m) => ({ name: MODE_LABEL[m], color: MODE_COLOR[m] })),
      "A red ring marks a load the architecture could not keep up with: a backlog built up, so delays grew.");
    document.getElementById("sweepRead").textContent = sweepReading(points, selected);

    document.getElementById("sweepHint").textContent =
      `${plural(selected, "connection")} sharing the arrivals; about ${s.duration_s} seconds of transactions per run, median of ${s.runs_per_cell} runs. ` +
      "The vertical scale is logarithmic: each gridline is ten times the one below.";

    const holder = document.getElementById("sweepTable");
    clear(holder);
    holder.append(table(["Arrivals per second", "External batch", "In-database", "Application tier"],
      points.map((p) => [`${p.rate_per_s}`, ...MODES.map((m) => latencyCell(p.architectures[m]))])));
    holder.append(h("p", { class: "table-note" }, "Each cell: median / 99th percentile decision latency."));
  }
  draw();

  // memory and processor cost against connections, at the one rate every connection count was tested
  const REFERENCE_RATE = 80;
  const reference = s.points.filter((p) => p.rate_per_s === REFERENCE_RATE).sort((a, b) => a.connections - b.connections);
  const cost = document.getElementById("costTable");
  clear(cost);
  if (reference.length > 1) {
    const xs = reference.map((p) => `${p.connections}`);
    const memTicks = niceTicks(Math.max(...reference.flatMap((p) => MODES.map((m) => p.architectures[m].memory_mb))));
    const cpuTicks = niceTicks(Math.max(...reference.flatMap((p) => MODES.map((m) => p.architectures[m].cpu_s_per_1000))));
    const costLine = (key) => MODES.map((m) => ({ color: MODE_COLOR[m], points: reference.map((p, i) => ({ i, y: p.architectures[m][key] })) }));
    lineChart(document.getElementById("memoryChart"), {
      categories: xs, series: costLine("memory_mb"),
      yTicks: memTicks.ticks, yFormat: (v) => `${v}`, yMin: 0, yMax: memTicks.top, logY: false,
      xTitle: "Scoring connections", yTitle: "Peak memory (MB)",
      label: "Peak memory in megabytes against the number of scoring connections, for three architectures, at 80 transactions per second",
    });
    lineChart(document.getElementById("cpuChart"), {
      categories: xs, series: costLine("cpu_s_per_1000"),
      yTicks: cpuTicks.ticks, yFormat: (v) => `${v}`, yMin: 0, yMax: cpuTicks.top, logY: false,
      xTitle: "Scoring connections", yTitle: "Processor seconds per 1,000 transactions",
      label: "Processor seconds per 1,000 transactions against the number of scoring connections, for three architectures, at 80 transactions per second",
    });
    legend(document.getElementById("costLegend"), MODES.map((m) => ({ name: MODE_LABEL[m], color: MODE_COLOR[m] })));
    const first = reference[0], last = reference[reference.length - 1];
    const batchMemory = reference.map((p) => p.architectures.external_batch.memory_mb);
    document.getElementById("costRead").textContent =
      `Memory grew with the number of scoring connections: from ${Math.round(first.architectures.in_database.memory_mb)} MB with ${plural(first.connections, "connection")} to ${Math.round(last.architectures.in_database.memory_mb)} MB with ${last.connections} for the in-database design, ` +
      `and from ${Math.round(first.architectures.application.memory_mb)} MB to ${Math.round(last.architectures.application.memory_mb)} MB for the application tier. The batch job stayed between ${Math.round(Math.min(...batchMemory))} and ${Math.round(Math.max(...batchMemory))} MB. ` +
      `Each scoring connection holds its own copy of the model libraries. All figures are at ${REFERENCE_RATE} transactions a second.`;
    cost.append(table(["Connections", "Batch: memory / CPU", "In-database: memory / CPU", "Application tier: memory / CPU"],
      reference.map((p) => [`${p.connections}`, ...MODES.map((m) =>
        `${Math.round(p.architectures[m].memory_mb)} MB / ${fmtNum(p.architectures[m].cpu_s_per_1000, 1)} s per 1,000`)])));
  }
  document.getElementById("sweepPanel").hidden = false;
}

// ---------- section 4: distance between the application and the database ----------

function renderNetwork(n) {
  const roundTrips = [...new Set(n.points.map((p) => Math.round(p.round_trip_ms)))].sort((a, b) => a - b);
  const readCounts = [...new Set(n.points.map((p) => p.reads))].sort((a, b) => a - b);
  const maxReads = readCounts[readCounts.length - 1];
  const find = (rt, reads) => n.points.find((p) => Math.round(p.round_trip_ms) === rt && p.reads === reads);
  const farthestRt = roundTrips[roundTrips.length - 1];
  const farthest = find(farthestRt, maxReads), farthestNone = find(farthestRt, 0);
  document.getElementById("networkTake").textContent = farthest
    ? `With ${plural(maxReads, "lookup")} per transaction and a round trip of ${farthestRt} ms, the application tier took ${fmtMs(farthest.architectures.application.p50_ms)} against ${fmtMs(farthest.architectures.in_database.p50_ms)} for the in-database design.`
    : "The further the database is from the application, the longer the application tier waits on each lookup.";
  document.getElementById("networkWhy").textContent =
    "A round trip is the time for a request to reach the database and the reply to come back. Every design pays one round trip to store a transaction. " +
    `The application tier also pays one for each stored-data lookup it makes before scoring (here ${maxReads}), because it asks the database from a distance; the in-database design makes those lookups locally, so they cost it almost nothing.`;

  const line = (mode, reads, dashed) => ({
    color: MODE_COLOR[mode], dashed,
    points: roundTrips.map((rt, i) => ({ i, y: (find(rt, reads) || { architectures: {} }).architectures[mode]?.p50_ms })),
  });
  lineChart(document.getElementById("networkChart"), {
    categories: roundTrips.map((rt) => `${rt} ms`),
    series: [line("in_database", 0, true), line("application", 0, true), line("in_database", maxReads, false), line("application", maxReads, false)],
    yTicks: [0, 100, 200, 300, 400, 500], yFormat: (v) => `${v} ms`, yMin: 0, yMax: 500, logY: false,
    xTitle: "Round trip between application and database", yTitle: "Median decision latency",
    label: "Median decision latency against network round trip, with and without database reads before scoring",
  });
  legend(document.getElementById("networkLegend"), [
    { name: "In-database, no reads", color: MODE_COLOR.in_database, dashed: true },
    { name: "Application tier, no reads", color: MODE_COLOR.application, dashed: true },
    { name: `In-database, ${plural(maxReads, "read")}`, color: MODE_COLOR.in_database },
    { name: `Application tier, ${plural(maxReads, "read")}`, color: MODE_COLOR.application },
  ], "The in-database lines overlap.");

  if (farthest && farthestNone) {
    const appNone = farthestNone.architectures.application.p50_ms, appReads = farthest.architectures.application.p50_ms;
    const dbNone = farthestNone.architectures.in_database.p50_ms, dbReads = farthest.architectures.in_database.p50_ms;
    const extra = appReads - appNone, trips = maxReads * farthestRt;
    const comparable = Math.abs(extra - trips) <= trips * 0.15;
    document.getElementById("networkRead").textContent =
      `At the longest round trip tested (${farthestRt} ms), the application tier took ${fmtMs(appNone)} with no lookups and ${fmtMs(appReads)} with ${plural(maxReads, "lookup")}: ${fmtMs(extra)} more` +
      `${comparable ? `, about the cost of ${plural(maxReads, "round trip")} (${maxReads} × ${farthestRt} = ${trips} ms)` : ""}. ` +
      `The in-database design took ${fmtMs(dbNone)} and ${fmtMs(dbReads)}, so the lookups added almost nothing. The batch job stayed near ${fmtMs(farthest.architectures.external_batch.p50_ms)}. ` +
      `Only round trips from ${roundTrips[0]} to ${farthestRt} ms were tested.`;
  }
  document.getElementById("networkHint").textContent =
    `A delaying relay was placed between the application and the database, on the same machine. ${n.transactions} transactions per run at ${n.rate_per_s} per second over ${n.connections} connections; median of ${n.runs_per_cell} runs. ` +
    "“Reads” are stored-data lookups each transaction needs before scoring: the application tier pays one round trip for each, the in-database trigger reads them locally. " +
    "The reads are stand-ins chosen by the study, not a measurement of any bank.";

  const rows = [];
  roundTrips.forEach((rt) => readCounts.forEach((reads) => {
    const p = find(rt, reads);
    if (!p) return;
    rows.push([`${rt} ms`, `${reads}`, ...MODES.map((m) => fmtMs(p.architectures[m].p50_ms))]);
  }));
  const holder = document.getElementById("networkTable");
  clear(holder);
  holder.append(table(["Round trip", "Reads", "External batch", "In-database", "Application tier"], rows));
  holder.append(h("p", { class: "table-note" }, "Each cell: median decision latency."));
  document.getElementById("networkPanel").hidden = false;
}

// ---------- the verdict and the short summary ----------

// The verdict, worked out from every condition the study tested (light load, load sweep, distance test).
// Two on-arrival designs are "about equal" when their medians are within 10% of each other.
function verdictText(results) {
  const conditions = [];
  const add = (arch) => {
    if (!arch || !arch.external_batch || !arch.in_database || !arch.application) return;
    conditions.push({
      batch: arch.external_batch.p50_ms, db: arch.in_database.p50_ms, app: arch.application.p50_ms,
      overloaded: Boolean(arch.in_database.saturated || arch.application.saturated),
    });
  };
  if (results.baseline) add(results.baseline.architectures);
  if (results.sweep) results.sweep.points.forEach((p) => add(p.architectures));
  if (results.network) results.network.points.forEach((p) => add(p.architectures));
  if (conditions.length < 2 || conditions.some((c) => [c.batch, c.db, c.app].some((v) => typeof v !== "number"))) return "";

  const dbFaster = conditions.filter((c) => c.db / c.app < 0.9).length;
  const appFaster = conditions.filter((c) => c.db / c.app > 1.1).length;
  const total = conditions.length;
  const equal = total - dbFaster - appFaster;
  let first;
  if (dbFaster > appFaster) {
    first = `Fastest: scoring inside the database. On decision time it matched or beat the application in ${total - appFaster} of the ${total} conditions tested (within 10% of each other in ${equal}), but speed is not the only thing to weigh.`;
  } else if (appFaster > dbFaster) {
    first = `Fastest: scoring in the application. On decision time it matched or beat the database in ${total - dbFaster} of the ${total} conditions tested (within 10% of each other in ${equal}), but speed is not the only thing to weigh.`;
  } else {
    first = "Scoring inside the database and in the application were about equally fast.";
  }
  const keptUp = conditions.filter((c) => !c.overloaded);
  const batchSlower = keptUp.filter((c) => c.batch > Math.max(c.db, c.app)).length;
  let second = `A batch job was slower than both whenever they kept up (${batchSlower} of ${keptUp.length}).`;
  if (conditions.some((c) => c.overloaded)) second += " When they were overloaded they fell behind and could be slower than the batch job.";
  return `${first} ${second}`;
}

// Five labelled lines at the top, one for each thing the study measured, built from the same result files as everything below
function renderSummary(results) {
  document.getElementById("summaryVerdict").textContent = verdictText(results);
  const items = [];
  const add = (label, text) => items.push({ label, text });
  const b = results.baseline && results.baseline.architectures;

  if (results.detection) {
    const m = results.detection.metrics;
    const same = b && MODES.every((mode) => b[mode].max_score_difference === 0);
    add("Detection",
      `The model found ${pct(m.recall.value)} of the frauds in a test of ${results.detection.test_transactions.toLocaleString()} transactions (${results.detection.test_frauds} frauds), and about ${pct(m.precision.value)} of what it flagged was fraud; AUC-ROC was ${fmtNum(m.roc_auc && m.roc_auc.value, 3)}. ` +
      `${same ? "All three architectures gave identical scores, so this does not depend on where the scoring runs." : "This is about the model, not about where it runs."}`);
  }
  if (b) {
    add("Speed at a light load",
      `A batch job takes about ${fmtMs(b.external_batch.p50_ms)} to reach a decision; scoring as the transaction arrives takes ${onArrivalPhrase(b.in_database.p50_ms, b.application.p50_ms)}.`);
  }
  if (results.sweep) {
    const batch = results.sweep.points.map((p) => p.architectures.external_batch.p50_ms);
    add("As the load rises", `${loadTake(results.sweep)} The batch job stayed between ${fmtMs(Math.min(...batch))} and ${fmtMs(Math.max(...batch))} at every load tested.`);
  }
  if (b) {
    const rate = results.baseline.rate_per_s;
    let text = `At ${rate} transactions a second the batch job used ${fmtNum(b.external_batch.cpu_s_per_1000, 2)} processor seconds per 1,000 transactions against ${fmtNum(b.in_database.cpu_s_per_1000, 1)} and ${fmtNum(b.application.cpu_s_per_1000, 1)} for the in-database and application designs.`;
    if (results.sweep) {
      const ref = results.sweep.points.filter((p) => p.rate_per_s === 80).sort((x, y) => x.connections - y.connections);   // the one rate every connection count was tested at
      if (ref.length > 1) {
        text += ` Memory grew with the number of scoring connections, from ${Math.round(ref[0].architectures.in_database.memory_mb)} MB to ${Math.round(ref[ref.length - 1].architectures.in_database.memory_mb)} MB for the in-database design (${ref[0].connections} to ${ref[ref.length - 1].connections} connections).`;
      }
    }
    add("Processor and memory", text);
  }
  if (results.network) {
    const trips = [...new Set(results.network.points.map((p) => Math.round(p.round_trip_ms)))].sort((a, c) => a - c);
    const far = results.network.points.find((p) => Math.round(p.round_trip_ms) === trips[trips.length - 1] && p.reads === 3);
    if (far) {
      add("Distance to the database",
        `Far from the database, the application waits on every lookup: ${fmtMs(far.architectures.application.p50_ms)} against ${fmtMs(far.architectures.in_database.p50_ms)} at a ${trips[trips.length - 1]} ms round trip.`);
    }
  }
  const list = document.getElementById("summaryList");
  clear(list);
  items.forEach((item) => list.append(h("li", {}, h("strong", { class: "summary-label" }, item.label), " ", item.text)));
  document.getElementById("summaryPanel").hidden = !items.length;
}

function renderNotes(summary) {
  const items = [
    "The data are a public dataset of European card transactions with anonymised features. They stand in for bank data and say nothing about fraud rates or patterns in Uganda.",
    summary.detection ? `The detection figures rest on ${summary.detection.test_frauds} frauds in the test set, so they are uncertain, as the intervals show.` : null,
    summary.sweep ? `All timings come from ${summary.sweep.machine}. The application and the database ran on that one machine; the distance test added a delaying relay between them. A real bank would run on different hardware, networks and loads.` : null,
    summary.sweep ? `The machine was not fully quiet: in the load sweep, ${summary.sweep.runs_started_busy} of ${summary.sweep.runs_total} runs started with the processor more than 25% busy. Medians held up better than the 99th-percentile figures at low loads.` : null,
    summary.network && summary.network.median_other_programs_cpu_percent !== null
      ? `In the distance test, other programs used a median of about ${summary.network.median_other_programs_cpu_percent}% of the processor during runs (a lower bound).` : null,
    "The distance test adds a fixed delay only: no bandwidth limit, jitter or packet loss. The round trips are measured values, and the lookups are stand-ins chosen by the study; neither is a figure from any Ugandan network or bank.",
    "The user evaluation was small and exploratory: three evaluators, none of whom works in fraud, risk or compliance. It shows what to improve first and does not show that users accept the system.",
    "These results describe scoring architectures under stated conditions. They do not establish fraud rates or operational performance for any Ugandan bank, and the prototype is not a validated banking deployment. Drift, explanations and real bank systems were not tested.",
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
    if (results.detection) renderDetection(results.detection, results.baseline);
    if (results.baseline) renderBaseline(results.baseline);
    if (results.sweep) renderSweep(results.sweep);
    if (results.network) renderNetwork(results.network);
    renderNotes(results);
    status.textContent = results.missing.length ? "Some results are not available." : "";
    status.hidden = !results.missing.length;
    redrawCharts();     // the panels are visible now, so each chart can be drawn for the width it really has
  } catch (err) {
    status.textContent = `Could not load the results: ${err.message}. If the service has been idle, wait a minute and reload.`;
  }
}

load();
