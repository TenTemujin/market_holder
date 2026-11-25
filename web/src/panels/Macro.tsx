import { useEffect, useState } from "react";
import { api, type Bar } from "../api";
import { num, px, sign, utc } from "../fmt";
import { useMarket } from "../store";

const iso = (d: Date) => d.toISOString().slice(0, 10);

async function historyAsOf(symbol: string, days: number, refIso?: string): Promise<Bar[]> {
  const endD = refIso ? new Date(refIso) : new Date();
  const startD = new Date(endD.getTime() - days * 864e5);
  const q = `symbol=${encodeURIComponent(symbol)}&freq=1d&start=${iso(startD)}&end=${iso(endD)}`;
  const bars = (await api<{ bars: Bar[] }>("GET", `/api/history?${q}`)).bars;
  if (!refIso) return bars;
  const cut = refIso.slice(0, 10);
  return bars.filter((b) => b.ts.slice(0, 10) <= cut);
}

function Spark({ values }: { values: number[] }) {
  if (values.length < 2) return <span className="dim">not enough data</span>;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 560},${118 - ((v - lo) / (hi - lo || 1)) * 108}`).join(" ");
  return (
    <svg width={560} height={124} role="img" aria-label="series chart" className="spark">
      <polyline points={`0,120 ${pts} 560,120`} fill="#ffa02818" stroke="none" />
      <polyline points={pts} fill="none" stroke="#ffa028" strokeWidth={1.6} />
    </svg>
  );
}

const TENORS: [string, string][] = [
  ["1M", "DGS1MO"], ["3M", "DGS3MO"], ["6M", "DGS6MO"], ["1Y", "DGS1"], ["2Y", "DGS2"], ["3Y", "DGS3"],
  ["5Y", "DGS5"], ["7Y", "DGS7"], ["10Y", "DGS10"], ["20Y", "DGS20"], ["30Y", "DGS30"],
];

/** US Treasury curve (FRED, official source) synchronized with session replay clock + key spreads (10Y-2Y, 10Y-3M). */
export function Curve() {
  const { snapshot } = useMarket();
  const asOf = snapshot?.clock.now;
  const [pts, setPts] = useState<{ label: string; y: number; ts: string }[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let alive = true;
    Promise.all(
      TENORS.map(async ([label, id]) => {
        const bars = await historyAsOf(`RATE:FRED:${id}`, 35, asOf);
        const b = bars[bars.length - 1];
        return b ? { label, y: Number(b.close), ts: b.ts } : null;
      }),
    ).then(
      (r) => alive && setPts(r.filter((x): x is { label: string; y: number; ts: string } => x !== null)),
      (e) => alive && setErr(String(e)),
    );
    return () => { alive = false; };
  }, [asOf]);
  if (err) return <div className="panel-body err">{err}</div>;
  if (!pts) return <div className="panel-body dim">Loading FRED yield curve…</div>;
  const lo = Math.min(...pts.map((p) => p.y));
  const hi = Math.max(...pts.map((p) => p.y));
  const xy = (i: number, y: number) => `${30 + (i / (pts.length - 1 || 1)) * 520},${110 - ((y - lo) / (hi - lo || 1)) * 90}`;

  const y3m = pts.find((p) => p.label === "3M")?.y;
  const y2y = pts.find((p) => p.label === "2Y")?.y;
  const y5y = pts.find((p) => p.label === "5Y")?.y;
  const y10y = pts.find((p) => p.label === "10Y")?.y;
  const y30y = pts.find((p) => p.label === "30Y")?.y;
  const s10_2 = y10y !== undefined && y2y !== undefined ? (y10y - y2y) * 100 : null;
  const s10_3m = y10y !== undefined && y3m !== undefined ? (y10y - y3m) * 100 : null;
  const s30_5 = y30y !== undefined && y5y !== undefined ? (y30y - y5y) * 100 : null;

  return (
    <div className="panel-body">
      <div className="kpis">
        <span>As of <b>{asOf ? utc(asOf).slice(0, 10) : "Latest"}</b></span>
        {s10_2 !== null && (
          <span className={s10_2 < 0 ? "down" : "up"}>
            2s10s Spread <b>{s10_2 >= 0 ? "+" : ""}{num(s10_2, 1)} bps</b> {s10_2 < 0 ? "(INVERTED)" : "(NORMAL)"}
          </span>
        )}
        {s10_3m !== null && (
          <span className={s10_3m < 0 ? "down" : "up"}>
            3m10s Spread <b>{s10_3m >= 0 ? "+" : ""}{num(s10_3m, 1)} bps</b>
          </span>
        )}
        {s30_5 !== null && (
          <span>5s30s Spread <b>{s30_5 >= 0 ? "+" : ""}{num(s30_5, 1)} bps</b></span>
        )}
      </div>
      <svg width={580} height={140} role="img" aria-label="yield curve" className="spark">
        <polyline points={pts.map((p, i) => xy(i, p.y)).join(" ")} fill="none" stroke="#ffa028" strokeWidth={2} />
        {pts.map((p, i) => (
          <g key={p.label}>
            <circle cx={30 + (i / (pts.length - 1 || 1)) * 520} cy={110 - ((p.y - lo) / (hi - lo || 1)) * 90} r={3} fill="#ffd400" />
            <text x={30 + (i / (pts.length - 1 || 1)) * 520} y={134} fill="#8a8a8a" fontSize={9} textAnchor="middle">{p.label}</text>
          </g>
        ))}
      </svg>
      <table className="grid">
        <thead><tr><th>Tenor</th><th className="r">Yield %</th><th>Observation Date</th></tr></thead>
        <tbody>{pts.map((p) => <tr key={p.label}><td className="sym">{p.label}</td><td className="r">{num(p.y, 2)}%</td><td>{utc(p.ts).slice(0, 10)}</td></tr>)}</tbody>
      </table>
      <div className="dim">Source: FRED (St. Louis Fed), constant-maturity Treasury yields, synchronized to session clock (no lookahead).</div>
    </div>
  );
}

const SERIES = [
  { id: "RATE:BCB:SELIC_META", name: "Brazil: Selic Target (% p.a.)", src: "BCB SGS 432" },
  { id: "RATE:BCB:IPCA", name: "Brazil: IPCA Monthly (%)", src: "BCB SGS 433" },
  { id: "FX:BCB:USDBRL", name: "USD/BRL PTAX (Official Sell)", src: "BCB Olinda" },
  { id: "RATE:FRED:FEDFUNDS", name: "US: Effective Fed Funds (%)", src: "FRED" },
  { id: "RATE:FRED:CPIAUCSL", name: "US: Consumer Price Index (CPI)", src: "FRED" },
  { id: "RATE:FRED:UNRATE", name: "US: Unemployment Rate (%)", src: "FRED" },
];

export function Eco({ initial }: { initial?: string }) {
  const { snapshot } = useMarket();
  const asOf = snapshot?.clock.now;
  const [sel, setSel] = useState(initial ?? SERIES[0].id);
  const [bars, setBars] = useState<Bar[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let alive = true;
    setBars(null);
    setErr("");
    historyAsOf(sel, 365 * 3, asOf).then((b) => alive && setBars(b), (e) => alive && setErr(String(e)));
    return () => { alive = false; };
  }, [sel, asOf]);
  const meta = SERIES.find((s) => s.id === sel) ?? SERIES[0];
  const closes = (bars ?? []).map((b) => Number(b.close));
  const last = bars?.[bars.length - 1];
  const prev = bars && bars.length > 1 ? bars[bars.length - 2] : undefined;
  const releases = (bars ?? []).slice(-10).reverse();

  return (
    <div className="panel-body form">
      <label>Macro Indicator Series
        <select aria-label="Series" value={sel} onChange={(e) => setSel(e.target.value)}>
          {SERIES.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </label>
      {err && <div className="err">{err}</div>}
      {!bars && !err && <div className="dim">Loading…</div>}
      {bars && <Spark values={closes} />}
      {last && (
        <div className="kpis">
          <span>Actual <b>{num(last.close, 4)}</b></span>
          {prev && <span>Prior <b>{num(prev.close, 4)}</b></span>}
          {prev && (
            <span className={sign(Number(last.close) - Number(prev.close))}>
              Delta <b>{Number(last.close) - Number(prev.close) >= 0 ? "+" : ""}{num(Number(last.close) - Number(prev.close), 4)}</b>
            </span>
          )}
          <span>Release Date <b>{utc(last.ts).slice(0, 10)}</b> · {bars.length} pts</span>
        </div>
      )}
      {releases.length > 0 && (
        <>
          <h4>Historical Release Calendar (Synced to Replay Clock)</h4>
          <table className="grid">
            <thead>
              <tr><th>Date</th><th>Indicator</th><th className="r">Prior</th><th className="r">Consensus (MA3)</th><th className="r">Actual</th><th className="r">Surprise</th></tr>
            </thead>
            <tbody>
              {releases.map((b, idx) => {
                const fullIdx = (bars?.length ?? 1) - 1 - idx;
                const priorVal = fullIdx > 0 && bars ? Number(bars[fullIdx - 1].close) : Number(b.close);
                const slice3 = bars ? bars.slice(Math.max(0, fullIdx - 3), fullIdx).map((x) => Number(x.close)) : [];
                const cons = slice3.length ? slice3.reduce((a, v) => a + v, 0) / slice3.length : priorVal;
                const act = Number(b.close);
                const surp = act - cons;
                return (
                  <tr key={b.ts}>
                    <td>{utc(b.ts).slice(0, 10)}</td>
                    <td className="sym">{meta.name}</td>
                    <td className="r">{num(priorVal, 3)}</td>
                    <td className="r dim">{num(cons, 3)}</td>
                    <td className="r"><b>{num(act, 3)}</b></td>
                    <td className={`r ${sign(surp)}`}>{surp >= 0 ? "+" : ""}{num(surp, 3)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
      <div className="dim">Official source: {meta.src}. Real historical data synchronized with replay timestamp.</div>
    </div>
  );
}

const FX_PAIRS: [string, string][] = [
  ["USD/BRL (PTAX)", "FX:BCB:USDBRL"],
  ["EUR/USD", "FX:YAHOO:EURUSD"],
  ["USD/JPY", "FX:YAHOO:USDJPY"],
  ["GBP/USD", "FX:YAHOO:GBPUSD"],
  ["AUD/USD", "FX:YAHOO:AUDUSD"],
];

export function FxPanel() {
  const { snapshot } = useMarket();
  const asOf = snapshot?.clock.now;
  const [rates, setRates] = useState<{ label: string; symbol: string; last: number; chgPct: number; ts: string }[]>([]);
  const [usdBrl, setUsdBrl] = useState(5.0);
  const [eurUsd, setEurUsd] = useState(1.08);
  const [usdJpy, setUsdJpy] = useState(150.0);
  const [gbpUsd, setGbpUsd] = useState(1.27);

  useEffect(() => {
    let alive = true;
    Promise.all(
      FX_PAIRS.map(async ([label, sym]) => {
        try {
          const bars = await historyAsOf(sym, 15, asOf);
          const lastBar = bars[bars.length - 1];
          const prevBar = bars[bars.length - 2] ?? lastBar;
          if (!lastBar) return null;
          const last = Number(lastBar.close);
          const prev = Number(prevBar.close) || last;
          return { label, symbol: sym, last, chgPct: ((last - prev) / prev) * 100, ts: lastBar.ts };
        } catch {
          return null;
        }
      }),
    ).then((res) => {
      if (!alive) return;
      const valid = res.filter((x): x is NonNullable<typeof x> => x !== null);
      setRates(valid);
      for (const r of valid) {
        if (r.symbol.endsWith("USDBRL")) setUsdBrl(r.last);
        if (r.symbol.endsWith("EURUSD")) setEurUsd(r.last);
        if (r.symbol.endsWith("USDJPY")) setUsdJpy(r.last);
        if (r.symbol.endsWith("GBPUSD")) setGbpUsd(r.last);
      }
    });
    return () => { alive = false; };
  }, [asOf]);

  // Cross-rate matrix: base (row) vs quote (col) in USD terms
  const toUsd: Record<string, number> = {
    USD: 1.0,
    EUR: eurUsd,
    GBP: gbpUsd,
    BRL: 1.0 / (usdBrl || 5.0),
    JPY: 1.0 / (usdJpy || 150.0),
  };
  const ccys = ["USD", "EUR", "GBP", "JPY", "BRL"];

  return (
    <div className="panel-body form">
      <h4>FX Spot &amp; Cross-Rates Matrix</h4>
      <table className="grid">
        <thead>
          <tr>
            <th>Base \ Quote</th>
            {ccys.map((c) => <th key={c} className="r">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {ccys.map((rCcy) => (
            <tr key={rCcy}>
              <td className="sym">{rCcy}</td>
              {ccys.map((cCcy) => {
                const cross = toUsd[rCcy] / toUsd[cCcy];
                return (
                  <td key={cCcy} className={`r ${rCcy === cCcy ? "dim" : ""}`}>
                    {rCcy === cCcy ? "1.0000" : px(cross)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      {rates.length > 0 && (
        <>
          <h4>Major Currency Feeds</h4>
          <table className="grid">
            <thead><tr><th>Pair</th><th className="r">Spot</th><th className="r">1D %Chg</th><th>As of</th></tr></thead>
            <tbody>
              {rates.map((r) => (
                <tr key={r.symbol}>
                  <td className="sym">{r.label}</td>
                  <td className="r">{px(r.last)}</td>
                  <td className={`r ${sign(r.chgPct)}`}>{r.chgPct >= 0 ? "+" : ""}{num(r.chgPct, 2)}%</td>
                  <td>{utc(r.ts).slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <div className="dim">Cross rates derived from BCB PTAX (official) and global spot feeds as of the session timestamp.</div>
    </div>
  );
}
