import numpy as np
import pandas as pd
import requests
import scipy.stats as stats
from arch import arch_model
from datetime import datetime, timezone
from tqdm import tqdm

# ─── Data fetch ────────────────────────────────────────────────────────────────

def get_btc_1h(n_bars: int = 1000) -> pd.Series:
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": "BTCUSDT", "interval": "1h", "limit": min(n_bars, 1000)}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    raw = r.json()
    closes = pd.Series(
        [float(bar[4]) for bar in raw],
        index=[datetime.fromtimestamp(bar[0] / 1000, tz=timezone.utc) for bar in raw],
        name="close",
    )
    return closes.sort_index()


# ─── Single path simulation ─────────────────────────────────────────────────────
# Uses pure FIGARCH conditional variance — no stacked multipliers.
# The FIGARCH model already captures volatility clustering and long memory.
# Adding entropy/crisis boosts on top inflates bands without improving coverage.

def simulate_cyber_gbm(S0, mu, sigma_fig, nu=5, dt=1, n_steps=1, eps=1e-8):
    S = np.zeros(n_steps + 1)
    S[0] = S0

    for t in range(1, n_steps + 1):
        sigma2 = float(sigma_fig.iloc[-1] ** 2)
        sigma2 = max(eps, min(sigma2, 0.5))

        # Student-t draw scaled to unit variance using fitted nu
        Z = np.random.standard_t(nu) * np.sqrt((nu - 2) / nu)
        S[t] = S[t - 1] * np.exp((mu - 0.5 * sigma2) * dt + np.sqrt(sigma2 * dt) * Z)

    return S


# ─── Monte Carlo wrapper ────────────────────────────────────────────────────────

def simulate_mc(S0, mu, sigma_fig, nu=5, n_sims=5000, n_steps=1, dt=1):
    out = np.zeros((n_sims, n_steps + 1))
    for i in range(n_sims):
        out[i] = simulate_cyber_gbm(S0, mu, sigma_fig, nu=nu, dt=dt, n_steps=n_steps)
    return out


# ─── Walk-forward backtest ──────────────────────────────────────────────────────

def backtest(prices: pd.Series, train: int = 500, test: int = 200, n_sims: int = 3000):
    """
    Strict walk-forward backtest on BTC 1h closes.
    For each bar i in [train, train+test), fit FIGARCH on prices[i-train:i],
    predict price at bar i+1, compare with actual. No peeking.
    dt=1 because sigma from FIGARCH is already in per-hour units.
    """
    log_ret_all = np.log(prices / prices.shift(1)).dropna()
    records = []

    for i in tqdm(range(train, train + test), desc="Backtesting"):
        train_ret = log_ret_all.iloc[i - train : i]

        try:
            am = arch_model(train_ret * 100, vol="FIGARCH", p=1, o=0, q=1, dist="studentst")
            res = am.fit(disp="off")
        except Exception:
            continue

        sigma_fig = res.conditional_volatility / 100
        resid = (train_ret * 100 - res.params["mu"]) / res.conditional_volatility
        nu = max(4, stats.t.fit(resid, floc=0, fscale=1)[0])

        if i == train:
            print(f"  [debug] fitted nu = {nu:.2f}")

        S0_bt = float(prices.iloc[i])
        mu_bt = float(train_ret.mean())

        paths_bt = simulate_mc(S0_bt, mu_bt, sigma_fig, nu=nu, n_sims=n_sims, n_steps=1, dt=1)

        S_t1 = paths_bt[:, 1]
        low95, high95 = np.percentile(S_t1, [2.5, 97.5])
        low997, high997 = np.percentile(S_t1, [0.15, 99.85])
        actual = float(prices.iloc[i + 1])

        width95 = high95 - low95
        alpha = 0.05
        if actual < low95:
            winkler = width95 + (2 / alpha) * (low95 - actual)
        elif actual > high95:
            winkler = width95 + (2 / alpha) * (actual - high95)
        else:
            winkler = width95

        records.append({
            "timestamp": prices.index[i + 1].isoformat(),
            "S0": S0_bt,
            "actual": actual,
            "low_95": low95,
            "high_95": high95,
            "low_997": low997,
            "high_997": high997,
            "coverage_95": int(low95 <= actual <= high95),
            "coverage_997": int(low997 <= actual <= high997),
            "width_95": width95,
            "winkler": winkler,
        })

    df = pd.DataFrame(records)
    print(f"\nResults on BTC/USDT 1h — {len(df)} test bars")
    print(f"  Coverage 95%  : {df['coverage_95'].mean():.2%}")
    print(f"  Coverage 99.7%: {df['coverage_997'].mean():.2%}")
    print(f"  Avg width 95% : ${df['width_95'].mean():,.2f}")
    print(f"  Mean Winkler  : {df['winkler'].mean():.2f}")
    return df


# ─── Live prediction ────────────────────────────────────────────────────────────

def live_predict(n_train: int = 500, n_sims: int = 5000):
    prices = get_btc_1h(n_bars=n_train + 10)
    log_ret = np.log(prices / prices.shift(1)).dropna()
    train_ret = log_ret.iloc[-n_train:]

    am = arch_model(train_ret * 100, vol="FIGARCH", p=1, o=0, q=1, dist="studentst")
    res = am.fit(disp="off")

    sigma_fig = res.conditional_volatility / 100
    resid = (train_ret * 100 - res.params["mu"]) / res.conditional_volatility
    nu = max(4, stats.t.fit(resid, floc=0, fscale=1)[0])

    S0 = float(prices.iloc[-1])
    mu = float(train_ret.mean())

    paths = simulate_mc(S0, mu, sigma_fig, nu=nu, n_sims=n_sims, n_steps=1, dt=1)

    S_t1 = paths[:, 1]
    low95, high95 = np.percentile(S_t1, [2.5, 97.5])

    return {
        "current_price": float(S0),
        "predicted_low_95": float(round(float(low95), 2)),
        "predicted_high_95": float(round(float(high95), 2)),
        "predicted_mean": float(round(float(S_t1.mean()), 2)),
        "as_of": prices.index[-1].isoformat(),
        "sigma_current": float(round(float(sigma_fig.iloc[-1]), 6)),
    }


# ─── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    print("Fetching BTC/USDT 1h data...")
    prices = get_btc_1h(n_bars=1000)
    print(f"Got {len(prices)} bars — {prices.index[0]} to {prices.index[-1]}")
    print(f"Latest close: ${prices.iloc[-1]:,.2f}")

    print("\nRunning walk-forward backtest...")
    df = backtest(prices, train=500, test=200, n_sims=3000)

    df.to_json("backtest_results.jsonl", orient="records", lines=True)
    print("\nSaved backtest_results.jsonl")

    print("\nRunning live prediction...")
    pred = live_predict(n_train=500, n_sims=5000)
    print(json.dumps(pred, indent=2))
