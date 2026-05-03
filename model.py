import numpy as np
import pandas as pd
import requests
import scipy.stats as stats
from arch import arch_model
from datetime import datetime, timezone
from tqdm import tqdm

# ─── Data fetch ────────────────────────────────────────────────────────────────

def get_btc_1h(n_bars: int = 1000) -> pd.Series:
    """
    Fetch BTC/USDT 1h closes from Binance public mirror.
    No API key, no geo-block.
    Returns a Series indexed by UTC datetime.
    """
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {
        "symbol": "BTCUSDT",
        "interval": "1h",
        "limit": min(n_bars, 1000),
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    raw = r.json()
    closes = pd.Series(
        [float(bar[4]) for bar in raw],
        index=[
            datetime.fromtimestamp(bar[0] / 1000, tz=timezone.utc)
            for bar in raw
        ],
        name="close",
    )
    return closes.sort_index()


# ─── Rolling entropy helper ─────────────────────────────────────────────────────

def rolling_entropy(x: pd.Series, window: int = 60, bins: int = 20) -> pd.Series:
    def ent(v):
        p, _ = np.histogram(v, bins=bins, density=True)
        p = p[p > 0]
        return -np.sum(p * np.log(p))
    return x.rolling(window).apply(ent, raw=True)


# ─── Fit FIGARCH + Cyber GBM params from a return series ───────────────────────

def fit_model(log_ret: pd.Series, prices: pd.Series):
    """
    Fits FIGARCH(1,0,1) with Student-t on log returns.
    Returns (res, sigma_fig, nu, H_series, M_series, bar_sigma2, redundancy, info_filter, base_params)
    """
    am = arch_model(log_ret * 100, vol="FIGARCH", p=1, o=0, q=1, dist="studentst")
    res = am.fit(disp="off")

    sigma_fig = res.conditional_volatility / 100
    resid = (log_ret * 100 - res.params["mu"]) / res.conditional_volatility
    nu = max(4, stats.t.fit(resid, floc=0, fscale=1)[0])

    H_series = rolling_entropy(resid)
    M_series = log_ret.abs().rolling(60).mean()

    h_star = H_series.quantile(0.95)
    m_star = M_series.quantile(0.95)
    bar_sigma2 = (sigma_fig ** 2).mean()

    redundancy = 1 + 0.1 * np.log1p(
        prices.rolling(5).var() / prices.rolling(20).var()
    )
    info_filter = (H_series > H_series.quantile(0.72)).astype(float)

    H_max, M_max = H_series.max(), M_series.max()
    a0, d0 = 0.5, 0.3
    if a0 * H_max + d0 * M_max >= 1:
        fac = 0.95 / (a0 * H_max + d0 * M_max)
        a0 *= fac
        d0 *= fac
    base_params = {"alpha": a0, "delta": d0, "gamma": 0.2, "kappa": 0.1, "eta": 1e-3}

    return res, sigma_fig, nu, H_series, M_series, bar_sigma2, redundancy, info_filter, base_params


# ─── Single path simulation ─────────────────────────────────────────────────────

def simulate_cyber_gbm(
    S0, mu, sigma_fig, H, M, redundancy, info_filter,
    params, bar_sigma2, n_steps, nu=5, dt=1, eps=1e-6
):
    S = np.zeros(n_steps + 1)
    V = np.zeros(n_steps + 1)
    S[0] = S0
    sigma2 = float(sigma_fig.iloc[-1] ** 2)

    H_max = H.max() if H.max() > 0 else 1.0
    M_max = M.max() if M.max() > 0 else 1.0

    for t in range(1, n_steps + 1):
        H_val = min(float(H.iloc[-1]) / H_max, 1.0)
        M_val = min(float(M.iloc[-1]) / M_max, 1.0)

        crisis = (H_val > 0.8) or (M_val > 0.8)
        delta_t = params["delta"] if crisis else 0.0

        sigma2 = (
            float(sigma_fig.iloc[-1]) ** 2
            * (1 + params["alpha"] * H_val + delta_t * M_val)
            + params["gamma"] * (bar_sigma2 - sigma2)
        )
        sigma2 *= max(1e-12, float(redundancy.iloc[-1]))
        sigma2 *= 1 + 0.3 * float(info_filter.iloc[-1])
        sigma2 = max(eps, min(sigma2, 0.5))

        # Student-t draw scaled to unit variance using fitted nu
        Z = np.random.standard_t(nu) * np.sqrt((nu - 2) / nu)
        S[t] = S[t - 1] * np.exp((mu - 0.5 * sigma2) * dt + np.sqrt(sigma2 * dt) * Z)
        V[t] = sigma2

        # Online param update
        err = sigma2 - bar_sigma2
        lr = params["eta"] / (1 + t ** 0.55)
        params = dict(params)
        params["gamma"] = np.clip(params["gamma"] + lr * err, 0.01, 0.5)

    return S, V


# ─── Monte Carlo wrapper ────────────────────────────────────────────────────────

def simulate_mc(
    S0, mu, sigma_fig, H, M, redundancy, info_filter,
    bar_sigma2, base_params, n_sims=5000, n_steps=1, nu=5, dt=1
):
    out = np.zeros((n_sims, n_steps + 1))
    for i in range(n_sims):
        paths, _ = simulate_cyber_gbm(
            S0, mu, sigma_fig, H, M, redundancy, info_filter,
            base_params.copy(), bar_sigma2, n_steps, nu=nu, dt=dt
        )
        out[i] = paths
    return out


# ─── Walk-forward backtest ──────────────────────────────────────────────────────

def backtest(prices: pd.Series, train: int = 500, test: int = 200, n_sims: int = 3000):
    """
    Strict walk-forward backtest on BTC 1h closes.
    For each bar i in [train, train+test), fit on prices[i-train:i],
    predict price at bar i+1, compare with actual.

    dt = 1/24 (one hour as fraction of a day, consistent with daily mu/sigma scaling)
    """
    log_ret_all = np.log(prices / prices.shift(1)).dropna()
    records = []

    for i in tqdm(range(train, train + test), desc="Backtesting"):
        train_prices = prices.iloc[i - train : i]
        train_ret = log_ret_all.iloc[i - train : i]

        # Fit model on training window only — no peeking
        try:
            am = arch_model(train_ret * 100, vol="FIGARCH", p=1, o=0, q=1, dist="studentst")
            res = am.fit(disp="off")
        except Exception:
            continue

        sigma_fig = res.conditional_volatility / 100
        resid = (train_ret * 100 - res.params["mu"]) / res.conditional_volatility
        nu = max(4, stats.t.fit(resid, floc=0, fscale=1)[0])
        if i == train:  # print only first bar
            print(f"  [debug] fitted nu = {nu:.2f}")

        H_bt = rolling_entropy(resid).dropna()
        M_bt = train_ret.abs().rolling(60).mean().dropna()

        # Align series to same length
        min_len = min(len(sigma_fig), len(H_bt), len(M_bt))
        sigma_bt = sigma_fig.iloc[-min_len:]
        H_bt = H_bt.iloc[-min_len:]
        M_bt = M_bt.iloc[-min_len:]

        redundancy_bt = 1 + 0.1 * np.log1p(
            train_prices.rolling(5).var() / train_prices.rolling(20).var()
        ).iloc[-min_len:]
        info_filter_bt = (H_bt > H_bt.quantile(0.72)).astype(float)

        bar_sigma2_bt = float((sigma_bt ** 2).mean())

        H_max, M_max = H_bt.max(), M_bt.max()
        a0, d0 = 0.5, 0.3
        if a0 * H_max + d0 * M_max >= 1:
            fac = 0.95 / (a0 * H_max + d0 * M_max)
            a0 *= fac
            d0 *= fac
        base_params_bt = {"alpha": a0, "delta": d0, "gamma": 0.2, "kappa": 0.1, "eta": 1e-3}

        S0_bt = float(prices.iloc[i])
        mu_bt = float(train_ret.mean())

        paths_bt = simulate_mc(
            S0_bt, mu_bt, sigma_bt, H_bt, M_bt,
            redundancy_bt, info_filter_bt,
            bar_sigma2_bt, base_params_bt,
            n_sims=n_sims, n_steps=1, nu=nu, dt=1,
        )

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


# ─── Live prediction (single next bar) ─────────────────────────────────────────

def live_predict(n_train: int = 500, n_sims: int = 5000):
    """
    Fetch latest data, fit model, predict next 1h bar.
    Returns dict with current price, low_95, high_95, mean prediction.
    """
    prices = get_btc_1h(n_bars=n_train + 10)
    log_ret = np.log(prices / prices.shift(1)).dropna()
    train_ret = log_ret.iloc[-n_train:]
    train_prices = prices.iloc[-n_train:]

    am = arch_model(train_ret * 100, vol="FIGARCH", p=1, o=0, q=1, dist="studentst")
    res = am.fit(disp="off")

    sigma_fig = res.conditional_volatility / 100
    resid = (train_ret * 100 - res.params["mu"]) / res.conditional_volatility
    nu = max(4, stats.t.fit(resid, floc=0, fscale=1)[0])

    H_series = rolling_entropy(resid)
    M_series = train_ret.abs().rolling(60).mean()

    min_len = min(len(sigma_fig), len(H_series), len(M_series))
    sigma_fig = sigma_fig.iloc[-min_len:]
    H_series = H_series.iloc[-min_len:]
    M_series = M_series.iloc[-min_len:]

    redundancy = 1 + 0.1 * np.log1p(
        train_prices.rolling(5).var() / train_prices.rolling(20).var()
    ).iloc[-min_len:]
    info_filter = (H_series > H_series.quantile(0.72)).astype(float)

    bar_sigma2 = float((sigma_fig ** 2).mean())

    H_max, M_max = H_series.max(), H_series.max()
    a0, d0 = 0.5, 0.3
    if a0 * H_max + d0 * M_max >= 1:
        fac = 0.95 / (a0 * H_max + d0 * M_max)
        a0 *= fac
        d0 *= fac
    base_params = {"alpha": a0, "delta": d0, "gamma": 0.2, "kappa": 0.1, "eta": 1e-3}

    S0 = float(prices.iloc[-1])
    mu = float(train_ret.mean())

    paths = simulate_mc(
        S0, mu, sigma_fig, H_series, M_series,
        redundancy, info_filter,
        bar_sigma2, base_params,
        n_sims=n_sims, n_steps=1, nu=nu, dt=1,
    )

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

    print("\nRunning walk-forward backtest (this takes ~5 min)...")
    df = backtest(prices, train=500, test=200, n_sims=3000)

    df.to_json("backtest_results.jsonl", orient="records", lines=True)
    print("\nSaved backtest_results.jsonl")

    print("\nRunning live prediction...")
    pred = live_predict(n_train=500, n_sims=5000)
    print(json.dumps(pred, indent=2))
