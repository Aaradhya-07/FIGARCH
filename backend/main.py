from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from model import get_btc_1h, live_predict, backtest
import numpy as np
import pandas as pd
import json
from datetime import datetime, timezone
from pathlib import Path
import threading

app = FastAPI(title="AlphaI GBM Signal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── In-memory prediction cache ────────────────────────────────────────────────
_cache = {"prediction": None, "history": [], "last_updated": None}
_lock = threading.Lock()

# Load backtest results on startup if available
BACKTEST_PATH = Path(__file__).parent.parent / "backtest_results.jsonl"

def load_backtest_stats():
    if not BACKTEST_PATH.exists():
        return None
    records = []
    with open(BACKTEST_PATH) as f:
        for line in f:
            records.append(json.loads(line.strip()))
    df = pd.DataFrame(records)
    return {
        "coverage_95": float(df["coverage_95"].mean()),
        "coverage_997": float(df["coverage_997"].mean()),
        "avg_width_95": float(round(df["width_95"].mean(), 2)),
        "mean_winkler": float(round(df["winkler"].mean(), 2)),
        "n_bars_tested": int(len(df)),
    }

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}

@app.get("/prediction")
def get_prediction():
    """
    Fetch latest BTC price, run FIGARCH Cyber GBM, return 1h ahead 95% CI.
    Also appends to in-memory history for Part C.
    """
    try:
        pred = live_predict(n_train=500, n_sims=3000)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    pred["backtest_stats"] = load_backtest_stats()

    with _lock:
        _cache["prediction"] = pred
        _cache["last_updated"] = datetime.now(timezone.utc).isoformat()
        _cache["history"].append({
            **pred,
            "saved_at": _cache["last_updated"],
            "actual": None,  # filled in on next call when bar closes
        })
        # Fill in actuals for previous predictions where we now know the price
        current_price = pred["current_price"]
        hist = _cache["history"]
        for i in range(len(hist) - 1):
            if hist[i]["actual"] is None:
                hist[i]["actual"] = current_price
                hist[i]["hit"] = bool(
                    hist[i]["predicted_low_95"] <= current_price <= hist[i]["predicted_high_95"]
                )

    return jsonable_encoder(pred)

@app.get("/history")
def get_history():
    """
    Returns OHLCV candles for the chart + saved prediction history.
    """
    try:
        prices = get_btc_1h(n_bars=60)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    candles = []
    for ts, close in prices.items():
        candles.append({
            "time": int(ts.timestamp()),
            "close": round(float(close), 2),
        })

    with _lock:
        history = list(_cache["history"])

    return {
        "candles": candles,
        "predictions": history[-30:],  # last 30 predictions
    }

@app.get("/backtest")
def get_backtest():
    stats = load_backtest_stats()
    if stats is None:
        raise HTTPException(status_code=404, detail="Run the backtest first: python model.py")
    return stats
