// "How this score was made": a step-by-step account of one analyzed
// transaction, drawn from the `explanation` the API returns with it
// (each model's score and weight, the figures each rule compared, and the
// condition that fixed the decision).
//
// Built with DOM calls and text nodes only, never by assigning markup
// strings, so nothing that came from the API can be read as markup.

(function () {
  const MODELS = {
    xgb: ["XGBoost", "Decision trees built one after another, each correcting the last, learned from labelled fraud."],
    lgb: ["LightGBM", "A second tree-based learner, trained on the same labelled data."],
    voting: ["Voting pair", "The XGBoost and LightGBM models averaged together."],
    iso: ["Isolation Forest", "Ignores the labels and asks how unusual the transaction is next to normal ones."],
  };

  function node(tag, className, text) {
    const e = document.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  const pct = (n) => `${(n * 100).toFixed(1)}%`;
  const num = (n) => (n < 10 && n !== Math.round(n)
    ? n.toFixed(2)
    : Math.round(n).toLocaleString());
  const isNum = (n) => typeof n === "number" && Number.isFinite(n);

  function step(number, title) {
    const section = node("div", "explain-step");
    const heading = node("h4", "explain-heading");
    heading.append(node("span", "explain-num", String(number)), document.createTextNode(title));
    section.append(heading);
    return section;
  }

  function modelsTable(models) {
    const wrap = node("div", "table-wrap");
    const table = node("table", "results-table explain-table");
    const head = node("tr");
    ["Model", "Its own score", "Weight", "Adds to the total"].forEach((t) => head.append(node("th", "", t)));
    const thead = node("thead");
    thead.append(head);
    table.append(thead);

    const body = node("tbody");
    models.components.forEach((c) => {
      const [name, what] = MODELS[c.model] || [c.model, ""];
      const row = node("tr");

      const label = node("td");
      label.append(node("div", "", name), node("div", "explain-what", what));

      const score = node("td");
      const bar = node("div", "score-bar");
      const fill = node("div", "score-fill");
      fill.style.width = `${Math.max(0, Math.min(1, c.score)) * 100}%`;
      bar.append(fill);
      score.append(node("div", "", pct(c.score)), bar);

      row.append(label, score, node("td", "", `${Math.round(c.weight * 100)}%`), node("td", "", pct(c.contribution)));
      body.append(row);
    });

    const total = node("tr", "explain-total");
    const label = node("td", "", "Fraud score");
    label.colSpan = 3;
    total.append(label, node("td", "", pct(models.final_score)));
    body.append(total);

    table.append(body);
    wrap.append(table);
    return wrap;
  }

  function ruleRow(fired, title, detail) {
    const row = node("li", "rule-row");
    row.append(
      node("span", `rule-state ${fired ? "fired" : "clear"}`, fired ? "Fired" : "Clear"),
      node("div", "rule-text"),
    );
    row.lastChild.append(node("strong", "", title), node("div", "explain-what", detail));
    return row;
  }

  function rulesList(flags, rules) {
    const list = node("ul", "rule-list");

    const a = rules.threshold_exceeded;
    if (a) {
      list.append(ruleRow(
        !!flags.threshold_exceeded,
        "Unusually large amount",
        `Amount ${num(a.amount)} against a limit of ${num(a.limit)}, which is five times this customer's average of ${num(a.customer_average)}.`,
      ));
    }

    const v = rules.velocity_anomaly;
    if (v) {
      list.append(ruleRow(
        !!flags.velocity_anomaly,
        "Too many transactions in an hour",
        `${v.recent_count} from this customer in the last hour; the rule fires above ${v.limit}.`,
      ));
    }

    const t = rules.unusual_time;
    if (t) {
      const hour = String(t.hour).padStart(2, "0");
      const hours = t.outside_hours
        ? `Hour ${hour}:00 is before 06:00 or after 22:00`
        : `Hour ${hour}:00 is within the 06:00 to 22:00 window`;
      list.append(ruleRow(
        !!flags.unusual_time,
        "Unusual time of day",
        `${hours}. The rule fires only at night-time hours, and only for a customer who transacts then less than ${pct(t.rate_limit)} of the time (this customer: ${pct(t.customer_night_rate)}).`,
      ));
    }

    return list;
  }

  window.renderExplanation = function (result) {
    const info = result && result.explanation;
    if (!info || !info.models || !Array.isArray(info.models.components)) return null;

    const root = node("div", "explain");
    root.append(node("h3", "explain-title", "How this score was made"));

    const inputs = step(1, "What the models are given");
    inputs.append(node("p", "", "Thirty numbers per transaction: the time of day, the 28 anonymized components from the source dataset, and the amount. The components carry no readable meaning, so the models cannot say which input drove a score; only which models and rules did."));

    const models = step(2, "Four models each give a score; a weighted average is the fraud score");
    models.append(modelsTable(info.models));
    models.append(node("p", "table-note", "A fifth model, a One-Class SVM, is trained but has no weight, so it does not affect the score. Above 0.5 counts as fraud; above 0.7 is sent for review."));

    const rules = step(3, "Three rule checks look at the customer's history");
    if (info.rules) rules.append(rulesList(result.sql_flags || {}, info.rules));
    rules.append(node("p", "table-note", "Only the model's score has been tested against known fraud labels; these rules and the decision labels have not."));

    const decision = step(4, "The decision");
    const line = node("p", "explain-decision");
    line.append(node("span", `badge decision-${/^[A-Z]+$/.test(result.decision) ? result.decision : "ALLOW"}`, String(result.decision)));
    line.append(document.createTextNode(` ${info.decision_reason || ""}`));
    decision.append(line);

    root.append(inputs, models, rules, decision);
    if (isNum(result.fraud_score)) root.dataset.score = String(result.fraud_score);
    return root;
  };
})();
