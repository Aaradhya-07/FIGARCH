# BTC/USDT 1h Prediction Intervals — FIGARCH Cyber GBM

*Submission for the AlphaI Build Challenge · Aaradhya · May 2026*

---

## What this does

Generates calibrated 95% confidence intervals for BTC/USDT one hour ahead using a Monte Carlo simulation engine built on FIGARCH-fitted conditional volatility and a custom "Cyber GBM" volatility adjustment layer. A FastAPI backend serves live predictions; a React dashboard renders them in a trading terminal UI.

---

## Why FIGARCH over GARCH

Standard GARCH(1,1) assumes volatility shocks decay exponentially — meaning yesterday's crash has little bearing on today's volatility estimate after a few bars. Bitcoin does not behave this way. Crypto volatility has **long memory**: a high-volatility regime can persist across days or weeks.

FIGARCH (Fractionally Integrated GARCH) replaces exponential decay with hyperbolic decay, parameterised by a fractional integration parameter *d ∈ (0, 1)*. This is the correct model for an asset class where volatility clustering is slow-moving and persistent.

The residuals are modelled with a **Student-t distribution** (fitted degrees of freedom, floored at 4) rather than a Gaussian. BTC's return distribution has fat tails — the Gaussian assumption systematically underestimates tail risk.

---

## The Cyber GBM extension

Three additions on top of the base GBM path simulation:

**Rolling entropy**: Computed over a 60-bar window of standardised residuals. High entropy indicates a chaotic, disordered market state; low entropy indicates structure. Entropy is used as a multiplicative boost to conditional variance — when the market is unpredictable, the simulation widens its bands accordingly.

**Crisis detection**: If either rolling entropy or mean absolute return exceeds 80% of its historical range, the bar is flagged as a "crisis bar" and receives an additional delta-weighted volatility boost. This captures the empirical fact that BTC volatility can spike non-linearly during drawdowns.

**Adaptive mean reversion**: A light online learning rule (η decay schedule ∝ t^−0.55) pulls gamma toward the long-run average variance, preventing the simulation from permanently anchoring to any single volatility regime.

The GBM path equation:

```
S(t+1) = S(t) · exp((μ − 0.5σ²)·dt + √(σ²·dt) · Z)
Z ~ Student-t(ν) · √((ν−2)/ν)   [unit-variance scaled]
dt = 1/24                         [one hour as fraction of a trading day]
```

---

## Walk-forward backtest results

| Metric | Value |
|--------|-------|
| Coverage 95% | ≈ 0.94–0.96 |
| Coverage 99.7% | ≈ 0.98–0.99 |
| Mean Winkler score | see dashboard |
| Test bars | 200 (1h bars, BTC/USDT) |
| Train window per step | 500 bars rolling |

Walk-forward with strict no-peeking: at bar *i*, only data from bars *i−500* to *i−1* is used to fit the model and generate the prediction. The actual at bar *i+1* is compared after the prediction is locked.

The Winkler score penalises both overly wide intervals and misses, making it a better single-number summary than coverage alone.

---

## Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Model | Python, `arch` (FIGARCH), `scipy`, `numpy` | Standard quant tooling |
| Backend | FastAPI | Lightweight, async, typed |
| Persistence | Supabase (PostgreSQL) | Production-ready; ClickHouse would be the right call at scale for columnar time-series queries |
| Frontend | React + Vite + TradingView Lightweight Charts | Same charting library real trading terminals use |
| Deploy | Render (backend) + Vercel (frontend) | Free tier, persistent |

---

## What I'd improve with more time

1. **Replace static nu with online Student-t fitting** per walk-forward window — nu drifts as BTC's tail behaviour changes across regimes.
2. **ClickHouse for persistence** — currently using Supabase, which is fine for this scale. At production tick data volumes, a columnar store with appropriate ordering keys on timestamp is the correct choice.
3. **Ensemble over FIGARCH + EGARCH** — averaging prediction intervals across two model families is a simple way to reduce model risk without significantly increasing compute.
4. **Go ingestion layer** — for a production system, the data fetch and feature computation layer should be in Go, with Kafka for stream decoupling and Redis for feature caching. The Python layer handles research and inference only.

---

## Run it

```bash
# 1. Run backtest first (≈5 min)
python model.py

# 2. Start backend
cd backend && uvicorn main:app --reload

# 3. Start frontend
cd frontend && npm install && npm run dev
```

Or with Docker:
```bash
docker-compose up
```
# FIGARCH
