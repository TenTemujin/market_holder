import { useEffect, useState } from "react";
import { api, type Bar } from "../api";
import { num, utc } from "../fmt";

const iso = (d: Date) => d.toISOString().slice(0, 10);
const daysAgo = (n: number) => iso(new Date(Date.now() - n * 864e5));

async function history(symbol: string, days: number): Promise<Bar[]> {
  const q = `symbol=${encodeURIComponent(symbol)}&freq=1d&start=${daysAgo(days)}&end=${iso(new Date())}`;
  return (await api<{ bars: Bar[] }>("GET", `/api/history?${q}`)).bars;
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

/** US Treasury curve (FRED, official source): latest available point of each tenor. */
export function Curve() {
  const [pts, setPts] = useState<{ label: string; y: number; ts: string }[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let alive = true;
    Promise.all(
      TENORS.map(async ([label, id]) => {
        const bars = await history(`RATE:FRED:${id}`, 20);
        const b = bars[bars.length - 1];
        return b ? { label, y: Number(b.close), ts: b.ts } : null;
      }),
    ).then(
      (r) => alive && setPts(r.filter((x): x is { label: string; y: number; ts: string } => x !== null)),
      (e) => alive && setErr(String(e)),
    );
    return () => { alive = false; };
  }, []);
  if (err) return <div className="panel-body err">{err}</div>;
  if (!pts) return <div className="panel-body dim">Loading FRED…</div>;
  const lo = Math.min(...pts.map((p) => p.y));
  const hi = Math.max(...pts.map((p) => p.y));
  const xy = (i: number, y: number) => `${30 + (i / (pts.length - 1 || 1)) * 520},${110 - ((y - lo) / (hi - lo || 1)) * 90}`;
  return (
    <div className="panel-body">
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
        <thead><tr><th>Tenor</th><th className="r">Yield %</th><th>As of</th></tr></thead>
        <tbody>{pts.map((p) => <tr key={p.label}><td>{p.label}</td><td className="r">{num(p.y, 2)}</td><td>{utc(p.ts).slice(0, 10)}</td></tr>)}</tbody>
      </table>
      <div className="dim">Source: FRED (St. Louis Fed), constant-maturity Treasury yields. Delay: 1 business day.</div>
    </div>
  );
}

const SERIES = [
  { id: "RATE:BCB:SELIC_META", name: "Brazil: Selic target (% p.a.)", src: "BCB SGS 432" },
  { id: "RATE:BCB:IPCA", name: "Brazil: IPCA monthly (%)", src: "BCB SGS 433" },
  { id: "FX:BCB:USDBRL", name: "USD/BRL PTAX (sell)", src: "BCB Olinda" },
  { id: "RATE:FRED:FEDFUNDS", name: "US: Fed Funds (%)", src: "FRED" },
  { id: "RATE:FRED:CPIAUCSL", name: "US: CPI (index)", src: "FRED" },
  { id: "RATE:FRED:UNRATE", name: "US: Unemployment rate (%)", src: "FRED" },
];

export function Eco({ initial }: { initial?: string }) {
  const [sel, setSel] = useState(initial ?? SERIES[0].id);
  const [bars, setBars] = useState<Bar[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let alive = true;
    setBars(null);
    setErr("");
    history(sel, 365 * 3).then((b) => alive && setBars(b), (e) => alive && setErr(String(e)));
    return () => { alive = false; };
  }, [sel]);
  const meta = SERIES.find((s) => s.id === sel)!;
  const closes = (bars ?? []).map((b) => Number(b.close));
  const last = bars?.[bars.length - 1];
  return (
    <div className="panel-body form">
      <label>Series
        <select aria-label="Series" value={sel} onChange={(e) => setSel(e.target.value)}>
          {SERIES.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </label>
      {err && <div className="err">{err}</div>}
      {!bars && !err && <div className="dim">Loading…</div>}
      {bars && <Spark values={closes} />}
      {last && <div>Latest: <b>{num(last.close, 4)}</b> on {utc(last.ts).slice(0, 10)} · {bars!.length} points</div>}
      <div className="dim">Official source: {meta.src}. Real data, not simulated.</div>
    </div>
  );
}
