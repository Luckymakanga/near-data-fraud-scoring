// window.FRAUD_API_BASE (set in config.js) takes priority once deployed -
// the API and this static dashboard live on different hosts in production,
// so we can't just guess the API's URL from window.location like we can locally.
const API_BASE = window.FRAUD_API_BASE ||
  (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://localhost:5000"
    : `${window.location.protocol}//${window.location.hostname}:5000`);

const TOKEN_KEY = "fraudAdmin.token";

// Escape anything that came from the API (or a file) before it goes into HTML.
// Transaction and customer ids are stored from API callers, so they are untrusted.
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const el = {
  loginScreen: document.getElementById("loginScreen"),
  loginForm: document.getElementById("loginForm"),
  loginError: document.getElementById("loginError"),
  username: document.getElementById("username"),
  password: document.getElementById("password"),
  apiUrlHint: document.getElementById("apiUrlHint"),

  dashboard: document.getElementById("dashboard"),
  apiStatus: document.getElementById("apiStatus"),
  roleBadge: document.getElementById("roleBadge"),
  refreshBtn: document.getElementById("refreshBtn"),
  logoutBtn: document.getElementById("logoutBtn"),

  statTotal: document.getElementById("statTotal"),
  statFraudCount: document.getElementById("statFraudCount"),
  statFraudRate: document.getElementById("statFraudRate"),
  statBlocked: document.getElementById("statBlocked"),
  statPrevention: document.getElementById("statPrevention"),

  analyzeForm: document.getElementById("analyzeForm"),
  aCustomer: document.getElementById("aCustomer"),
  loadSampleBtn: document.getElementById("loadSampleBtn"),
  analyzeBtn: document.getElementById("analyzeBtn"),
  samplePreview: document.getElementById("samplePreview"),
  analyzeResult: document.getElementById("analyzeResult"),
  analyzeExplainBox: document.getElementById("analyzeExplainBox"),
  analyzeExplain: document.getElementById("analyzeExplain"),

  autoRefresh: document.getElementById("autoRefresh"),
  filterPills: document.getElementById("filterPills"),
  txTableBody: document.getElementById("txTableBody"),
  patternList: document.getElementById("patternList"),

  lookupForm: document.getElementById("lookupForm"),
  lCustomer: document.getElementById("lCustomer"),
  profileCard: document.getElementById("profileCard"),

  uploadForm: document.getElementById("uploadForm"),
  uCustomer: document.getElementById("uCustomer"),
  uFile: document.getElementById("uFile"),
  uploadBtn: document.getElementById("uploadBtn"),
  uploadResult: document.getElementById("uploadResult"),
  uploadTableWrap: document.getElementById("uploadTableWrap"),
  uploadTableBody: document.getElementById("uploadTableBody"),

  resetForm: document.getElementById("resetForm"),
  resetConfirm: document.getElementById("resetConfirm"),
  resetBtn: document.getElementById("resetBtn"),
  resetNote: document.getElementById("resetNote"),

  toast: document.getElementById("toast"),
};

el.apiUrlHint.textContent = API_BASE;

let refreshTimer = null;

function getToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

function setToken(token) {
  sessionStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(ROLE_KEY);
}

// The role comes with the sign-in: admin can do everything, an analyst can analyze and upload but not delete,
// and a viewer can only read. Hiding what a role cannot use is for clarity; the server enforces the role itself.
const ROLE_KEY = "fraudAdmin.role";
const ROLE_LABEL = { admin: "Admin", analyst: "Analyst", viewer: "Viewer (read-only)" };

function applyRole() {
  const stored = sessionStorage.getItem(ROLE_KEY);
  const role = ROLE_LABEL[stored] ? stored : "viewer";      // a session without a known role is treated as read-only
  const show = (form, allowed) => {
    const panel = form.closest("section");
    if (panel) panel.hidden = !allowed;
  };
  show(el.analyzeForm, role === "admin" || role === "analyst");
  show(el.uploadForm, role === "admin" || role === "analyst");
  show(el.resetForm, role === "admin");
  el.roleBadge.textContent = ROLE_LABEL[role];
  el.roleBadge.hidden = false;
}

function showToast(msg) {
  el.toast.textContent = msg;
  el.toast.classList.add("show");
  setTimeout(() => el.toast.classList.remove("show"), 2400);
}

async function apiFetch(path, options = {}) {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });

  if (res.status === 401) {
    clearToken();
    showLogin("Session expired — please sign in again.");
    throw new Error("Unauthorized");
  }

  const data = await res.json().catch(() => ({}));
  if (res.status === 429) {
    throw new Error("Too many requests - please wait a few minutes, then refresh.");
  }
  if (!res.ok) {
    const reference = data.error_id ? ` (reference ${data.error_id})` : "";
    throw new Error((data.error || `Request failed (${res.status})`) + reference);
  }
  return data;
}

function showLogin(message) {
  el.dashboard.hidden = true;
  el.loginScreen.hidden = false;
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
  if (message) {
    el.loginError.textContent = message;
    el.loginError.hidden = false;
  }
}

function showDashboard() {
  el.loginScreen.hidden = true;
  el.dashboard.hidden = false;
  applyRole();
  loadAll();
  if (el.autoRefresh.checked) startAutoRefresh();
}

const REFRESH_SECONDS = 30;

function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {
    if (!document.hidden) loadAll();   // a background tab does not need fresh numbers
  }, REFRESH_SECONDS * 1000);
}

function stopAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = null;
}

el.autoRefresh.addEventListener("change", () => {
  if (el.autoRefresh.checked) startAutoRefresh();
  else stopAutoRefresh();
});

// ---------- Login ----------

el.loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  el.loginError.hidden = true;

  try {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: el.username.value,
        password: el.password.value,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Login failed");

    setToken(data.token);
    sessionStorage.setItem(ROLE_KEY, typeof data.role === "string" ? data.role : "viewer");
    showDashboard();
  } catch (err) {
    el.loginError.textContent = err.message.includes("fetch")
      ? `Can't reach the API at ${API_BASE}. Is api_server.py running?`
      : err.message;
    el.loginError.hidden = false;
  }
});

el.logoutBtn.addEventListener("click", () => {
  clearToken();
  showLogin();
});

// The About panel starts open for a new visitor and stays as they leave it
const aboutPanel = document.getElementById("aboutPanel");
try {
  if (localStorage.getItem("fraudAdmin.aboutClosed") === "1") aboutPanel.open = false;
} catch (e) { /* storage may be blocked; the panel just stays open */ }
aboutPanel.addEventListener("toggle", () => {
  try { localStorage.setItem("fraudAdmin.aboutClosed", aboutPanel.open ? "0" : "1"); } catch (e) { /* ignore */ }
});

el.refreshBtn.addEventListener("click", async () => {
  el.refreshBtn.disabled = true;
  el.refreshBtn.textContent = "Refreshing…";
  try {
    if (await loadAll()) showToast("Dashboard updated");
  } finally {
    el.refreshBtn.disabled = false;
    el.refreshBtn.textContent = "Refresh";
  }
});

// ---------- Health check ----------

async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (!res.ok) throw new Error();
    el.apiStatus.className = "api-status online";
    el.apiStatus.innerHTML = `<span class="dot"></span> API online`;
  } catch {
    el.apiStatus.className = "api-status offline";
    el.apiStatus.innerHTML = `<span class="dot"></span> API unreachable`;
  }
}

// ---------- Stats ----------

function fmtPct(n) {
  return `${(n * 100).toFixed(1)}%`;
}

async function loadStats() {
  const { statistics } = await apiFetch("/api/statistics/fraud");
  el.statTotal.textContent = statistics.total_transactions ?? "–";
  el.statFraudCount.textContent = statistics.fraud_count ?? "–";
  el.statFraudRate.textContent = typeof statistics.fraud_rate === "number" ? fmtPct(statistics.fraud_rate) : "–";
  el.statBlocked.textContent = statistics.blocked ?? "–";
  el.statPrevention.textContent = typeof statistics.prevention_rate === "number" ? fmtPct(statistics.prevention_rate) : "–";
}

// ---------- Transactions table ----------

function fmtTime(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (isNaN(d)) return esc(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// Amounts are shown in UGX for the demonstration, at window.DEMO_UGX_PER_UNIT shillings for each
// unit of the dataset's amount (set in explain.js, and used by the stored reasons too). The stored
// amount, the model's inputs and the rule checks are not scaled; only how it is written.
function fmtAmount(n) {
  if (typeof n !== "number") return "–";
  return `UGX ${Math.round(n * window.DEMO_UGX_PER_UNIT).toLocaleString("en-US")}`;
}

// The stored score is 0 to 1 and is not changed; it is only shown as a number out of 100.
// The ensemble's weighted average has not been calibrated, so it is called a Risk Score,
// never a probability.
function fmtScore(n) {
  if (typeof n !== "number") return "–";
  return `${(n * 100).toFixed(1)}/100`;
}

// The cut-offs the decision logic uses (fraud_detection_system.py, _decide), out of 100
const SCORE_THRESHOLDS = { fraud: 50, review: 70 };

function fmtTimeOfDay(seconds) {
  if (typeof seconds !== "number") return "–";
  const totalSeconds = Math.floor(seconds % 86400);
  const h = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  return `${h}:${m}`;
}

// The date and time of the transaction itself. The dataset's Time is the seconds since its
// first transaction, over two days in September 2013 (it gives the month, not the exact day,
// so its first day is shown as 1 September). The date and the time of day come from the same
// number, so the Date and Time column always agrees with the Time of Day column.
const TRANSACTION_CLOCK_START = Date.UTC(2013, 8, 1);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function fmtDateTime(seconds) {
  if (typeof seconds !== "number") return "–";
  const d = new Date(TRANSACTION_CLOCK_START + Math.floor(seconds) * 1000);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${fmtTimeOfDay(seconds)}`;
}

const DECISION_WORDS = { BLOCK: "blocked", REVIEW: "sent for review", MONITOR: "put on monitor", ALLOW: "allowed" };
const openDetails = new Set();   // transactions whose reason is open, kept across refreshes

let decisionFilter = "";

async function loadTransactions() {
  const query = decisionFilter ? `&decision=${decisionFilter}` : "";
  const { transactions } = await apiFetch(`/api/transactions/recent?limit=25${query}`);

  if (!transactions.length) {
    const emptyMsg = decisionFilter
      ? `No ${decisionFilter} transactions yet.`
      : "No transactions yet — analyze one above, or run the full system to generate sample data.";
    el.txTableBody.innerHTML = `<tr><td colspan="6" class="table-empty">${emptyMsg}</td></tr>`;
    return;
  }

  el.txTableBody.innerHTML = transactions
    .map((tx) => {
      const decision = esc(tx.decision || "—");
      const customerId = esc(tx.customer_id ?? "");
      const id = esc(tx.transaction_id ?? "");
      // the transaction's own date and time; a row without one shows when it was processed
      const when = typeof tx.txn_time === "number" ? fmtDateTime(tx.txn_time) : fmtTime(tx.timestamp);
      const open = openDetails.has(tx.transaction_id);
      const word = DECISION_WORDS[tx.decision] || "decided";
      // the stored reason is shown as it is; when none was stored, say so and invent nothing
      const reason = tx.reason
        ? `<p class="why-reason">${esc(tx.reason)}</p>`
        : `<p class="why-reason why-missing"><strong>Explanation unavailable.</strong> No reason was stored for this transaction because it was analyzed before the system began keeping reasons. Analyze it again to get one.</p>`;
      return `
        <tr class="tx-row${open ? " selected" : ""}">
          <td data-label="Date &amp; Time" title="Processed ${esc(fmtTime(tx.timestamp))}">${when}</td>
          <td data-label="Transaction ID"><code>${id || "–"}</code></td>
          <td data-label="Customer">${customerId ? `<button type="button" class="customer-link" data-customer="${customerId}">${customerId}</button>` : "–"}</td>
          <td data-label="Amount">${fmtAmount(tx.amount)}</td>
          <td data-label="Risk Score">${fmtScore(tx.fraud_score)}</td>
          <td data-label="Decision"><button type="button" class="badge decision-btn decision-${decision}" data-tx="${id}" aria-expanded="${open}" title="Select to see why">${decision}</button></td>
        </tr>
        <tr class="tx-detail"${open ? "" : " hidden"}>
          <td colspan="6">
            <div class="why-box decision-${decision}">
              <h4 class="why-title">Why this transaction was ${word}</h4>
              <div class="why-flow" aria-label="Risk score leads to decision">
                <div class="why-tile"><span class="why-label">Risk Score</span><strong>${fmtScore(tx.fraud_score)}</strong></div>
                <span class="why-arrow" aria-hidden="true">→</span>
                <div class="why-tile"><span class="why-label">System decision</span><span class="badge decision-${decision}">${decision}</span></div>
              </div>
              <div class="why-section"><span class="why-label">Reason</span>${reason}</div>
              <div class="why-section"><span class="why-label">How the decision is reached</span>
                <p class="why-meta">A risk score above ${SCORE_THRESHOLDS.fraud} counts as a fraud signal and above ${SCORE_THRESHOLDS.review} is sent for review. The three rule checks count as well, so the score alone does not fix the decision.</p></div>
              <div class="why-section"><span class="why-label">Transaction</span>
                <p class="why-meta">${id || "–"} · ${customerId || "no customer"} · amount ${fmtAmount(tx.amount)} · ${when}</p></div>
            </div>
          </td>
        </tr>`;
    })
    .join("");
}

function toggleDetails(row) {
  const button = row.querySelector(".decision-btn");
  const detail = row.nextElementSibling;
  if (!button || !detail) return;
  const open = detail.hidden;                        // it is about to open
  detail.hidden = !open;
  row.classList.toggle("selected", open);
  button.setAttribute("aria-expanded", String(open));
  if (open) openDetails.add(button.dataset.tx);
  else openDetails.delete(button.dataset.tx);
}

el.txTableBody.addEventListener("click", (e) => {
  const link = e.target.closest(".customer-link");
  if (link) {
    el.lCustomer.value = link.dataset.customer;
    lookupCustomer(link.dataset.customer);
    el.profileCard.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  // the decision button, or anywhere else on the row, opens the reason under it
  const row = e.target.closest("tr.tx-row");
  if (row) toggleDetails(row);
});

el.filterPills.addEventListener("click", (e) => {
  const pill = e.target.closest(".pill");
  if (!pill) return;

  decisionFilter = pill.dataset.decision;
  el.filterPills.querySelectorAll(".pill").forEach((p) => p.classList.toggle("active", p === pill));
  loadTransactions().catch((err) => {
    if (err.message !== "Unauthorized") showToast(err.message);
  });
});

// ---------- Fraud patterns ----------

async function loadPatterns() {
  const { patterns } = await apiFetch("/api/statistics/patterns");

  if (!patterns || !patterns.length) {
    el.patternList.innerHTML = `<li class="table-empty">No patterns detected yet.</li>`;
    return;
  }

  el.patternList.innerHTML = patterns
    .slice(0, 5)
    .map((p) => `<li><span>${esc(p.pattern)}</span><span class="pattern-count">${esc(p.count)} cases</span></li>`)
    .join("");
}

// ---------- Customer risk profile lookup ----------

function fmtFreq(n) {
  if (typeof n !== "number") return "–";
  return `${(n * 100).toFixed(0)}%`;
}

// The overall risk on a customer's record is one of three labels the system stores:
// LOW_RISK, NORMAL and HIGH_ACTIVITY. They are shown as LOW, MEDIUM and HIGH RISK (a wording
// change only; the stored label is shown beside it and nothing is recalculated). A label that
// is missing or not one of these is shown as it is, never replaced by a guess.
const CUSTOMER_RISK = {
  LOW_RISK: { word: "LOW RISK", level: "LOW" },
  NORMAL: { word: "MEDIUM RISK", level: "MEDIUM" },
  HIGH_ACTIVITY: { word: "HIGH RISK", level: "HIGH" },
};

function customerRisk(stored) {
  if (CUSTOMER_RISK[stored]) return { ...CUSTOMER_RISK[stored], stored };
  return { word: stored ? String(stored).replace(/_/g, " ") : "NOT CLASSIFIED", level: "NONE", stored: stored || null };
}

// How many of a customer's recent decisions fall in each category, counted from the list the
// API returned (the latest ten at most); nothing is added.
const DECISION_SUMMARY = [
  ["ALLOW", "Allowed"],
  ["REVIEW", "Sent for review"],
  ["BLOCK", "Blocked"],
  ["MONITOR", "On monitor"],
];

function countDecisions(list) {
  const counts = { ALLOW: 0, REVIEW: 0, BLOCK: 0, MONITOR: 0 };
  (list || []).forEach((d) => { if (d in counts) counts[d] += 1; });
  return counts;
}

async function lookupCustomer(customerId) {
  el.profileCard.hidden = false;
  el.profileCard.className = "profile-card";
  el.profileCard.textContent = "Loading…";

  try {
    const { profile } = await apiFetch(`/api/customers/${encodeURIComponent(customerId)}/risk-profile`);

    // a customer with no record comes back without a name; the name itself is never shown
    if (!profile || !profile.name) {
      el.profileCard.className = "profile-card not-found";
      el.profileCard.textContent = `No profile on file for ${customerId} — this customer has no transaction history yet.`;
      return;
    }

    const risk = customerRisk(profile.risk_level);
    const recent = Array.isArray(profile.recent_decisions) ? profile.recent_decisions : [];
    const counts = countDecisions(recent);
    const summary = DECISION_SUMMARY
      .map(([key, word]) => `<li class="count-item${counts[key] ? "" : " zero"}"><span class="badge decision-${key}">${esc(counts[key])}</span> ${esc(word)}</li>`)
      .join("");
    const chips = recent.map((d) => `<span class="badge decision-${esc(d)}">${esc(d)}</span>`).join("");

    el.profileCard.className = "profile-card";
    el.profileCard.innerHTML = `
      <div class="profile-head">
        <h3>Customer ID: ${esc(profile.customer_id)}</h3>
        <span class="profile-category">${esc(profile.account_type || "–")} customer</span>
      </div>

      <section class="profile-section">
        <h4 class="profile-heading">Overall Customer Risk</h4>
        <div class="risk-line">
          <span class="risk-badge risk-${risk.level}">${esc(risk.word)}</span>
          ${risk.stored ? `<span class="risk-stored">System classification: ${esc(risk.stored)}</span>` : ""}
        </div>
        <p class="profile-note">This is the customer&rsquo;s standing risk profile, held on their record. It is not the result of any single transaction, so one blocked transaction does not change it.</p>
      </section>

      <section class="profile-section">
        <h4 class="profile-heading">Risk Indicators</h4>
        <div class="profile-grid">
          <div class="profile-field">
            <span class="field-label">Average transaction amount</span>
            <span class="field-value">${fmtAmount(profile.avg_transaction)}</span>
          </div>
          <div class="profile-field">
            <span class="field-label">Last transaction location</span>
            <span class="field-value">${esc(profile.last_location || "–")}</span>
          </div>
          <div class="profile-field">
            <span class="field-label">Unusual-hours transactions</span>
            <span class="field-value">${fmtFreq(profile.unusual_hours_frequency)}${typeof profile.unusual_hours_frequency === "number" ? " of transactions" : ""}</span>
          </div>
        </div>
      </section>

      <section class="profile-section">
        <h4 class="profile-heading">Recent Transaction Decisions</h4>
        ${recent.length
          ? `<ul class="count-list" aria-label="Decisions on this customer's latest ${recent.length} transactions">${summary}</ul>
             <div class="profile-merchants" aria-label="Newest first">${chips}</div>
             <p class="profile-note">Counts cover this customer&rsquo;s latest ${recent.length} analyzed transaction${recent.length === 1 ? "" : "s"}, newest first. Each is a decision on one transaction, separate from the overall risk above: a customer can be LOW RISK overall and still have a transaction blocked.</p>`
          : `<p class="profile-note">No transactions have been analyzed for this customer yet.</p>`}
      </section>
    `;
  } catch (err) {
    el.profileCard.className = "profile-card not-found";
    el.profileCard.textContent = `Error: ${err.message}`;
  }
}

el.lookupForm.addEventListener("submit", (e) => {
  e.preventDefault();
  if (!el.lCustomer.value) return;
  lookupCustomer(el.lCustomer.value);
});

// ---------- Analyze form ----------

let currentSample = null;
let currentSampleLabel = null;

el.loadSampleBtn.addEventListener("click", async () => {
  el.analyzeResult.hidden = true;
  el.analyzeExplainBox.hidden = true;
  el.samplePreview.hidden = false;
  el.samplePreview.textContent = "Loading a random transaction…";
  el.analyzeBtn.disabled = true;

  try {
    const { transaction, true_label } = await apiFetch("/api/transactions/sample");
    currentSample = transaction;
    currentSampleLabel = true_label;

    el.samplePreview.innerHTML = `
      Loaded <code>${esc(transaction.transaction_id)}</code> &mdash;
      amount ${fmtAmount(transaction.amount)}, ${fmtDateTime(transaction.Time)}.
      Pick a customer, then Analyze to see the model's verdict.
    `;
    el.analyzeBtn.disabled = !el.aCustomer.value;
  } catch (err) {
    el.samplePreview.textContent = `Error: ${err.message}`;
    currentSample = null;
  }
});

el.aCustomer.addEventListener("change", () => {
  el.analyzeBtn.disabled = !currentSample || !el.aCustomer.value;
});

el.analyzeForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentSample) return;
  el.analyzeResult.hidden = true;
  el.analyzeExplainBox.hidden = true;

  const body = { ...currentSample, customer_id: el.aCustomer.value };
  delete body.timestamp;

  try {
    const { result } = await apiFetch("/api/transactions/analyze", {
      method: "POST",
      body: JSON.stringify(body),
    });

    const matchNote = currentSampleLabel
      ? ` (actual label: <strong>${esc(currentSampleLabel)}</strong>)`
      : "";

    el.analyzeResult.className = `analyze-result decision-${esc(result.decision)}`;
    el.analyzeResult.innerHTML = `
      <div class="why-flow" aria-label="Risk score leads to decision">
        <div class="why-tile"><span class="why-label">Risk Score</span><strong>${fmtScore(result.fraud_score)}</strong></div>
        <span class="why-arrow" aria-hidden="true">→</span>
        <div class="why-tile"><span class="why-label">System decision</span><span class="badge decision-${esc(result.decision)}"><strong>${esc(result.decision)}</strong></span></div>
      </div>
      <p class="why-meta">For <code>${esc(result.transaction_id)}</code> (${esc(result.customer_id)}, amount ${fmtAmount(result.amount)})${matchNote}<br/>
      Rule checks that fired: ${Object.entries(result.sql_flags || {})
        .filter(([, v]) => v)
        .map(([k]) => esc(k))
        .join(", ") || "none"}</p>
    `;
    el.analyzeResult.hidden = false;

    const explanation = window.renderExplanation ? window.renderExplanation(result) : null;
    el.analyzeExplain.replaceChildren(...(explanation ? [explanation] : []));
    el.analyzeExplainBox.hidden = !explanation;

    currentSample = null;
    currentSampleLabel = null;
    el.analyzeBtn.disabled = true;

    showToast("Transaction analyzed");
    await Promise.all([loadStats(), loadTransactions()]);
  } catch (err) {
    el.analyzeResult.className = "analyze-result decision-BLOCK";
    el.analyzeResult.textContent = `Error: ${err.message}`;
    el.analyzeResult.hidden = false;
  }
});

// ---------- Upload dataset ----------

// Rows sent per request when a file is uploaded (the server accepts up to 500 at once)
const UPLOAD_CHUNK = 50;

const DEMO_CUSTOMERS = [
  "CUST001", "CUST002", "CUST003", "CUST004", "CUST005",
  "CUST006", "CUST007", "CUST008", "CUST009", "CUST010",
];

function parseCSV(text) {
  const lines = text.split(/\r\n|\n/).filter((line) => line.trim().length > 0);
  if (!lines.length) return [];

  const headers = lines[0].split(",").map((h) => h.trim());
  return lines.slice(1).map((line) => {
    const cells = line.split(",").map((c) => c.trim());
    const row = {};
    headers.forEach((h, i) => {
      row[h] = cells[i];
    });
    return row;
  });
}

el.uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = el.uFile.files[0];
  if (!file) return;

  el.uploadResult.hidden = false;
  el.uploadResult.className = "upload-result";
  el.uploadResult.textContent = "Reading file…";
  el.uploadTableWrap.hidden = true;
  el.uploadBtn.disabled = true;

  try {
    const text = await file.text();
    const rows = parseCSV(text);

    if (!rows.length) {
      throw new Error("No rows found in that file.");
    }

    const truncated = rows.length > 500;
    const useRows = rows.slice(0, 500);
    // Every row belongs to its own customer, fixed by its place in the file (row 1 is the first
    // demo customer, row 2 the second, and so on round again). The choice above only decides
    // which customer's rows are listed in the table under the form; all rows are analyzed and
    // saved under their own customers and all appear in Recent Transactions.
    const onlyCustomer = el.uCustomer.value !== "ALL" ? el.uCustomer.value : null;

    const trueLabels = new Map(); // transaction_id -> "FRAUD" | "NORMAL" | null

    const transactions = useRows.map((row, i) => {
      const transactionId = `TXN${Date.now().toString(36).toUpperCase()}${i}`;
      const customerId = DEMO_CUSTOMERS[i % DEMO_CUSTOMERS.length];

      if (row.Class !== undefined && row.Class !== "") {
        trueLabels.set(transactionId, Number(row.Class) === 1 ? "FRAUD" : "NORMAL");
      }

      const txn = { transaction_id: transactionId, customer_id: customerId };
      for (const [key, value] of Object.entries(row)) {
        if (key === "Class") continue;
        txn[key] = value === "" ? 0 : Number(value);
      }
      if (txn.Amount !== undefined) txn.amount = txn.Amount;
      return txn;
    });

    // A big file goes up in small chunks. The service scores a row in well under a second but
    // reads from a database that may be far away, so one 500-row request could run past the
    // host's time limit and hold up every other request while it ran. Chunks keep each request
    // short, show progress, and keep what was analyzed if one of them fails.
    const total = transactions.length;
    const results = [];
    const errors = [];
    let fraudCount = 0;
    let stoppedEarly = false;
    let failure = null;
    const started = Date.now();

    for (let offset = 0; offset < total; offset += UPLOAD_CHUNK) {
      const chunk = transactions.slice(offset, offset + UPLOAD_CHUNK);
      el.uploadResult.textContent =
        `Analyzing transactions ${offset + 1} to ${offset + chunk.length} of ${total}… ` +
        `${results.length} done so far. Please wait and do not upload again.`;
      try {
        const data = await apiFetch("/api/transactions/batch-analyze", {
          method: "POST",
          body: JSON.stringify({ transactions: chunk }),
        });
        results.push(...data.results);
        data.errors.forEach((e) => errors.push({ ...e, index: e.index + offset }));
        fraudCount += data.summary.fraud_count;
        if (data.summary.stopped_early) {
          stoppedEarly = true;
          break;
        }
      } catch (err) {
        if (err.message === "Unauthorized") throw err;
        failure = err.message;
        break;
      }
    }

    const seconds = ((Date.now() - started) / 1000).toFixed(0);
    const truncNote = truncated ? ` (first 500 of ${rows.length} rows)` : "";
    const errNote = errors.length ? `, ${errors.length} row${errors.length === 1 ? "" : "s"} skipped` : "";
    const problemNote = failure
      ? `<br/>Stopped after ${results.length} of ${total}: ${esc(failure)}. The ${results.length} analyzed are shown and saved.`
      : stoppedEarly
        ? `<br/>Stopped early after repeated errors on the server; ${results.length} of ${total} were analyzed.`
        : "";
    // the rows listed below the form: everything, or only the chosen customer's
    const shown = onlyCustomer ? results.filter((r) => r.customer_id === onlyCustomer) : results;
    const shownFraud = shown.filter((r) => r.is_fraud).length;
    const customersNote = onlyCustomer
      ? `<br/>Showing the ${shown.length} transaction${shown.length === 1 ? "" : "s"} that belong to <strong>${esc(onlyCustomer)}</strong>: <strong>${esc(shownFraud)}</strong> flagged as fraud${shown.length ? ` (${((shownFraud / shown.length) * 100).toFixed(1)}%)` : ""}. The other ${results.length - shown.length} were analyzed under their own customers and are in Recent Transactions.`
      : `<br/>Each transaction was given its own customer, so they are spread across ${esc(DEMO_CUSTOMERS.length)} customers in Recent Transactions.`;
    el.uploadResult.className = failure || stoppedEarly ? "upload-result error" : "upload-result";
    el.uploadResult.innerHTML = `
      Analyzed <strong>${esc(results.length)}</strong> transaction${results.length === 1 ? "" : "s"}${truncNote}${errNote} in ${esc(seconds)} s &mdash;
      <strong>${esc(fraudCount)}</strong> flagged as fraud (${results.length ? ((fraudCount / results.length) * 100).toFixed(1) : 0}%).${customersNote}${problemNote}
    `;

    el.uploadTableBody.innerHTML = shown
      .map((r) => {
        const decision = esc(r.decision || "—");
        const actual = trueLabels.get(r.transaction_id);
        const actualCell = actual
          ? `<span class="badge decision-${actual === "FRAUD" ? "BLOCK" : "ALLOW"}">${actual}</span>`
          : "–";
        return `
          <tr>
            <td><code>${esc(r.transaction_id ?? "–")}</code></td>
            <td>${esc(r.customer_id ?? "–")}</td>
            <td>${fmtAmount(r.amount)}</td>
            <td>${fmtScore(r.fraud_score)}</td>
            <td><span class="badge decision-${decision}">${decision}</span></td>
            <td>${actualCell}</td>
          </tr>`;
      })
      .join("");
    el.uploadTableWrap.hidden = !shown.length;

    showToast(failure ? "Upload stopped part-way" : `Uploaded dataset analyzed: ${fraudCount}/${results.length} flagged`);
    await loadAll();     // the upload is done; a failed refresh must not turn it into an error
  } catch (err) {
    el.uploadResult.className = "upload-result error";
    el.uploadResult.textContent = `Error: ${err.message}`;
  } finally {
    el.uploadBtn.disabled = false;
  }
});

// ---------- Start a new evaluation session ----------

// The button stays disabled until the word RESET is typed, and the server asks for it again.
el.resetConfirm.addEventListener("input", () => {
  el.resetBtn.disabled = el.resetConfirm.value.trim() !== "RESET";
});

el.resetForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (el.resetConfirm.value.trim() !== "RESET") return;
  el.resetBtn.disabled = true;
  el.resetNote.hidden = false;
  el.resetNote.textContent = "Deleting…";
  try {
    const { removed } = await apiFetch("/api/admin/reset-demo-data", {
      method: "POST",
      body: JSON.stringify({ confirm: "RESET" }),
    });
    // Clear what the page itself still shows from earlier sessions
    for (const box of [el.uploadResult, el.uploadTableWrap, el.analyzeResult, el.analyzeExplainBox, el.samplePreview, el.profileCard]) {
      box.hidden = true;
    }
    el.uploadTableBody.innerHTML = "";
    el.uFile.value = "";
    el.resetConfirm.value = "";
    el.resetNote.textContent =
      `Done: ${removed.transactions} transaction${removed.transactions === 1 ? "" : "s"} and ${removed.alerts} alert${removed.alerts === 1 ? "" : "s"} deleted. The dashboard now starts at zero.`;
    showToast("Dashboard reset for a new session");
    await loadAll();
  } catch (err) {
    if (err.message !== "Unauthorized") el.resetNote.textContent = `Could not delete: ${err.message}`;
  } finally {
    el.resetBtn.disabled = el.resetConfirm.value.trim() !== "RESET";
  }
});

// ---------- Bootstrap ----------

// Each panel loads on its own, so one failing request does not blank the others, and a reload
// already under way is reused, so a slow server is never asked the same thing twice at once.
let loadingAll = null;

function loadAll() {
  if (!loadingAll) {
    loadingAll = refreshPanels().finally(() => { loadingAll = null; });
  }
  return loadingAll;
}

async function refreshPanels() {
  checkHealth();
  const panels = [["statistics", loadStats], ["transactions", loadTransactions], ["fraud patterns", loadPatterns]];
  const outcomes = await Promise.allSettled(panels.map(([, load]) => load()));
  const failed = outcomes
    .map((o, i) => ({ panel: panels[i][0], reason: o.reason }))
    .filter((o) => o.reason && o.reason.message !== "Unauthorized");
  if (failed.length) showToast("Could not refresh the " + failed[0].panel + ": " + failed[0].reason.message);   // textContent, not HTML
  return outcomes.every((o) => o.status === "fulfilled");
}

if (getToken()) {
  showDashboard();
} else {
  showLogin();
}
