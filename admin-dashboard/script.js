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

function fmtAmount(n) {
  if (typeof n !== "number") return "–";
  return Math.round(n).toLocaleString();
}

function fmtScore(n) {
  if (typeof n !== "number") return "–";
  return `${(n * 100).toFixed(1)}%`;
}

function fmtTimeOfDay(seconds) {
  if (typeof seconds !== "number") return "–";
  const totalSeconds = Math.floor(seconds % 86400);
  const h = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  return `${h}:${m}`;
}

let decisionFilter = "";

async function loadTransactions() {
  const query = decisionFilter ? `&decision=${decisionFilter}` : "";
  const { transactions } = await apiFetch(`/api/transactions/recent?limit=25${query}`);

  if (!transactions.length) {
    const emptyMsg = decisionFilter
      ? `No ${decisionFilter} transactions yet.`
      : "No transactions yet — analyze one above, or run the full system to generate sample data.";
    el.txTableBody.innerHTML = `<tr><td colspan="7" class="table-empty">${emptyMsg}</td></tr>`;
    return;
  }

  el.txTableBody.innerHTML = transactions
    .map((tx) => {
      const decision = esc(tx.decision || "—");
      const customerId = esc(tx.customer_id ?? "");
      return `
        <tr>
          <td>${fmtTime(tx.timestamp)}</td>
          <td><code>${esc(tx.transaction_id ?? "–")}</code></td>
          <td>${customerId ? `<button type="button" class="customer-link" data-customer="${customerId}">${customerId}</button>` : "–"}</td>
          <td>${fmtTimeOfDay(tx.txn_time)}</td>
          <td>${fmtAmount(tx.amount)}</td>
          <td>${fmtScore(tx.fraud_score)}</td>
          <td><span class="badge decision-${decision}">${decision}</span></td>
        </tr>`;
    })
    .join("");
}

el.txTableBody.addEventListener("click", (e) => {
  const link = e.target.closest(".customer-link");
  if (!link) return;
  el.lCustomer.value = link.dataset.customer;
  lookupCustomer(link.dataset.customer);
  el.profileCard.scrollIntoView({ behavior: "smooth", block: "center" });
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

async function lookupCustomer(customerId) {
  el.profileCard.hidden = false;
  el.profileCard.className = "profile-card";
  el.profileCard.textContent = "Loading…";

  try {
    const { profile } = await apiFetch(`/api/customers/${encodeURIComponent(customerId)}/risk-profile`);

    if (!profile || !profile.name) {
      el.profileCard.className = "profile-card not-found";
      el.profileCard.textContent = `No profile on file for ${customerId} — this customer has no transaction history yet.`;
      return;
    }

    const risk = esc(profile.risk_level || "NORMAL");
    const decisions = profile.recent_decisions && profile.recent_decisions.length
      ? profile.recent_decisions.map((d) => `<span class="merchant-chip badge decision-${esc(d)}">${esc(d)}</span>`).join("")
      : `<span class="merchant-chip">none yet</span>`;

    el.profileCard.className = "profile-card";
    el.profileCard.innerHTML = `
      <div class="profile-head">
        <div>
          <h3>${esc(profile.name)}</h3>
          <span class="profile-id">${esc(profile.customer_id)} &middot; ${esc(profile.account_type || "–")}</span>
        </div>
        <span class="risk-badge risk-${risk}">${risk}</span>
      </div>
      <div class="profile-grid">
        <div class="profile-field">
          <span class="field-label">Avg Transaction</span>
          <span class="field-value">${fmtAmount(profile.avg_transaction)}</span>
        </div>
        <div class="profile-field">
          <span class="field-label">Last Location</span>
          <span class="field-value">${esc(profile.last_location || "–")}</span>
        </div>
        <div class="profile-field">
          <span class="field-label">Unusual Hours Freq.</span>
          <span class="field-value">${fmtFreq(profile.unusual_hours_frequency)}</span>
        </div>
      </div>
      <div class="profile-field">
        <span class="field-label">Recent Decisions</span>
        <div class="profile-merchants">${decisions}</div>
      </div>
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
      amount ${fmtAmount(transaction.amount)}, time-of-day ${fmtTimeOfDay(transaction.Time)}.
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
      <strong>${esc(result.decision)}</strong> — fraud score ${fmtScore(result.fraud_score)}
      for <code>${esc(result.transaction_id)}</code> (${esc(result.customer_id)}, ${fmtAmount(result.amount)})${matchNote}<br/>
      Flags: ${Object.entries(result.sql_flags || {})
        .filter(([, v]) => v)
        .map(([k]) => esc(k))
        .join(", ") || "none"}
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
    const fixedCustomer = el.uCustomer.value !== "ROTATE" ? el.uCustomer.value : null;

    const trueLabels = new Map(); // transaction_id -> "FRAUD" | "NORMAL" | null

    const transactions = useRows.map((row, i) => {
      const transactionId = `TXN${Date.now().toString(36).toUpperCase()}${i}`;
      const customerId = fixedCustomer || DEMO_CUSTOMERS[i % DEMO_CUSTOMERS.length];

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
    el.uploadResult.className = failure || stoppedEarly ? "upload-result error" : "upload-result";
    el.uploadResult.innerHTML = `
      Analyzed <strong>${esc(results.length)}</strong> transaction${results.length === 1 ? "" : "s"}${truncNote}${errNote} in ${esc(seconds)} s &mdash;
      <strong>${esc(fraudCount)}</strong> flagged as fraud (${results.length ? ((fraudCount / results.length) * 100).toFixed(1) : 0}%).${problemNote}
    `;

    el.uploadTableBody.innerHTML = results
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
    el.uploadTableWrap.hidden = false;

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
