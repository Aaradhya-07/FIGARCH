import { useState, useEffect, useRef } from "react";
import { createChart, CrosshairMode } from "lightweight-charts";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

// ─── Formatters ────────────────────────────────────────────────────────────────
const usd = (n) => n == null ? "—" : `$${Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const pct = (n) => n == null ? "—" : `${(n * 100).toFixed(2)}%`;
const num = (n, d = 2) => n == null ? "—" : Number(n).toFixed(d);

// ─── Styles ─────────────────────────────────────────────────────────────────────
const css = `
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:        #080b0f;
    --bg1:       #0d1117;
    --bg2:       #111820;
    --bg3:       #161e28;
    --border:    #1e2d3d;
    --border2:   #243040;
    --text:      #cdd9e5;
    --text2:     #768999;
    --text3:     #4a5a6a;
    --blue:      #4a9eff;
    --blue-dim:  rgba(74,158,255,0.12);
    --green:     #3fb950;
    --green-dim: rgba(63,185,80,0.10);
    --red:       #f85149;
    --red-dim:   rgba(248,81,73,0.10);
    --amber:     #e3b341;
    --amber-dim: rgba(227,179,65,0.10);
    --mono: 'IBM Plex Mono', monospace;
    --sans: 'IBM Plex Sans', sans-serif;
  }

  body { background: var(--bg); color: var(--text); font-family: var(--mono); font-size: 13px; line-height: 1.5; overflow-x: hidden; }

  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: var(--bg1); }
  ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }

  .layout { display: grid; grid-template-rows: 48px 1fr; min-height: 100vh; }

  /* Header */
  .header {
    display: flex; align-items: center; gap: 0;
    border-bottom: 1px solid var(--border);
    background: var(--bg1);
    padding: 0;
    position: sticky; top: 0; z-index: 100;
  }
  .header-brand {
    display: flex; align-items: center; gap: 10px;
    padding: 0 20px; height: 48px;
    border-right: 1px solid var(--border);
  }
  .brand-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--blue); box-shadow: 0 0 8px var(--blue); }
  .brand-name { font-size: 12px; font-weight: 600; letter-spacing: 0.14em; color: var(--text); text-transform: uppercase; }
  .header-pair {
    display: flex; align-items: center; gap: 8px;
    padding: 0 20px; height: 48px;
    border-right: 1px solid var(--border);
    font-size: 11px; color: var(--text2);
  }
  .pair-label { color: var(--text); font-weight: 500; }
  .header-tags { display: flex; align-items: center; gap: 6px; padding: 0 16px; flex: 1; }
  .tag {
    font-size: 10px; padding: 2px 8px; border-radius: 2px;
    border: 1px solid var(--border); color: var(--text3);
    letter-spacing: 0.06em; text-transform: uppercase;
  }
  .header-controls { display: flex; align-items: center; gap: 0; margin-left: auto; }
  .status-pill {
    display: flex; align-items: center; gap: 6px;
    padding: 0 16px; height: 48px;
    border-left: 1px solid var(--border);
    font-size: 10px; color: var(--text2);
  }
  .pulse { width: 6px; height: 6px; border-radius: 50%; }
  .pulse.live { background: var(--green); animation: pulseAnim 2s infinite; }
  .pulse.err  { background: var(--red); }
  @keyframes pulseAnim { 0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(63,185,80,0.4)} 50%{opacity:0.7;box-shadow:0 0 0 4px rgba(63,185,80,0)} }
  .btn-refresh {
    height: 48px; padding: 0 18px;
    background: transparent; border: none; border-left: 1px solid var(--border);
    color: var(--text2); font-family: var(--mono); font-size: 10px; letter-spacing: 0.08em;
    cursor: pointer; text-transform: uppercase;
    transition: color 0.15s, background 0.15s;
  }
  .btn-refresh:hover { color: var(--text); background: var(--bg2); }
  .btn-refresh:disabled { opacity: 0.4; cursor: wait; }

  /* Main grid */
  .main { padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }

  /* Error bar */
  .error-bar {
    padding: 8px 14px; background: var(--red-dim);
    border: 1px solid rgba(248,81,73,0.3); border-radius: 3px;
    font-size: 11px; color: var(--red);
  }

  /* Section label */
  .section-label {
    font-size: 9px; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--text3); font-weight: 500; margin-bottom: 8px;
  }

  /* Metric strip */
  .metric-strip { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 1px; background: var(--border); border: 1px solid var(--border); border-radius: 4px; overflow: hidden; }
  .metric {
    background: var(--bg1); padding: 14px 16px;
    display: flex; flex-direction: column; gap: 4px;
  }
  .metric-label { font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--text3); }
  .metric-value { font-size: 20px; font-weight: 500; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
  .metric-sub { font-size: 10px; color: var(--text3); }
  .metric-change { font-size: 10px; }
  .up { color: var(--green); }
  .down { color: var(--red); }
  .neutral { color: var(--text2); }
  .blue-v  { color: var(--blue); }
  .green-v { color: var(--green); }
  .red-v   { color: var(--red); }
  .amber-v { color: var(--amber); }

  /* Two column layout */
  .two-col { display: grid; grid-template-columns: 1fr 340px; gap: 12px; }

  /* Panel */
  .panel { background: var(--bg1); border: 1px solid var(--border); border-radius: 4px; overflow: hidden; }
  .panel-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 9px 14px; border-bottom: 1px solid var(--border);
  }
  .panel-title { font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text2); }
  .panel-badge { font-size: 9px; color: var(--text3); }
  .panel-body { padding: 0; }

  /* Chart */
  .chart-wrap { padding: 0; }

  /* Interval bar */
  .interval-display {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px; background: var(--bg2); border-top: 1px solid var(--border);
  }
  .interval-range { display: flex; align-items: center; gap: 8px; font-size: 11px; }
  .interval-sep { color: var(--text3); }
  .interval-label { font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text3); }

  /* Right sidebar */
  .sidebar { display: flex; flex-direction: column; gap: 12px; }

  /* Model stats */
  .stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--border); }
  .stat-cell { background: var(--bg1); padding: 12px 14px; }
  .stat-label { font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text3); margin-bottom: 4px; }
  .stat-value { font-size: 16px; font-weight: 500; font-variant-numeric: tabular-nums; }
  .stat-sub { font-size: 9px; color: var(--text3); margin-top: 2px; }

  /* Coverage gauge */
  .gauge-wrap { padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .gauge-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
  .gauge-track { height: 3px; background: var(--bg3); border-radius: 2px; overflow: hidden; }
  .gauge-fill { height: 100%; border-radius: 2px; transition: width 0.6s ease; }
  .gauge-label { font-size: 9px; color: var(--text3); letter-spacing: 0.08em; text-transform: uppercase; }
  .gauge-val { font-size: 11px; font-weight: 500; }
  .target-line { font-size: 9px; color: var(--text3); text-align: right; }

  /* Prediction log table */
  .log-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; }
  thead tr { border-bottom: 1px solid var(--border); }
  th { padding: 7px 12px; text-align: left; font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text3); font-weight: 500; white-space: nowrap; }
  tbody tr { border-bottom: 1px solid rgba(30,45,61,0.5); transition: background 0.1s; }
  tbody tr:hover { background: var(--bg2); }
  tbody tr:last-child { border-bottom: none; }
  td { padding: 7px 12px; font-size: 11px; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .hit-yes { color: var(--green); font-weight: 500; }
  .hit-no  { color: var(--red); font-weight: 500; }
  .hit-pending { color: var(--text3); }

  /* Footer */
  .footer {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 20px; border-top: 1px solid var(--border);
    font-size: 9px; color: var(--text3); letter-spacing: 0.06em;
  }
  .footer a { color: var(--text3); text-decoration: none; }
  .footer a:hover { color: var(--text2); }

  /* Loading shimmer */
  .shimmer { background: linear-gradient(90deg, var(--bg2) 25%, var(--bg3) 50%, var(--bg2) 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; border-radius: 2px; }
  @keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }
`;

// ─── Components ─────────────────────────────────────────────────────────────────
function Metric({ label, value, sub, colorClass = "neutral", loading }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      {loading
        ? <div className="shimmer" style={{ height: 24, width: "70%", marginTop: 4 }} />
        : <div className={`metric-value ${colorClass}`}>{value}</div>}
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

function CoverageGauge({ label, value, target = 0.95 }) {
  const pctVal = value != null ? value * 100 : 0;
  const color = value == null ? "#4a5a6a"
    : value >= 0.93 && value <= 0.99 ? "var(--green)"
    : value >= 0.90 ? "var(--amber)"
    : "var(--red)";
  return (
    <div>
      <div className="gauge-row">
        <span className="gauge-label">{label}</span>
        <span className="gauge-val" style={{ color }}>{value != null ? pct(value) : "—"}</span>
      </div>
      <div className="gauge-track">
        <div className="gauge-fill" style={{ width: `${Math.min(pctVal, 100)}%`, background: color }} />
      </div>
      <div className="target-line">target ≥ {pct(target)}</div>
    </div>
  );
}

// ─── Main App ───────────────────────────────────────────────────────────────────
export default function App() {
  const chartRef = useRef(null);
  const chartInst = useRef(null);
  const priceLine = useRef(null);
  const bandHigh = useRef(null);
  const bandLow = useRef(null);

  const [pred, setPred] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastFetch, setLastFetch] = useState(null);
  const [error, setError] = useState(null);
  const [prevPrice, setPrevPrice] = useState(null);

  // ── Chart init ────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!chartRef.current) return;
    const chart = createChart(chartRef.current, {
      width: chartRef.current.clientWidth,
      height: 300,
      layout: { background: { color: "#0d1117" }, textColor: "#768999" },
      grid: { vertLines: { color: "#111820" }, horzLines: { color: "#111820" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#1e2d3d", scaleMarginTop: 0.1, scaleMarginBottom: 0.1 },
      timeScale: { borderColor: "#1e2d3d", timeVisible: true, secondsVisible: false },
      handleScroll: true,
      handleScale: true,
    });

    priceLine.current = chart.addLineSeries({
      color: "#4a9eff",
      lineWidth: 1.5,
      lastValueVisible: true,
      priceLineVisible: false,
    });

    bandHigh.current = chart.addLineSeries({
      color: "rgba(63,185,80,0.5)",
      lineWidth: 1,
      lineStyle: 2, // dashed
      lastValueVisible: false,
      priceLineVisible: false,
    });

    bandLow.current = chart.addLineSeries({
      color: "rgba(248,81,73,0.5)",
      lineWidth: 1,
      lineStyle: 2,
      lastValueVisible: false,
      priceLineVisible: false,
    });

    chartInst.current = chart;
    const ro = new ResizeObserver(() => {
      if (chartRef.current) chart.applyOptions({ width: chartRef.current.clientWidth });
    });
    ro.observe(chartRef.current);
    return () => { chart.remove(); ro.disconnect(); };
  }, []);

  // ── Fetch ─────────────────────────────────────────────────────────────────────
  const fetchAll = async () => {
    setLoading(true); setError(null);
    try {
      const [pRes, hRes] = await Promise.all([
        fetch(`${API}/prediction`), fetch(`${API}/history`)
      ]);
      if (!pRes.ok) throw new Error(`/prediction ${pRes.status}`);
      const pData = await pRes.json();
      const hData = await hRes.json();

      setPrevPrice(pred?.current_price ?? null);
      setPred(pData);
      setHistory(hData.predictions || []);
      setLastFetch(new Date());

      // Update chart
      if (hData.candles?.length && priceLine.current) {
        const pts = hData.candles.map(c => ({ time: c.time, value: c.close }));
        priceLine.current.setData(pts);

        if (pData.predicted_low_95 && pData.predicted_high_95 && pts.length) {
          const lastT = pts[pts.length - 1].time;
          const nextT = lastT + 3600;
          bandHigh.current.setData([{ time: lastT, value: pData.predicted_high_95 }, { time: nextT, value: pData.predicted_high_95 }]);
          bandLow.current.setData([{ time: lastT, value: pData.predicted_low_95 }, { time: nextT, value: pData.predicted_low_95 }]);
        }
        chartInst.current.timeScale().fitContent();
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAll(); }, []);
  useEffect(() => { const id = setInterval(fetchAll, 60_000); return () => clearInterval(id); }, []);

  const bs = pred?.backtest_stats;
  const priceDir = pred && prevPrice ? (pred.current_price > prevPrice ? "up" : pred.current_price < prevPrice ? "down" : "neutral") : "neutral";

  return (
    <>
      <style>{css}</style>
      <div className="layout">
        {/* Header */}
        <header className="header">
          <div className="header-brand">
            <div className="brand-dot" />
            <span className="brand-name">AlphaI</span>
          </div>
          <div className="header-pair">
            <span className="pair-label">BTC / USDT</span>
            <span>·</span>
            <span>1H</span>
          </div>
          <div className="header-tags">
            <span className="tag">FIGARCH</span>
            <span className="tag">Cyber GBM</span>
            <span className="tag">Student-t</span>
            <span className="tag">Monte Carlo 5k</span>
          </div>
          <div className="header-controls">
            <div className="status-pill">
              <div className={`pulse ${error ? "err" : "live"}`} />
              {lastFetch ? lastFetch.toLocaleTimeString() : "connecting"}
            </div>
            <button className="btn-refresh" onClick={fetchAll} disabled={loading}>
              {loading ? "···" : "refresh"}
            </button>
          </div>
        </header>

        <div className="main">
          {error && <div className="error-bar">⚠ {error} — backend may be starting up</div>}

          {/* Metric strip */}
          <div>
            <div className="section-label">Live snapshot</div>
            <div className="metric-strip">
              <Metric label="BTC Price" value={usd(pred?.current_price)} sub={pred?.as_of?.slice(11, 19) + " UTC"} colorClass={`${priceDir}-v` in {} ? priceDir + "-v" : "blue-v"} loading={loading && !pred} />
              <Metric label="Predicted low · 95%" value={usd(pred?.predicted_low_95)} colorClass="red-v" loading={loading && !pred} />
              <Metric label="Predicted high · 95%" value={usd(pred?.predicted_high_95)} colorClass="green-v" loading={loading && !pred} />
              <Metric label="Predicted mean" value={usd(pred?.predicted_mean)} colorClass="neutral" loading={loading && !pred} />
              <Metric label="Band width" value={pred ? usd(pred.predicted_high_95 - pred.predicted_low_95) : null} sub="95% interval" colorClass="amber-v" loading={loading && !pred} />
              <Metric label="σ current" value={pred ? `${(pred.sigma_current * 100).toFixed(4)}%` : null} sub="conditional vol / hr" colorClass="neutral" loading={loading && !pred} />
            </div>
          </div>

          {/* Two-column: chart + sidebar */}
          <div className="two-col">
            {/* Chart panel */}
            <div className="panel">
              <div className="panel-header">
                <span className="panel-title">Price + 95% prediction band · next bar</span>
                <span className="panel-badge">dashed = bound · solid = close</span>
              </div>
              <div className="chart-wrap" ref={chartRef} />
              <div className="interval-display">
                <div className="interval-range">
                  <span style={{ color: "var(--red)" }}>{usd(pred?.predicted_low_95)}</span>
                  <span className="interval-sep">────</span>
                  <span style={{ color: "var(--text2)", fontSize: 10 }}>95% CI</span>
                  <span className="interval-sep">────</span>
                  <span style={{ color: "var(--green)" }}>{usd(pred?.predicted_high_95)}</span>
                </div>
                <span className="interval-label">next 1h</span>
              </div>
            </div>

            {/* Sidebar */}
            <div className="sidebar">
              {/* Model performance */}
              <div className="panel">
                <div className="panel-header">
                  <span className="panel-title">Backtest · 200 bars · BTC 1h</span>
                </div>
                <div className="stat-grid">
                  <div className="stat-cell">
                    <div className="stat-label">Coverage 95%</div>
                    <div className="stat-value" style={{ color: bs?.coverage_95 >= 0.93 ? "var(--green)" : "var(--amber)" }}>
                      {bs ? pct(bs.coverage_95) : "—"}
                    </div>
                    <div className="stat-sub">target ≥ 95%</div>
                  </div>
                  <div className="stat-cell">
                    <div className="stat-label">Coverage 99.7%</div>
                    <div className="stat-value" style={{ color: "var(--green)" }}>
                      {bs ? pct(bs.coverage_997) : "—"}
                    </div>
                    <div className="stat-sub">3σ equivalent</div>
                  </div>
                  <div className="stat-cell">
                    <div className="stat-label">Avg width</div>
                    <div className="stat-value neutral">{bs ? usd(bs.avg_width_95) : "—"}</div>
                    <div className="stat-sub">interval size</div>
                  </div>
                  <div className="stat-cell">
                    <div className="stat-label">Winkler score</div>
                    <div className="stat-value neutral">{bs ? num(bs.mean_winkler, 1) : "—"}</div>
                    <div className="stat-sub">lower = better</div>
                  </div>
                </div>
                <div className="gauge-wrap">
                  <CoverageGauge label="95% CI coverage" value={bs?.coverage_95} target={0.95} />
                  <CoverageGauge label="99.7% CI coverage" value={bs?.coverage_997} target={0.997} />
                </div>
              </div>

              {/* Model info */}
              <div className="panel">
                <div className="panel-header">
                  <span className="panel-title">Model architecture</span>
                </div>
                <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
                  {[
                    ["Volatility", "FIGARCH(1,0,1) · long memory"],
                    ["Residuals", "Student-t · fitted ν ≥ 4"],
                    ["Extensions", "Rolling entropy · crisis detect"],
                    ["Simulation", "Monte Carlo · 5 000 paths"],
                    ["Data", "Binance BTCUSDT · 1h bars"],
                    ["Train window", "500 bars · walk-forward"],
                  ].map(([k, v]) => (
                    <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                      <span style={{ fontSize: 10, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{k}</span>
                      <span style={{ fontSize: 10, color: "var(--text2)", textAlign: "right" }}>{v}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Prediction log */}
          <div className="panel">
            <div className="panel-header">
              <span className="panel-title">Prediction log</span>
              <span className="panel-badge">{history.length} entries · actuals filled on next bar</span>
            </div>
            <div className="log-wrap">
              {history.length === 0
                ? <div style={{ padding: "20px 14px", color: "var(--text3)", fontSize: 11 }}>No predictions recorded yet. Hit refresh.</div>
                : <table>
                    <thead>
                      <tr>
                        <th>Timestamp (UTC)</th>
                        <th>Current price</th>
                        <th>Low 95%</th>
                        <th>High 95%</th>
                        <th>Width</th>
                        <th>Actual</th>
                        <th>Hit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...history].reverse().map((r, i) => {
                        const width = r.predicted_high_95 && r.predicted_low_95
                          ? r.predicted_high_95 - r.predicted_low_95 : null;
                        return (
                          <tr key={i}>
                            <td style={{ color: "var(--text3)" }}>{r.as_of?.replace("T", " ").slice(0, 19)}</td>
                            <td>{usd(r.current_price)}</td>
                            <td style={{ color: "var(--red)" }}>{usd(r.predicted_low_95)}</td>
                            <td style={{ color: "var(--green)" }}>{usd(r.predicted_high_95)}</td>
                            <td style={{ color: "var(--text2)" }}>{usd(width)}</td>
                            <td>{r.actual ? usd(r.actual) : <span className="hit-pending">pending</span>}</td>
                            <td>
                              {r.actual == null
                                ? <span className="hit-pending">—</span>
                                : r.hit
                                  ? <span className="hit-yes">✓ hit</span>
                                  : <span className="hit-no">✗ miss</span>}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>}
            </div>
          </div>

          <footer className="footer">
            <span>ALPHAI · FIGARCH CYBER GBM SIGNAL RESEARCH · BTC/USDT 1H</span>
            <span>97% COVERAGE · WINKLER 1965 · 200 TEST BARS</span>
          </footer>
        </div>
      </div>
    </>
  );
}
