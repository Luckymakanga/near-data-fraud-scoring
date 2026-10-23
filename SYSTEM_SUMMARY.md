# System Summary

A technical description of the prototype and the research harness around it, written from the code. Every figure comes from a file in `results/`; anything not measured is labelled as such. For the research context see `README.md` and `docs/Methodology.docx`.

---

## 1. Purpose and scope

The repository holds two things that share one fraud model:

1. **An application prototype**: a Flask API, a PostgreSQL store and a web dashboard that score card transactions as they are submitted. It is deployed as a demonstration (Render and Neon free tiers).
2. **A research harness**: scripts that run the same model in three architectures and measure detection quality, decision latency, throughput, processor time and memory while load, concurrency and the distance between application and database change.

The central question is how machine-learning fraud scoring can be integrated close to transaction data to give timely detection under Ugandan banking constraints. The data are a public European card dataset used as a proxy; no customer data is requested or used.

---

## 2. Architecture

### 2.1 The application prototype (the "application tier" architecture)

```
 Dashboard / simulator / curl
            |  HTTPS, token (JWT) login
            v
   api_server.py  (Flask, rate limits)
            |
            v
   fraud_detection_system.py
     1. validate the transaction
     2. read the customer's profile from PostgreSQL
     3. rule checks  (amount, frequency, hour of day)
     4. extract features  --> model score between 0 and 1
     5. combine into a decision: BLOCK / REVIEW / MONITOR / ALLOW
     6. store the transaction (and an alert if flagged) in PostgreSQL
```

The service trains the model at start-up from `data/creditcard_sample.csv`, which is why a cold start on the free hosting tier takes about a minute.

### 2.2 The three architectures compared in the study

```
 A. External batch        B. In-database             C. Application tier
 -----------------        --------------             -------------------
 app inserts the row      app inserts the row        app scores the row
 (unscored)               a trigger inside           then inserts it with
      |                   PostgreSQL scores it       its score
      v                   as it is stored
 a separate job polls
 every 10 s, reads the
 unscored rows, scores
 them outside the
 database, writes the
 scores back
```

All three use one pickled model and one feature pipeline (`near_data_scoring.py`), so the only difference is where scoring runs. The deployed prototype is architecture C.

---

## 3. Components

### 3.1 Data (`data/`)

`creditcard_sample.csv` is a 20,492-row sample of the public ULB credit-card fraud dataset (real, anonymised European card transactions): all 492 frauds plus 20,000 randomly chosen genuine transactions, so 2.4% fraud against 0.17% in the full data. Columns are `Time` (seconds since the first transaction), `V1` to `V28` (anonymised principal components), `Amount` and `Class`. Provenance and why it was chosen are in `data/README.md`.

### 3.2 Features (`feature_engineering.py`, `transaction_processor.py`)

The model's inputs are: time of day, the 28 components, and the amount. The same function builds the features for training, for the API and for every benchmark architecture. `transaction_processor.py` also generates sample transactions by drawing real dataset rows.

### 3.3 The fraud model (`advanced_ml_models.py`)

- Scaling: a robust scaler fitted on the training split only.
- Class imbalance: ADASYN oversampling applied to the training split only, after the split.
- Models: XGBoost and LightGBM (200 trees each), a soft-voting pair of those two, and an Isolation Forest (200 trees) anomaly score. A One-Class SVM is also trained, but it does not contribute to the score.
- Score: a weighted average of XGBoost (0.35), LightGBM (0.35), Isolation Forest (0.15) and the voting pair (0.15), clipped to the range 0 to 1. A transaction counts as fraud above 0.5. `explain_score` returns the same score together with each model's own score, weight and contribution; it shares its code with `score_batch`, so the two cannot differ (checked bit-for-bit on the saved model).
- The pickled model is about 5.8 MB.

### 3.4 Rule checks and decisions (`fraud_detection_system.py`)

Three simple rules run alongside the model:

| Rule | Condition |
|---|---|
| Amount threshold | amount greater than five times the customer's average |
| Frequency | more than ten transactions from the customer in the last hour |
| Unusual hour | hour of day before 06:00 or after 22:00 for a customer who rarely transacts then |

The customer averages and usual-hours rates these rules compare against come from the ten fictional seeded customers, and "hour of day" is derived from the dataset's elapsed-seconds column, so it is an artificial clock. The rules therefore demonstrate a stage of the pipeline; they are not a model of real customer behaviour.

The decision is `BLOCK` if three rules fire, or the model says fraud and at least one rule fires; `REVIEW` if two rules fire or the score exceeds 0.7; `MONITOR` if the model says fraud or the score exceeds 0.5; otherwise `ALLOW`. **Only the model's score has been evaluated against fraud labels. These rules and decision labels have not.** Each rule reports the figures it compared and the decision reports which condition produced it (`_evaluate_rules`, `_decide`); the dashboard uses these to show how a result arose. They change no flag or decision, and a test compares `_decide` with the original logic for every combination.

### 3.5 Storage (`database_module.py`)

PostgreSQL through a connection pool, configured by `DATABASE_URL` or the `PG*` variables. Tables:

| Table | Use |
|---|---|
| `customers` | Ten fictional customers (`CUST001` to `CUST010`) seeded with fixed average amounts and usual-hours rates; the dataset has no customer identifiers, so these are not derived from data |
| `transactions` | Every scored transaction, with score and decision (indexed on customer, time, score and amount) |
| `fraud_alerts` | Alerts for flagged transactions |
| `detection_logs`, `system_metrics` | Created but not used |

### 3.6 API (`api_server.py`)

Token-based login (24-hour tokens signed with `SECRET_KEY`, which is required), cross-origin access enabled, default limits of 200 requests a day and 50 an hour per address with lower limits on some routes (login: 10 attempts a minute). Login credentials come from `ADMIN_USERNAME` and `ADMIN_PASSWORD_HASH` or `ADMIN_PASSWORD`, defaulting to the public demo password with a logged warning. Transactions are validated before scoring (`validation.py`): ids are 1 to 64 letters, digits, hyphens or underscores and the amount is a number from 0 to 1,000,000,000,000. Server errors return a generic message with a short reference id; the detail goes to the log. Endpoints: login; `analyze` (one transaction, returned with an `explanation` of the score, rules and decision that is not stored);  `batch-analyze` (up to 500, scored synchronously, bad rows reported and skipped; the rows of a batch read each customer's profile and hourly count once instead of once per row, a row that fails is reported without cancelling the rest, three failures in a row stop the batch, and the response says how long it took); `recent` (filterable by decision); `sample`; `statistics/fraud` and `statistics/patterns`; `customers/<id>/risk-profile`; `metrics/roi`; `reports/executive-summary`; `research/results` (login required; returns a condensed form of the four files in `results/`, built by `results_summary.py`); `health`.

### 3.7 Analytics (`analytics.py`)

Fraud statistics, simple pattern counts and customer risk profiles are computed from the stored transactions. The ROI and executive-summary figures are computed from cost assumptions written into the code (an assumed one-off implementation cost, an assumed annual operating cost, an assumed saving per investigated case and an assumed "reputation benefit" per case). They are illustrative, not measured.

### 3.8 Dashboard and simulator (`admin-dashboard/`, `live_simulator.py`)

The dashboard is a static page: login, summary statistics, loading a real dataset row and scoring it, CSV upload for batch scoring (sent 50 rows at a time, with progress, because on a host far from its database a single 500-row request ran past the server's and the host's time limits; `data/upload_samples/` has 50, 100 and 200-row files), customer risk-profile lookup, and a decision filter on recent transactions. It re-reads its three tables every 30 seconds while the tab is visible; an earlier 10-second refresh made 360 requests an hour per route against limits of 100 to 200, so a dashboard left open locked itself out with a 429 error. Each table loads on its own, so one failing request does not blank the others; a reload already under way is reused instead of being repeated; and a failure shows the server's reference number, which can be matched to the host's log. After a transaction is analyzed, a "how this score was made" panel (`explain.js`) walks through the four model scores and weights, the three rule checks with the figures they compared, and the reason for the decision. A second page, `results.html`, opens with a plain-language flow of the scoring steps, marking the scoring step that the study moves and where it runs in each architecture, then presents the study's measured results (model detection with 95% intervals, the three architectures at a light load, the rate sweep, the network-distance test and a list of caveats). It draws everything from the `research/results` endpoint, so every figure comes from the result files and none is typed into the page; it redirects to the login page without a token. The static pages themselves are public; only the data is behind the login. `live_simulator.py` posts real dataset rows to the API at random 75 to 110 second intervals so the dashboard shows activity; it is run locally, because the hosting tier has no free always-on worker.

### 3.9 Removed code

An unfinished stream-processing sketch (`advanced_streaming.py`, never imported) and an unrelated static page (`focus-flow/`, from the first commit) were removed; both remain in the git history. No Kafka or other message broker is used anywhere.

---

## 4. The research harness

| Script | What it does |
|---|---|
| `evaluate.py` | Trains on the earlier 80% of transactions by time and scores the later 20%; reports precision, recall, F1 score, PR-AUC, false-positive rate and ROC-AUC with 95% bootstrap intervals (1,000 resamples). Genuine transactions are weighted by about 14.2 to restore the real fraud prevalence. |
| `near_data_scoring.py` | The scoring code shared by every architecture; it is also imported inside PostgreSQL by the trigger. |
| `benchmark_db.py` | Creates a private PostgreSQL cluster (port 5433) with the PL/Python language, which needs a superuser. |
| `benchmark_architectures.py` | Replays the held-out transactions at a fixed rate under each architecture and records latency, processor time, peak memory and cold start; checks the stored scores against the model's own. |
| `benchmark_sweep.py` | Repeats this over arrival rates from 5 to 160 transactions per second and 1, 2 or 4 concurrent connections, and records the machine's state before each run. |
| `benchmark_network.py`, `latency_proxy.py` | Puts a TCP relay that delays traffic between application and database, at five distances, with 0 or 3 stand-in database reads per transaction. |

**Timing definition.** Latency runs from a transaction's scheduled arrival to the moment its score is committed, so queueing counts. A configuration is "saturated" when the last transaction commits more than one second late.

**Stand-in reads.** The model uses only features that arrive with the transaction, so on its own the network test cannot tell the two synchronous designs apart. The reads (customer-history lookups) are stand-ins: the application reads them over its connection, the in-database trigger reads them locally, and the batch job reads them in one query per poll. Their values are not used by the model, and the number of reads is a parameter chosen by the study.

---

## 5. Measured results

Source files are in `results/`; limits and caveats are in `docs/Methodology.docx`.

**Detection (`evaluation_metrics.json`)**, 75 frauds in the test split, real prevalence restored:

| Metric | Value | 95% interval |
|---|---|---|
| Precision | 0.39 | 0.25 to 0.68 |
| Recall | 0.84 | 0.75 to 0.92 |
| F1 score | 0.53 | 0.38 to 0.76 |
| PR-AUC | 0.75 | 0.62 to 0.90 |
| False-positive rate | 0.0017 | 0.0005 to 0.0032 |

**Architectures at 10 transactions per second (`architecture_benchmark.json`)**, one connection, median of 3 runs:

| | External batch | In-database | Application tier |
|---|---|---|---|
| Decision latency, median / 99th percentile | 5,045 / 9,944 ms | 23.2 / 77.7 ms | 23.1 / 79.0 ms |
| Processor seconds per 1,000 transactions | 1.47 | 23.7 | 23.6 |
| Peak memory, application / database | 192 / 23 MB | 46 / 202 MB | 201 / 22 MB |

**Rate sweep (`rate_sweep.json`)**, decision latency (median / 99th percentile):

| Offered load | External batch | In-database | Application tier |
|---|---|---|---|
| 5/s, 1 connection | 5.0 s / 9.9 s | 23 ms / 53 ms | 23 ms / 31 ms |
| 40/s, 1 connection | 5.1 s / 10.0 s | 21 ms / 224 ms | 25 ms / 531 ms |
| 80/s, 1 connection | 5.1 s / 10.0 s | 15.3 s / 25.8 s (48.5/s achieved) | 9.0 s / 19.0 s (54.1/s) |
| 160/s, 1 connection | 5.6 s / 10.1 s | 24.7 s / 48.1 s (55.3/s) | 24.1 s / 47.1 s (56.0/s) |
| 80/s, 4 connections | 5.1 s / 10.0 s | 19 ms / 91 ms | 19 ms / 67 ms |
| 160/s, 4 connections | 5.1 s / 10.1 s | 2.0 s / 5.3 s (132/s) | 6.9 s / 11.3 s (110/s) |

The full grid (including 2 connections) is in the results file and the methodology. Memory grew with the number of scoring connections: about 240, 493 and 984 MB for in-database scoring and 213, 441 and 880 MB for application-tier scoring with 1, 2 and 4 connections.

**Network distance (`network_latency.json`)**, median decision latency at 5 transactions per second over 4 connections:

| Round trip | Reads | External batch | In-database | Application tier |
|---|---|---|---|---|
| 1 ms | 0 | 5.1 s | 56 ms | 57 ms |
| 53 ms | 0 | 5.2 s | 110 ms | 108 ms |
| 53 ms | 3 | 5.3 s | 106 ms | 267 ms |
| 103 ms | 0 | 5.4 s | 155 ms | 157 ms |
| 103 ms | 3 | 5.5 s | 156 ms | 467 ms |

**What the results support:** batch latency is set by the polling interval; scoring on arrival decides in tens of milliseconds until a connection's capacity is exceeded; capacity and memory both scale with the number of scoring connections; and network distance affects the application tier in proportion to the reads it makes, while in-database scoring is unaffected by them. **What they do not support:** any claim about fraud in Uganda, about drift, about real bank systems, or that one synchronous design beats the other in general (they match except at heavy load with four connections, where in-database sustained more, for a reason not established).

**Cautions:** one laptop; the dataset spans two days; 75 test frauds; the machine was not fully quiet (17 of 90 sweep runs began above 25% processor load, and other programs used a median of 13% of the processor during the network runs); the application tier showed a 1.2 to 1.6 second stall in 3 of 30 sweep runs, cause unknown.

---

## 6. Deployment

`render.yaml` defines the API (gunicorn, one worker) and the static dashboard on Render's free tier; the database is a free Neon PostgreSQL instance. Set `DATABASE_URL` (the connection string) and `SECRET_KEY` as environment variables on the host (`render.yaml` generates the key), and `ADMIN_PASSWORD_HASH` or `ADMIN_PASSWORD` to replace the public demo password. The service sleeps after 15 minutes idle. The deployment is a demonstration: no latency measurement was made on it.

---

## 7. Security

This section records what the code does and does not do about security. It comes from reading `api_server.py`, `database_module.py`, `admin-dashboard/script.js` and the benchmark code. It is a code review of a prototype, not a penetration test: nothing here has been tried by an attacker. "Fixed", "partly fixed" and "not fixed" describe the code in this repository; the live deployment changes only when it is redeployed from this code. The fixes are covered by tests in `tests/test_security.py`, and the cross-site scripting fix was also checked in a browser against the original dashboard.

### 7.1 Context

The live demo holds no sensitive data. The transactions are a public anonymised dataset, the ten customers are fictional, and the login credentials are printed in the README. The realistic risks to the demo are misuse of its open access (filling the shared database, using up free-tier limits, attacking whoever opens the dashboard). The more important risk for the study is what the same design would mean in a bank, where the same weaknesses would matter a great deal more.

### 7.2 What is in place

- **Authentication.** Nine of the eleven routes need a signed token (a JWT using HS256); only login and the health check are open. The signing algorithm is fixed when a token is checked, so a token cannot choose its own, and tokens expire after 24 hours. The signing key comes from `SECRET_KEY`, which is required (there is no built-in default outside debug mode). Login credentials come from the environment, are compared in constant time, and login is limited to 10 attempts a minute.
- **Database access.** Every query uses bound parameters. No query is built from request text (checked across `database_module.py`, `analytics.py` and the API). The two filters on the recent-transactions route are validated: the limit is clamped to 1 to 200 and the decision must be one of four values. Batches are capped at 500 transactions.
- **Input validation and output escaping.** The server accepts transaction and customer ids only as 1 to 64 letters, digits, hyphens or underscores, and the amount only as a number from 0 to 1,000,000,000,000. The dashboard escapes every value that came from the API or a file before putting it into the page, so a hostile value is shown as plain text and runs nothing.
- **Errors.** Server errors return a generic message and a short reference id; the detail is logged under that id.
- **Rate limits.** 200 requests a day and 50 an hour per visitor by default, lower on some routes; the health check is not limited. Behind a hosting proxy every request arrives from the proxy's address, so limits are counted against the visitor's address taken from the host's header (`CF-Connecting-IP` on Render, enabled automatically there; `CLIENT_IP_HEADER` names another header or turns it off). It is off elsewhere, because a caller could otherwise write any value into the header.
- **Stale database connections.** A managed database may pause when idle and drop the service's pooled connections without telling it, which made the first requests after a quiet spell fail with a 500 (seen on the live demo as "Internal server error" right after sign-in). A pooled connection idle for more than 20 seconds is now tested before use and replaced if dead, opening a connection is retried while a paused database wakes, and idle connections are probed by TCP keepalives. Tested with stand-in connections and checked against a real PostgreSQL by killing a pooled connection.
- **Debug mode** is off unless `FLASK_DEBUG=true`.
- **Secrets** come from environment variables. `.env` is excluded from git, and a scan of the repository found no credentials. On Render the `SECRET_KEY` is generated by the platform, and the database connection string is set in the host's dashboard; the example connection string asks for an encrypted connection (`sslmode=require`).
- **Transport.** The hosted API is served over HTTPS by the host.
- **Token storage.** The dashboard keeps the token in `sessionStorage`, which is cleared when the tab closes.
- **No unpickling in the service.** The deployed API trains its model at start-up and does not load any pickle file; only the benchmarks do.
- **Tests.** `tests/test_security.py` (71 tests) covers validation, login, the signing key, error handling and the dashboard's escaping. They fail on the original code (26 of the 71) and pass on the fixed code. `tests/test_explain.py` (20 tests) checks that the score breakdown matches the score exactly, that the decision logic is unchanged, and the explanation's API wiring and page code. `tests/test_results.py` (16 tests) checks the results summary against the result files, the endpoint's login requirement and generic errors, and that the results page builds its content without assigning markup strings.
- **The latency relay** used in the network test listens on the local machine only.

### 7.3 Known weaknesses

| # | Weakness | Where and why it matters | Fix | Status |
|---|---|---|---|---|
| 1 | **Stored cross-site scripting in the dashboard** | The API accepted `customer_id` and `transaction_id` with only a presence check, and the dashboard inserted stored values into the page with `innerHTML` and no escaping, so script supplied by any caller would have run in the browser of whoever opened the dashboard. Checked in a browser: the original dashboard ran an injected script; the fixed one shows the text and runs nothing. | Fixed in two layers: the dashboard escapes every value from the API or a file, and the server accepts ids only in a plain character set (`validation.py`) | Fixed |
| 2 | **Shared admin login** | Credentials now come from the environment (`ADMIN_USERNAME`, and `ADMIN_PASSWORD_HASH` or `ADMIN_PASSWORD`), are compared in constant time, and login is limited to 10 attempts a minute. There is still one shared admin account with no roles, every valid token can call every endpoint, and **until a password is set the public demo password `admin` is used; the live demo is in this state.** | Set `ADMIN_PASSWORD_HASH` on the host; later, separate users with roles and lockout after repeated failures | Partly fixed |
| 3 | **Default signing key in the source** | The API now refuses to start without `SECRET_KEY` outside debug mode; debug mode uses a development-only key and logs a warning. Tokens signed with the old built-in key are rejected (tested). | Done | Fixed |
| 4 | **Error details returned to callers** | All nine handlers now return a generic message with a short reference id; the detail goes to the server log under that id (tested, including against the real system). | Done | Fixed |
| 5 | **Cross-origin access open to all sites** | `CORS(app)` with defaults. Tokens travel in a header, not a cookie, so the usual cross-site request risk is limited, but scripts on any site can call the API once they hold a token. | Allow only the dashboard's origin | Not fixed |
| 6 | **Rate limiting behind a proxy** | The limit was keyed on the connecting address, which behind Render is the proxy's, so all visitors shared one limit of 50 requests an hour and 10 logins a minute and a few requests locked everyone out (seen on the live demo as HTTP 429). Now the visitor's address is read from the host's header where the host is known to set it, and the health check is exempt (tested, including that one visitor cannot lock out another). Counters are still in memory, so they reset on restart and are not shared between workers. | Use an external counter store if more than one worker is run | Fixed for the shared-limit fault; counter store not done |
| 7 | **Thin input validation** | Transactions are now validated: ids as above, amount a finite number from 0 to 1,000,000,000,000, and bodies that are not JSON objects get a 400. The other fields (the 28 anonymised features, time, merchant) are not yet checked for type or range. | Validate the remaining fields against a schema | Partly fixed |
| 8 | **Login handler** | An empty or non-JSON body now returns 400, and login is limited to 10 attempts a minute per address. There is still no lockout after repeated failures. | Lockout | Partly fixed |
| 9 | **Open write access on the public demo** | Anyone with the public credentials can add rows to the shared database, within the rate limits, polluting the demo data and using free-tier storage | A read-only demo role, or a periodic reset | Not fixed |
| 10 | **In-database scoring** (research harness) | It needs PostgreSQL's untrusted PL/Python language and a superuser, and loads the model from a pickle file inside the database server. A tampered model file would run arbitrary code inside the database. Each scoring session also holds its own Python and ML runtime (about 200 MB), which is not isolated from the data. | Restrict file permissions, sign and verify model files, use a dedicated database role, or consider an index-based approximation or an external scorer | Inherent to the design; memory cost is measured in `results/` |
| 11 | **Unpinned dependencies** | `requirements.txt` gives lower bounds only and nothing scans for known vulnerabilities, so builds can change and problems can go unnoticed | Pin versions; run a dependency audit | Not done |
| 12 | **No audit trail** | Logins and administrative actions are not recorded, and alerts are only printed to the console | A structured audit log | Not done |
| 13 | **Personal data and the law** | The demo holds no personal data. A real deployment would hold customer data and fall under the Data Protection and Privacy Act 2019 (not yet reviewed in this project) and Bank of Uganda requirements, and the hosts are outside Uganda. | Legal and data-protection review before any real data is used | Open |

Items 1, 3 and 4 are fixed, and items 2, 7 and 8 are partly fixed. The most important remaining step for the live demo is to set `ADMIN_PASSWORD_HASH` on the host, because until then anyone who has read this README can log in and write to the shared database (item 9).

### 7.4 What a bank would need beyond this prototype

Integration with the bank's identity system (single sign-on, roles, multi-factor authentication); encrypted connections everywhere, including the database link; network separation between application and database; managed secrets with rotation; a reviewed and signed model-release process; audit logging and monitoring; regular testing, including independent penetration testing; and a data-protection assessment. These are general practices; this project did not assess them against Bank of Uganda requirements.

### 7.5 Security as a constraint in the study

Security is one of the constraints named in the research question. The measured costs of near-data scoring, the memory held by each scoring session and the privileges needed to run model code inside the database, are the technical side of weakness 10, and are what a practitioner or regulator would ask about first. The literature review sets out the regulatory context.

---

## 8. Reproducing the results

```bash
pip install -r requirements.txt
python evaluate.py                        # detection metrics
python benchmark_db.py init               # once
python benchmark_db.py start
python benchmark_architectures.py         # architectures at one load
python benchmark_sweep.py                 # rate and concurrency sweep
python benchmark_network.py               # network-distance test
python benchmark_db.py stop
```

Close other programs first; timing results depend on a quiet machine. Each result file records the machine and code version that produced it.
