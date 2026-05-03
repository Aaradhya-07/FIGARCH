# AlphaI Build Challenge — Project Context
**Last updated:** 2026-05-03 04:11 AM IST  
**Deadline:** 2026-05-04 17:00 IST (Sunday 5 PM)  
**Status:** Dashboard working locally. Backend numpy bug active. Persistence not set up. Not deployed.

---

## What this project is

A submission for AlphaI's public build challenge. AlphaI is a Coinbase-backed AI-native crypto trading copilot. The challenge asks for:
- **Part A:** Walk-forward backtest of GBM prediction intervals on BTC/USDT 1h data
- **Part B:** Live dashboard showing real-time prediction intervals
- **Part C (bonus):** Persistence layer storing predictions + actuals over time

The submission is intentionally beyond the brief — we use FIGARCH instead of GBM, a React trading terminal instead of Streamlit, and ClickHouse Cloud for persistence instead of SQLite.

---

## Why specific decisions were made

| Decision | Reason |
|----------|--------|
| FIGARCH over GBM/GARCH | BTC volatility has long memory — shocks decay hyperbolically, not exponentially. The founder's background is econophysics. |
| React + TradingView Lightweight Charts | The CTO said they chose their tools deliberately. Streamlit signals "data science student." TradingView is what real trading terminals use. |
| FastAPI backend | Lightweight, async, typed. Their stack is Go — Python handles the research/inference layer only. |
| ClickHouse for persistence | The CTO explicitly mentioned they switched from Postgres to ClickHouse for time-series analytics. Using it signals we were listening. |
| dt=1 not dt=1/24 | FIGARCH fitted on hourly returns → sigma is already per-hour. dt=1/24 shrank intervals by sqrt(24) ≈ 5x, causing 51% coverage. Fixed. |
| Student-t distribution | Brief explicitly said keep it. BTC has fat tails. |
| Binance data-api.binance.vision | No API key, no geo-block. Specified in the brief. |

---

## Project structure

```
~/Desktop/alphai/
├── model.py                  # Core: data fetch, FIGARCH, Cyber GBM, backtest, live_predict
├── backtest_results.jsonl    # Output of python model.py — 200 walk-forward bars
├── backend/
│   ├── main.py               # FastAPI — /prediction, /history, /backtest endpoints
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx           # React dashboard — TradingView chart, metric cards, prediction log
│   │   └── main.jsx
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── docker-compose.yml
├── README.md                 # Written as a research report, not a setup guide
└── context.md                # THIS FILE
```

---

## Model architecture

### Data
- Source: `https://data-api.binance.vision/api/v3/klines`
- Symbol: BTCUSDT, interval: 1h, limit: 1000
- Returns: UTC-indexed pandas Series of close prices

### FIGARCH(1,0,1) + Student-t
```python
am = arch_model(log_ret * 100, vol='FIGARCH', p=1, o=0, q=1, dist='studentst')
```
- Fitted on trailing 500-bar window per walk-forward step
- `sigma_fig = res.conditional_volatility / 100` — per-hour fractional units
- `nu = max(4, stats.t.fit(resid)[0])` — fitted degrees of freedom, floored at 4

### Cyber GBM extensions
Three additions on top of base GBM:
1. **Rolling entropy** (60-bar window, 20 bins) — boosts sigma when market is disordered
2. **Crisis detection** — if entropy or mean abs return > 80th percentile, extra delta boost
3. **Redundancy** — ratio of 5-bar to 20-bar variance, multiplicative sigma scaler

### GBM path equation
```
S[t] = S[t-1] * exp((mu - 0.5*sigma²)*dt + sqrt(sigma²*dt)*Z)
Z ~ Student-t(nu) * sqrt((nu-2)/nu)   # unit-variance scaled
dt = 1                                  # one step = one hour; sigma already per-hour
```

### Monte Carlo
- 3000 sims per backtest bar, 5000 for live prediction
- 95% CI: percentiles [2.5, 97.5]
- 99.7% CI: percentiles [0.15, 99.85]

---

## Backtest results (current)

| Metric | Value |
|--------|-------|
| Coverage 95% | **97.00%** |
| Coverage 99.7% | **100.00%** |
| Avg width 95% | $1,675.69 |
| Mean Winkler | 1965.99 |
| Test bars | 200 (BTC/USDT 1h) |
| Train window | 500 bars rolling |
| Data range | 2026-03-22 to 2026-05-02 |

97% coverage on a 95% CI = slightly conservative = correct failure mode for a trading system. Do not try to "fix" this down to exactly 95% — it will introduce instability.

---

## Known bugs (as of last update)

### BUG-001 — numpy serialization in FastAPI [ACTIVE]
**File:** `backend/main.py`  
**Error:** `ValueError: 'numpy.bool_' object is not iterable` on `/prediction` endpoint  
**Cause:** `load_backtest_stats()` reads jsonl file into a DataFrame; pandas infers numpy types for coverage fields. FastAPI's default JSON encoder can't handle `numpy.bool_` or `numpy.int64`.  
**Fix:** In `load_backtest_stats()`, explicitly cast all values to Python native types:
```python
return {
    "coverage_95": float(df["coverage_95"].mean()),
    "coverage_997": float(df["coverage_997"].mean()),
    "avg_width_95": float(round(df["width_95"].mean(), 2)),
    "mean_winkler": float(round(df["winkler"].mean(), 2)),
    "n_bars_tested": int(len(df)),
}
```
**Status:** Not yet applied.

---

## TODO before deployment (in order)

- [ ] **Fix BUG-001** — numpy serialization in backend/main.py
- [ ] **Set up ClickHouse Cloud** — free tier, create predictions table, wire into /prediction endpoint
- [ ] **Test full local flow** — backend green, frontend showing live data with no errors
- [ ] **Deploy backend to Render** — connect GitHub repo, set env vars
- [ ] **Deploy frontend to Vercel** — set `VITE_API_URL` to Render backend URL
- [ ] **Smoke test live URLs** — open in incognito, verify prediction loads
- [ ] **Final README pass** — add live URL, add actual backtest numbers
- [ ] **Submit form** — fill challenge submission
- [ ] **DM CTO on Instagram** — short, specific message with GitHub + live URL

---

## ClickHouse setup (target schema)

```sql
CREATE TABLE predictions (
    id           UUID DEFAULT generateUUIDv4(),
    saved_at     DateTime64(3, 'UTC'),
    as_of        DateTime64(3, 'UTC'),
    current_price Float64,
    predicted_low_95  Float64,
    predicted_high_95 Float64,
    predicted_mean    Float64,
    actual_price      Nullable(Float64),
    hit               Nullable(Bool)
) ENGINE = MergeTree()
ORDER BY saved_at;
```

Python client: `clickhouse-connect` (official ClickHouse Python driver)
```python
import clickhouse_connect
client = clickhouse_connect.get_client(
    host=os.environ["CH_HOST"],
    port=8443,
    username="default",
    password=os.environ["CH_PASSWORD"],
    secure=True
)
```

---

## Deployment targets

| Service | Platform | URL (fill after deploy) |
|---------|----------|------------------------|
| FastAPI backend | Render (free) | TBD |
| React frontend | Vercel (free) | TBD |
| ClickHouse | ClickHouse Cloud (free tier) | TBD |

### Render environment variables needed
```
CH_HOST=<clickhouse-cloud-host>
CH_PASSWORD=<clickhouse-cloud-password>
```

### Vercel environment variables needed
```
VITE_API_URL=<render-backend-url>
```

---

## What NOT to change

- **Do not change dt** — it must stay `dt=1` everywhere. dt=1/24 caused 51% coverage (wrong).
- **Do not replace Student-t** — brief explicitly requires it; it's also correct for BTC.
- **Do not replace FIGARCH with plain GARCH** — long memory is the key insight.
- **Do not add options pricing** — that code was stripped from the original notebook intentionally; it's irrelevant to the challenge.
- **Do not switch to Streamlit** — the React dashboard is a deliberate differentiator.
- **Do not add unnecessary endpoints** — keep API surface minimal: /prediction, /history, /backtest, /health.

---

## Context on the company and candidate

**AlphaI:** Coinbase-backed AI-native crypto trading copilot. Founder Dev Motlani — ex-senior partner at US quant hedge fund, managed $80M+, AI researcher in econophysics. CTO (co-founder) — told candidate about their stack: Go backend, Kafka, Redis, ClickHouse, bounded goroutine worker pools.

**Candidate:** Aaradhya, 2nd year B.Tech CSE (AI/ML), Polaris School of Technology Bangalore. Prior internship at Mstack — built production event-driven data pipelines (Kafka, FastAPI, Docker, PostgreSQL, GitHub Actions). The CTO followed Aaradhya on Instagram after their conversation and asked for proof of work. This submission IS the proof of work.

**Roles targeted:** AI Research (primary), ML Models (secondary).

---

## Changelog

### [2026-05-03 04:11] — Session 1 complete
- Built `model.py`: Binance 1h fetch, FIGARCH Cyber GBM, walk-forward backtest, live_predict
- Built `backend/main.py`: FastAPI with /prediction, /history, /backtest, /health
- Built `frontend/src/App.jsx`: React dashboard, TradingView Lightweight Charts, metric cards, prediction log table
- Built `docker-compose.yml`, `README.md` (as research report)
- **Fixed critical bug:** dt=1/24 → dt=1 (coverage went from 51% to 97%)
- **Fixed:** hardcoded nu=5 → fitted nu passed through simulate_mc → simulate_cyber_gbm
- **Backtest confirmed:** 97% coverage, 100% 99.7% coverage, Winkler 1965.99
- **Dashboard confirmed working locally** at localhost:5173
- **BUG-001 identified** (numpy serialization) — not yet fixed

---

*When passing this file to a new agent or session: paste this entire file and say "read context.md and continue from where we left off." The agent should acknowledge the changelog, apply BUG-001 fix first, then continue with the TODO list in order.*
