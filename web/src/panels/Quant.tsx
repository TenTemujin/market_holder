import { useEffect, useState } from "react";
import { api, type CorrelationResp, type MonteCarloResp, type ScreenerRow } from "../api";
import { num, px, secName, sign } from "../fmt";
import { useMarket, usePanels } from "../store";

/** EQS: Dynamic Equity & Multi-Asset Screener */
export function Eqs() {
  const { snapshot } = useMarket();
  const { open } = usePanels();
  const [rows, setRows] = useState<ScreenerRow[]>([]);
  const [filter, setFilter] = useState<"ALL" | "GAINERS" | "LOSERS" | "RVOL" | "OVERSOLD" | "OVERBOUGHT" | "BREAKOUT">("ALL");
  const [minRvol, setMinRvol] = useState("0");

  useEffect(() => {
    if (!snapshot) return;
    let alive = true;
    api<{ rows: ScreenerRow[] }>("GET", "/api/quant/screener").then(
      (r) => alive && setRows(r.rows),
      () => undefined,
    );
    return () => { alive = false; };
  }, [snapshot?.clock.now, snapshot?.id]);

  if (!snapshot) return <div className="panel-body dim">No session. Press F10 (REPLAY) to start one.</div>;

  const rvolFloor = Number(minRvol) || 0;
  const filtered = rows.filter((r) => {
    if (r.rvol < rvolFloor) return false;
    if (filter === "GAINERS") return r.chg_pct > 0;
    if (filter === "LOSERS") return r.chg_pct < 0;
    if (filter === "RVOL") return r.rvol >= 1.5;
    if (filter === "OVERSOLD") return r.rsi14 !== null && r.rsi14 <= 35;
    if (filter === "OVERBOUGHT") return r.rsi14 !== null && r.rsi14 >= 65;
    if (filter === "BREAKOUT") return r.breakout !== "INSIDE";
    return true;
  });

  return (
    <div className="panel-body form">
      <div className="row">
        {(["ALL", "GAINERS", "LOSERS", "RVOL", "OVERSOLD", "OVERBOUGHT", "BREAKOUT"] as const).map((f) => (
          <button key={f} className={filter === f ? "on buy" : ""} onClick={() => setFilter(f)}>{f}</button>
        ))}
        <label>Min RVOL
          <input aria-label="Min RVOL" value={minRvol} onChange={(e) => setMinRvol(e.target.value)} size={4} />
        </label>
        <span className="dim">{filtered.length} / {rows.length} securities</span>
      </div>
      <table className="grid">
        <thead>
          <tr>
            <th>Security</th>
            <th className="r">Last</th>
            <th className="r">%Chg</th>
            <th className="r">RVOL (20)</th>
            <th className="r">RSI (14)</th>
            <th className="r">20B High</th>
            <th className="r">20B Low</th>
            <th>20B Range Status</th>
            <th className="r">Ann. Vol %</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((r) => (
            <tr key={r.symbol} className="click" onDoubleClick={() => open("GP", r.symbol)}>
              <td className="sym">{secName(r.symbol)}</td>
              <td className="r">{px(r.last)}</td>
              <td className={`r ${sign(r.chg_pct)}`}>{r.chg_pct >= 0 ? "+" : ""}{num(r.chg_pct, 2)}%</td>
              <td className={`r ${r.rvol >= 1.8 ? "up" : ""}`}>{num(r.rvol, 2)}x</td>
              <td className={`r ${r.rsi14 !== null && r.rsi14 >= 70 ? "down" : r.rsi14 !== null && r.rsi14 <= 30 ? "up" : ""}`}>
                {r.rsi14 !== null ? num(r.rsi14, 1) : "–"}
              </td>
              <td className="r">{px(r.high_20)}</td>
              <td className="r">{px(r.low_20)}</td>
              <td className={r.breakout === "HIGH_BREAK" ? "up" : r.breakout === "LOW_BREAK" ? "down" : "dim"}>
                {r.breakout === "HIGH_BREAK" ? "▲ 20B HIGH BREAK" : r.breakout === "LOW_BREAK" ? "▼ 20B LOW BREAK" : "INSIDE"}
              </td>
              <td className="r">{num(r.vol_annual, 1)}%</td>
              <td>
                <button className="mini" onClick={() => open("GP", r.symbol)}>GP</button>{" "}
                <button className="mini" onClick={() => open("ORD", r.symbol)}>ORD</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="dim">Computed strictly on processed session bars (zero lookahead). Double-click any row to open GP.</div>
    </div>
  );
}

/** CORR: Cross-Asset Correlation Heatmap & Benchmark Beta */
export function Corr() {
  const { snapshot } = useMarket();
  const [bench, setBench] = useState("");
  const [data, setData] = useState<CorrelationResp | null>(null);

  useEffect(() => {
    if (!snapshot) return;
    let alive = true;
    const q = bench ? `?benchmark=${encodeURIComponent(bench)}` : "";
    api<CorrelationResp>("GET", `/api/quant/correlation${q}`).then(
      (r) => alive && setData(r),
      () => undefined,
    );
    return () => { alive = false; };
  }, [snapshot?.clock.now, snapshot?.id, bench]);

  if (!snapshot) return <div className="panel-body dim">No session. Press F10 (REPLAY) to start one.</div>;

  const heatBg = (v: number) => {
    const a = Math.min(0.55, Math.abs(v) * 0.55);
    return v >= 0 ? `rgba(0, 210, 106, ${a.toFixed(2)})` : `rgba(255, 59, 59, ${a.toFixed(2)})`;
  };

  return (
    <div className="panel-body form">
      <div className="row">
        <label>Benchmark Security
          <select aria-label="Benchmark" value={bench} onChange={(e) => setBench(e.target.value)}>
            <option value="">Auto (first security)</option>
            {snapshot.quotes.map((q) => <option key={q.symbol} value={q.symbol}>{secName(q.symbol)}</option>)}
          </select>
        </label>
        {data?.benchmark && <span className="kv">Active Benchmark: <b>{secName(data.benchmark)}</b></span>}
      </div>
      {data && (
        <table className="grid">
          <thead>
            <tr>
              <th>Security</th>
              <th className="r">Beta (β)</th>
              {data.symbols.map((s) => <th key={s} className="r">{secName(s).split(" ")[0]}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.symbols.map((s, i) => (
              <tr key={s}>
                <td className="sym">{secName(s)}</td>
                <td className="r"><b>{num(data.betas[s] ?? 1, 2)}</b></td>
                {data.matrix[i].map((v, j) => (
                  <td key={data.symbols[j]} className="r" style={{ background: heatBg(v) }}>
                    {num(v, 2)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="dim">Rolling return correlation matrix and beta vs. benchmark across session history.</div>
    </div>
  );
}

/** MC: Monte Carlo Bootstrap Simulator for Equity Curve, Drawdown & Risk of Ruin */
export function Mc() {
  const { snapshot } = useMarket();
  const [paths, setPaths] = useState("400");
  const [horizon, setHorizon] = useState("50");
  const [data, setData] = useState<MonteCarloResp | null>(null);

  const run = () => {
    if (!snapshot) return;
    api<MonteCarloResp>("GET", `/api/quant/montecarlo?paths=${Number(paths) || 400}&horizon=${Number(horizon) || 50}`).then(
      setData,
      () => undefined,
    );
  };

  useEffect(() => {
    run();
  }, [snapshot?.id, snapshot?.fills.length]);

  if (!snapshot) return <div className="panel-body dim">No session. Press F10 (REPLAY) to start one.</div>;

  const renderFan = (mc: MonteCarloResp) => {
    if (!mc.fan_paths.length) return null;
    const allVals = mc.fan_paths.flat();
    const lo = Math.min(...allVals);
    const hi = Math.max(...allVals);
    const w = 620;
    const h = 160;
    return (
      <svg width={w} height={h} className="spark" role="img" aria-label="Monte Carlo equity fan">
        {mc.fan_paths.map((curve, idx) => {
          const pts = curve
            .map((v, i) => `${(i / (curve.length - 1 || 1)) * (w - 20) + 10},${h - 14 - ((v - lo) / (hi - lo || 1)) * (h - 28)}`)
            .join(" ");
          return (
            <polyline
              key={idx}
              points={pts}
              fill="none"
              stroke={curve[curve.length - 1] >= mc.initial_equity ? "#00d26a55" : "#ff3b3b55"}
              strokeWidth={1.2}
            />
          );
        })}
      </svg>
    );
  };

  return (
    <div className="panel-body form">
      <div className="row">
        <label>Simulations<input aria-label="Simulations" value={paths} onChange={(e) => setPaths(e.target.value)} size={6} /></label>
        <label>Horizon (Trades)<input aria-label="Horizon" value={horizon} onChange={(e) => setHorizon(e.target.value)} size={5} /></label>
        <button onClick={run}>Run Monte Carlo</button>
      </div>
      {data && (
        <>
          {data.synthetic && (
            <div className="warn">
              REFERENCE DISTRIBUTION: fewer than 2 closed trades in blotter; showing baseline +/-1% sigma projection until you close trades.
            </div>
          )}
          <div className="kpis">
            <span>Closed Trades <b>{data.sample_size}</b></span>
            <span>Win Rate <b>{num(data.win_rate, 1)}%</b></span>
            <span>Profit Factor <b>{num(data.profit_factor, 2)}</b></span>
            <span>Expectancy <b>{num(data.expectancy, 2)}</b></span>
            <span className={data.prob_ruin_pct > 10 ? "down" : "up"}>Risk of Ruin (-50% DD) <b>{num(data.prob_ruin_pct, 2)}%</b></span>
          </div>
          {renderFan(data)}
          <table className="grid">
            <thead>
              <tr>
                <th>Metric</th>
                <th className="r">5th Percentile (Bear)</th>
                <th className="r">50th Percentile (Median)</th>
                <th className="r">95th Percentile (Bull)</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Projected Terminal Equity ({snapshot.base_currency})</td>
                <td className="r down">{num(data.equity_p5)}</td>
                <td className="r"><b>{num(data.equity_p50)}</b></td>
                <td className="r up">{num(data.equity_p95)}</td>
              </tr>
              <tr>
                <td>Maximum Drawdown (%)</td>
                <td className="r">–</td>
                <td className="r down">{num(data.max_dd_p50_pct, 2)}%</td>
                <td className="r down"><b>{num(data.max_dd_p95_pct, 2)}% (95% Worst)</b></td>
              </tr>
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
