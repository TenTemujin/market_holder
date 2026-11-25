import { useEffect, useState } from "react";
import { api, type CorrelationResp, type MonteCarloResp, type ScreenerRow, type SessionStatsResp } from "../api";
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

/** BOT: Automated Trading Strategy & Bot Console */
export function BotPanel() {
  const { snapshot, refresh } = useMarket();
  const [sym, setSym] = useState("");
  const [strategy, setStrategy] = useState<"SMA_CROSS" | "RSI_REV" | "TURTLE_20" | "VWAP_TREND">("SMA_CROSS");
  const [qty, setQty] = useState("10");
  const [p1, setP1] = useState("5");
  const [p2, setP2] = useState("15");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!sym && snapshot?.quotes.length) setSym(snapshot.quotes[0].symbol);
  }, [snapshot, sym]);

  if (!snapshot) return <div className="panel-body dim">No session. Press F10 (REPLAY) to start one.</div>;

  const createBot = async () => {
    if (!sym) return;
    const params: Record<string, number> =
      strategy === "SMA_CROSS"
        ? { fast: Number(p1) || 5, slow: Number(p2) || 15 }
        : strategy === "RSI_REV"
        ? { period: 14, oversold: Number(p1) || 32, overbought: Number(p2) || 68 }
        : { lookback: Number(p1) || 10 };
    try {
      await api("POST", "/api/bots", { symbol: sym, strategy, qty, params });
      setMsg(`Deployed ${strategy} bot on ${secName(sym)}`);
      void refresh();
    } catch (e) {
      setMsg(String(e));
    }
  };

  const toggle = async (id: string) => {
    await api("PATCH", `/api/bots/${id}`);
    void refresh();
  };

  const remove = async (id: string) => {
    await api("DELETE", `/api/bots/${id}`);
    void refresh();
  };

  const runHeadlessBacktest = async () => {
    try {
      await api("POST", "/api/clock", { action: "fast_forward", steps: 10000 });
      setMsg("Headless backtest completed (up to 10,000 steps). Open STATS or PORT for results.");
      void refresh();
    } catch (e) {
      setMsg(String(e));
    }
  };

  const bots = snapshot.bots ?? [];

  return (
    <div className="panel-body form">
      <div className="block">
        <div className="row">
          <label>Security
            <select aria-label="Bot Security" value={sym} onChange={(e) => setSym(e.target.value)}>
              {snapshot.quotes.map((q) => <option key={q.symbol} value={q.symbol}>{secName(q.symbol)}</option>)}
            </select>
          </label>
          <label>Strategy Logic
            <select
              aria-label="Bot Strategy"
              value={strategy}
              onChange={(e) => {
                const s = e.target.value as typeof strategy;
                setStrategy(s);
                if (s === "SMA_CROSS") { setP1("5"); setP2("15"); }
                else if (s === "RSI_REV") { setP1("32"); setP2("68"); }
                else { setP1("10"); setP2("20"); }
              }}
            >
              <option value="SMA_CROSS">SMA Golden/Death Crossover</option>
              <option value="RSI_REV">RSI(14) Mean Reversion (Oversold/Overbought)</option>
              <option value="TURTLE_20">Donchian / Turtle Channel Breakout</option>
              <option value="VWAP_TREND">Session VWAP Momentum Crossover</option>
            </select>
          </label>
          <label>Order Lot Qty
            <input aria-label="Bot Qty" value={qty} onChange={(e) => setQty(e.target.value)} size={6} />
          </label>
          {strategy === "SMA_CROSS" && (
            <>
              <label>Fast SMA<input aria-label="Fast SMA" value={p1} onChange={(e) => setP1(e.target.value)} size={4} /></label>
              <label>Slow SMA<input aria-label="Slow SMA" value={p2} onChange={(e) => setP2(e.target.value)} size={4} /></label>
            </>
          )}
          {strategy === "RSI_REV" && (
            <>
              <label>Buy RSI ≤<input aria-label="Oversold" value={p1} onChange={(e) => setP1(e.target.value)} size={4} /></label>
              <label>Sell RSI ≥<input aria-label="Overbought" value={p2} onChange={(e) => setP2(e.target.value)} size={4} /></label>
            </>
          )}
          {strategy === "TURTLE_20" && (
            <label>Channel Bars<input aria-label="Lookback" value={p1} onChange={(e) => setP1(e.target.value)} size={4} /></label>
          )}
          <button className="on buy" onClick={createBot}>+ Deploy Bot</button>
          {snapshot.meta.mode !== "live" && (
            <button onClick={runHeadlessBacktest} title="Run active bots through the entire replay at 10,000x speed">
              ⚡ Run 10,000x Backtest
            </button>
          )}
        </div>
        {msg && <div className="ok">{msg}</div>}
      </div>

      <h4>Active &amp; Deployed Strategy Bots ({bots.length})</h4>
      <table className="grid">
        <thead>
          <tr><th>ID</th><th>Strategy</th><th>Security</th><th className="r">Lot Qty</th><th className="r">Signals</th><th>Last Signal &amp; Order</th><th>Status</th><th /></tr>
        </thead>
        <tbody>
          {bots.length === 0 && <tr><td colSpan={8} className="dim">No bots deployed. Deploy one above and step or fast-forward the replay clock.</td></tr>}
          {bots.map((b) => (
            <tr key={b.id}>
              <td>{b.id}</td>
              <td className="sym">{b.strategy}</td>
              <td className="sym">{secName(b.symbol)}</td>
              <td className="r">{num(b.qty, 4)}</td>
              <td className="r"><b>{b.signals_count}</b></td>
              <td className="dim">{b.last_signal}</td>
              <td className={b.active ? "up" : "down"}>{b.active ? "RUNNING" : "PAUSED"}</td>
              <td>
                <button className="mini" onClick={() => toggle(b.id)}>{b.active ? "Pause" : "Resume"}</button>{" "}
                <button className="mini" onClick={() => remove(b.id)}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="dim">
        Bots evaluate strictly on closed session bars (zero lookahead) and route market orders into the main PORT account.
      </div>
    </div>
  );
}

/** STATS: Institutional Performance Tear Sheet (Sharpe, Sortino, Calmar, Max DD & Base-100 Equity vs Benchmark) */
export function StatsPanel() {
  const { snapshot } = useMarket();
  const [stats, setStats] = useState<SessionStatsResp | null>(null);

  useEffect(() => {
    if (!snapshot) return;
    let alive = true;
    api<SessionStatsResp>("GET", "/api/quant/stats").then(
      (r) => alive && setStats(r),
      () => undefined,
    );
    return () => { alive = false; };
  }, [snapshot?.clock.now, snapshot?.id, snapshot?.fills.length]);

  if (!snapshot) return <div className="panel-body dim">No session. Press F10 (REPLAY) to start one.</div>;

  const renderCurve = (st: SessionStatsResp) => {
    if (st.curve.length < 2) return <div className="dim">Advance the replay clock to build the equity curve.</div>;
    const vals = st.curve.flatMap((c) => [c.eq_base100, c.bench_base100]);
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const w = 620;
    const h = 165;
    const toPts = (key: "eq_base100" | "bench_base100") =>
      st.curve
        .map((c, i) => `${(i / (st.curve.length - 1 || 1)) * (w - 24) + 12},${h - 16 - ((c[key] - lo) / (hi - lo || 1)) * (h - 32)}`)
        .join(" ");
    return (
      <svg width={w} height={h} className="spark" role="img" aria-label="Equity vs Benchmark Base 100">
        <polyline points={toPts("bench_base100")} fill="none" stroke="#7a7a7a" strokeWidth={1.3} strokeDasharray="3,3" />
        <polyline points={toPts("eq_base100")} fill="none" stroke="#ffa028" strokeWidth={2.2} />
      </svg>
    );
  };

  return (
    <div className="panel-body form">
      {stats && (
        <>
          <div className="kpis">
            <span className={sign(stats.total_return_pct)}>Total Return <b>{stats.total_return_pct >= 0 ? "+" : ""}{num(stats.total_return_pct, 2)}%</b></span>
            <span className={sign(stats.benchmark_return_pct)}>Benchmark (Buy&amp;Hold) <b>{stats.benchmark_return_pct >= 0 ? "+" : ""}{num(stats.benchmark_return_pct, 2)}%</b></span>
            <span className={sign(stats.alpha_pct)}>Net Alpha <b>{stats.alpha_pct >= 0 ? "+" : ""}{num(stats.alpha_pct, 2)}%</b></span>
            <span>Sharpe Ratio <b>{num(stats.sharpe, 2)}</b></span>
            <span>Sortino Ratio <b>{num(stats.sortino, 2)}</b></span>
            <span>Calmar Ratio <b>{num(stats.calmar, 2)}</b></span>
            <span className="down">Max Drawdown <b>-{num(stats.max_drawdown_pct, 2)}%</b></span>
            <span>Win Rate <b>{num(stats.win_rate_pct, 1)}%</b> ({stats.trades_closed} trades)</span>
            <span>Profit Factor <b>{num(stats.profit_factor, 2)}</b></span>
          </div>
          <h4>Normalized Performance Curve (Base 100: <span style={{ color: "#ffa028" }}>■ Portfolio Equity</span> vs. <span className="dim">┅ Benchmark Buy &amp; Hold</span>)</h4>
          {renderCurve(stats)}
        </>
      )}
    </div>
  );
}
