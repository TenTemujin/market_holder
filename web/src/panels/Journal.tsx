import { useEffect, useState } from "react";
import { num, px, secName, sign } from "../fmt";
import { useMarket } from "../store";

export interface JournalEntry {
  id: string;
  ts: string;
  symbol: string;
  side: "BUY" | "SELL";
  setup: string;
  confidence: number;
  pnl: number;
  tags: string[];
  notes: string;
}

const JRNL_KEY = "mh.journal.v1";
const ALRT_KEY = "mh.alerts.v1";

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function Jrnl() {
  const { snapshot } = useMarket();
  const [entries, setEntries] = useState<JournalEntry[]>(() => loadJson(JRNL_KEY, []));
  const [symbol, setSymbol] = useState(snapshot?.quotes[0]?.symbol ?? "EQ:US:AAPL");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [setup, setSetup] = useState("Breakout");
  const [confidence, setConfidence] = useState(4);
  const [pnl, setPnl] = useState("0");
  const [tagsText, setTagsText] = useState("#breakout #trend");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    window.localStorage.setItem(JRNL_KEY, JSON.stringify(entries));
  }, [entries]);

  const addEntry = () => {
    const tags = tagsText
      .split(/[\s,]+/)
      .map((t) => t.trim().toLowerCase())
      .filter(Boolean)
      .map((t) => (t.startsWith("#") ? t : `#${t}`));
    const rec: JournalEntry = {
      id: `J${Date.now()}`,
      ts: snapshot?.clock.now ?? new Date().toISOString(),
      symbol,
      side,
      setup,
      confidence,
      pnl: Number(pnl) || 0,
      tags: tags.length ? tags : ["#untagged"],
      notes,
    };
    setEntries([rec, ...entries]);
    setNotes("");
  };

  const importRealized = () => {
    if (!snapshot) return;
    const added: JournalEntry[] = [];
    for (const [sym, val] of Object.entries(snapshot.realized)) {
      const p = Number(val);
      if (p === 0) continue;
      added.push({
        id: `J${Date.now()}-${sym}`,
        ts: snapshot.clock.now,
        symbol: sym,
        side: p >= 0 ? "BUY" : "SELL",
        setup: "Session Realized",
        confidence: 3,
        pnl: p,
        tags: [p >= 0 ? "#winner" : "#loser", "#session"],
        notes: `Imported from Session #${snapshot.id}`,
      });
    }
    if (added.length) setEntries([...added, ...entries]);
  };

  // Tag attribution analytics
  const tagStats = new Map<string, { count: number; wins: number; totalPnl: number }>();
  for (const e of entries) {
    for (const t of e.tags) {
      const cur = tagStats.get(t) ?? { count: 0, wins: 0, totalPnl: 0 };
      cur.count += 1;
      if (e.pnl > 0) cur.wins += 1;
      cur.totalPnl += e.pnl;
      tagStats.set(t, cur);
    }
  }

  return (
    <div className="panel-body form">
      <div className="block">
        <div className="row">
          <label>Security
            <input aria-label="Journal Security" value={symbol} onChange={(e) => setSymbol(e.target.value)} size={18} />
          </label>
          <label>Side
            <select aria-label="Journal Side" value={side} onChange={(e) => setSide(e.target.value as "BUY" | "SELL")}>
              <option>BUY</option><option>SELL</option>
            </select>
          </label>
          <label>Setup
            <select aria-label="Setup" value={setup} onChange={(e) => setSetup(e.target.value)}>
              {["Breakout", "VWAP Pullback", "Mean Reversion", "Macro Release", "Option Spread", "Scalp"].map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <label>Confidence (1-5)
            <select aria-label="Confidence" value={confidence} onChange={(e) => setConfidence(Number(e.target.value))}>
              {[1, 2, 3, 4, 5].map((c) => <option key={c} value={c}>{c} ★</option>)}
            </select>
          </label>
          <label>Net P&amp;L
            <input aria-label="Net P&L" value={pnl} onChange={(e) => setPnl(e.target.value)} size={8} />
          </label>
          <label>Tags
            <input aria-label="Tags" value={tagsText} onChange={(e) => setTagsText(e.target.value)} placeholder="#breakout #fomo #news" size={18} />
          </label>
        </div>
        <div className="row">
          <label style={{ flex: 1 }}>Trade Notes &amp; Thesis
            <input aria-label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Entry catalyst, execution quality, emotional state…" />
          </label>
          <button className="on buy" onClick={addEntry}>Log Trade</button>
          {snapshot && <button onClick={importRealized}>Import Session P&amp;L</button>}
        </div>
      </div>

      <h4>Performance by Tag</h4>
      <table className="grid">
        <thead>
          <tr><th>Tag</th><th className="r">Trades</th><th className="r">Win Rate</th><th className="r">Net P&amp;L</th><th className="r">Avg P&amp;L</th></tr>
        </thead>
        <tbody>
          {tagStats.size === 0 && <tr><td colSpan={5} className="dim">No logged trades yet.</td></tr>}
          {[...tagStats.entries()].sort((a, b) => b[1].totalPnl - a[1].totalPnl).map(([tag, st]) => (
            <tr key={tag}>
              <td className="sym">{tag}</td>
              <td className="r">{st.count}</td>
              <td className="r">{num((st.wins / st.count) * 100, 1)}%</td>
              <td className={`r ${sign(st.totalPnl)}`}>{num(st.totalPnl)}</td>
              <td className={`r ${sign(st.totalPnl)}`}>{num(st.totalPnl / st.count)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4>Trade Log ({entries.length})</h4>
      <table className="grid">
        <thead>
          <tr><th>Time</th><th>Security</th><th>Side</th><th>Setup</th><th>Conf</th><th className="r">P&amp;L</th><th>Tags</th><th>Notes</th><th /></tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id}>
              <td>{e.ts.slice(0, 16).replace("T", " ")}</td>
              <td className="sym">{secName(e.symbol)}</td>
              <td className={e.side === "BUY" ? "up" : "down"}>{e.side}</td>
              <td>{e.setup}</td>
              <td>{"★".repeat(e.confidence)}</td>
              <td className={`r ${sign(e.pnl)}`}>{num(e.pnl)}</td>
              <td className="sym">{e.tags.join(" ")}</td>
              <td className="dim">{e.notes}</td>
              <td><button className="mini" onClick={() => setEntries(entries.filter((x) => x.id !== e.id))}>×</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface PriceAlert {
  id: string;
  symbol: string;
  condition: "ABOVE" | "BELOW";
  price: number;
  note: string;
  triggeredAt?: string;
}

export function loadAlerts(): PriceAlert[] {
  return loadJson<PriceAlert[]>(ALRT_KEY, []);
}

export function saveAlerts(alerts: PriceAlert[]): void {
  window.localStorage.setItem(ALRT_KEY, JSON.stringify(alerts));
}

export function Alrt() {
  const { snapshot } = useMarket();
  const [alerts, setAlerts] = useState<PriceAlert[]>(loadAlerts);
  const [sym, setSym] = useState(snapshot?.quotes[0]?.symbol ?? "EQ:US:AAPL");
  const [cond, setCond] = useState<"ABOVE" | "BELOW">("ABOVE");
  const [price, setPrice] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (snapshot?.quotes.length && !snapshot.quotes.some((q) => q.symbol === sym)) {
      setSym(snapshot.quotes[0].symbol);
    }
  }, [snapshot, sym]);

  useEffect(() => {
    const id = window.setInterval(() => setAlerts(loadAlerts()), 800);
    return () => window.clearInterval(id);
  }, []);

  const add = () => {
    const p = Number(price);
    if (!sym || !Number.isFinite(p) || p <= 0) return;
    const next: PriceAlert[] = [
      { id: `AL${Date.now()}`, symbol: sym, condition: cond, price: p, note: note || `${cond} ${p}` },
      ...alerts,
    ];
    setAlerts(next);
    saveAlerts(next);
    setPrice("");
    setNote("");
  };

  const remove = (id: string) => {
    const next = alerts.filter((a) => a.id !== id);
    setAlerts(next);
    saveAlerts(next);
  };

  return (
    <div className="panel-body form">
      <div className="row">
        <label>Security
          {snapshot?.quotes.length ? (
            <select aria-label="Alert Security" value={sym} onChange={(e) => setSym(e.target.value)}>
              {snapshot.quotes.map((q) => <option key={q.symbol} value={q.symbol}>{secName(q.symbol)}</option>)}
            </select>
          ) : (
            <input aria-label="Alert Security" value={sym} onChange={(e) => setSym(e.target.value)} />
          )}
        </label>
        <label>Condition
          <select aria-label="Condition" value={cond} onChange={(e) => setCond(e.target.value as "ABOVE" | "BELOW")}>
            <option value="ABOVE">CROSSES ABOVE (≥)</option>
            <option value="BELOW">CROSSES BELOW (≤)</option>
          </select>
        </label>
        <label>Trigger Price
          <input aria-label="Trigger Price" value={price} onChange={(e) => setPrice(e.target.value)} size={10} />
        </label>
        <label>Message
          <input aria-label="Alert Message" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Breakout level / Stop warning" size={20} />
        </label>
        <button className="on buy" onClick={add}>Create Alert</button>
      </div>
      <table className="grid">
        <thead>
          <tr><th>Security</th><th>Rule</th><th className="r">Level</th><th>Note</th><th>Status</th><th /></tr>
        </thead>
        <tbody>
          {alerts.length === 0 && <tr><td colSpan={6} className="dim">No active price alerts.</td></tr>}
          {alerts.map((a) => (
            <tr key={a.id}>
              <td className="sym">{secName(a.symbol)}</td>
              <td className={a.condition === "ABOVE" ? "up" : "down"}>{a.condition}</td>
              <td className="r">{px(a.price)}</td>
              <td>{a.note}</td>
              <td className={a.triggeredAt ? "up blink" : "dim"}>{a.triggeredAt ? `TRIGGERED @ ${a.triggeredAt}` : "ARMED"}</td>
              <td><button className="mini" onClick={() => remove(a.id)}>Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="dim">Armed alerts trigger terminal audio beeps and visual toast notifications when crossed in Replay or Live mode.</div>
    </div>
  );
}
