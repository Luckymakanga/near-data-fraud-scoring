const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
  ? "http://localhost:5000"
  : `${window.location.protocol}//${window.location.hostname}:5000`;

const TOKEN_KEY = "fraudAdmin.token";

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

  autoRefresh: document.getElementById("autoRefresh"),
  filterPills: document.getElementById("filterPills"),
  txTableBody: document.getElementById("txTableBody"),
  patternList: document.getElementById("patternList"),

  lookupForm: document.getElementById("lookupForm"),
  lCustomer: document.getElementById("lCustomer"),
  profileCard: document.getElementById("profileCard"),

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
  if (!res.ok) {
    throw new Error(data.error || `Request failed (${res.status})`);
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

function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(loadAll, 10000);
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

el.refreshBtn.addEventListener("click", loadAll);

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
  if (isNaN(d)) return iso;
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
      const decision = tx.decision || "—";
      const customerId = tx.customer_id ?? "";
      return `
        <tr>
          <td>${fmtTime(tx.timestamp)}</td>
          <td><code>${tx.transaction_id ?? "–"}</code></td>
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
    .map((p) => `<li><span>${p.pattern}</span><span class="pattern-count">${p.count} cases</span></li>`)
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

    const risk = profile.risk_level || "NORMAL";
    const decisions = profile.recent_decisions && profile.recent_decisions.length
      ? profile.recent_decisions.map((d) => `<span class="merchant-chip badge decision-${d}">${d}</span>`).join("")
      : `<span class="merchant-chip">none yet</span>`;

    el.profileCard.className = "profile-card";
    el.profileCard.innerHTML = `
      <div class="profile-head">
        <div>
          <h3>${profile.name}</h3>
          <span class="profile-id">${profile.customer_id} &middot; ${profile.account_type || "–"}</span>
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
          <span class="field-value">${profile.last_location || "–"}</span>
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
  el.samplePreview.hidden = false;
  el.samplePreview.textContent = "Loading a random transaction…";
  el.analyzeBtn.disabled = true;

  try {
    const { transaction, true_label } = await apiFetch("/api/transactions/sample");
    currentSample = transaction;
    currentSampleLabel = true_label;

    el.samplePreview.innerHTML = `
      Loaded <code>${transaction.transaction_id}</code> &mdash;
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

  const body = { ...currentSample, customer_id: el.aCustomer.value };
  delete body.timestamp;

  try {
    const { result } = await apiFetch("/api/transactions/analyze", {
      method: "POST",
      body: JSON.stringify(body),
    });

    const matchNote = currentSampleLabel
      ? ` (actual label: <strong>${currentSampleLabel}</strong>)`
      : "";

    el.analyzeResult.className = `analyze-result decision-${result.decision}`;
    el.analyzeResult.innerHTML = `
      <strong>${result.decision}</strong> — fraud score ${fmtScore(result.fraud_score)}
      for <code>${result.transaction_id}</code> (${result.customer_id}, ${fmtAmount(result.amount)})${matchNote}<br/>
      Flags: ${Object.entries(result.sql_flags || {})
        .filter(([, v]) => v)
        .map(([k]) => k)
        .join(", ") || "none"}
    `;
    el.analyzeResult.hidden = false;

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

// ---------- Bootstrap ----------

async function loadAll() {
  checkHealth();
  try {
    await Promise.all([loadStats(), loadTransactions(), loadPatterns()]);
  } catch (err) {
    if (err.message !== "Unauthorized") showToast(err.message);
  }
}

if (getToken()) {
  showDashboard();
} else {
  showLogin();
}
