import { useEffect, useState } from "react";
import { api } from "../api";
import { num, px, secName } from "../fmt";
import { useMarket, useTick } from "../store";

type Result = { order: { id: string }; status: string; reject_reason: string };

export function Ord({ symbol }: { symbol?: string }) {
  const { snapshot: s } = useMarket();
  const [sym, setSym] = useState(symbol ?? "");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [type, setType] = useState("MARKET");
  const [qty, setQty] = useState("");
  const [limit, setLimit] = useState("");
  const [stop, setStop] = useState("");
  const [tif, setTif] = useState("DAY");
  const [msg, setMsg] = useState<{ t: string; err: boolean }>({ t: "", err: false });
  const tick = useTick(sym || undefined);

  useEffect(() => {
    if (!sym && s?.quotes.length) setSym(s.quotes[0].symbol);
  }, [s, sym]);
  // with daily or weekly bars a DAY order expires before the next bar: default to GTC
  const freq = s?.meta.freq;
  useEffect(() => {
    setTif(freq === "1d" || freq === "1w" ? "GTC" : "DAY");
  }, [freq, s?.id]);
  if (!s) return <div className="panel-body dim">No session. Press F10 (REPLAY) to start one.</div>;

  const quote = s.quotes.find((q) => q.symbol === sym);
  const pos = s.positions.find((p) => p.symbol === sym);
  const cfg = s.meta.symbols?.find((c) => c.symbol === sym);
  const lot = Number(cfg?.lot_size ?? 1) || 1;
  const last = tick?.price ?? Number(quote?.last);
  const bid = tick?.bid ?? last;
  const ask = tick?.ask ?? last;
  const live = s.meta.mode === "live";

  const pct = (p: number) => {
    // BUY: % of equity at the current price; SELL: % of the position
    const raw = side === "BUY" ? (Number(s.equity) * p) / (last || 1) : Math.abs(Number(pos?.qty ?? 0)) * p;
    setQty(String(Math.floor(raw / lot) * lot));
  };
  const needLimit = type === "LIMIT" || type === "STOP_LIMIT";
  const needStop = type === "STOP" || type === "STOP_LIMIT";

  const submit = async (body: Record<string, unknown>) => {
    try {
      const r = await api<Result>("POST", "/api/orders", body);
      const bad = r.status === "REJECTED";
      setMsg({ t: bad ? `Rejected: ${r.reject_reason}` : `Order ${r.order.id} ${r.status}`, err: bad });
    } catch (e) {
      setMsg({ t: String(e), err: true });
    }
  };
  const send = () =>
    submit({
      symbol: sym, side, type, qty, tif,
      limit_price: needLimit ? limit : undefined,
      stop_price: needStop ? stop : undefined,
    });
  const oneClick = (sd: "BUY" | "SELL") => submit({ symbol: sym, side: sd, type: "MARKET", qty, tif });

  return (
    <div className="panel-body form ticket">
      <div className="row">
        <label>Security
          <select aria-label="Security" value={sym} onChange={(e) => setSym(e.target.value)}>
            {s.quotes.map((q) => <option key={q.symbol} value={q.symbol}>{secName(q.symbol)}</option>)}
          </select>
        </label>
        <span className="kv">Position <b>{num(pos?.qty ?? 0, 4)}</b></span>
        <span className="kv">Avg <b>{pos ? px(pos.avg_price) : "–"}</b></span>
        <span className="kv">Unrealized <b className={Number(pos?.unrealized ?? 0) >= 0 ? "up" : "down"}>{num(pos?.unrealized ?? 0)}</b></span>
        <span className="kv">Cash <b>{num(s.cash[quote?.currency ?? s.base_currency] ?? 0)}</b></span>
      </div>

      <div className="quote-box">
        <button className="mkt sell" disabled={!sym || !qty} onClick={() => oneClick("SELL")} title="Sell at market, one click">
          <small>MKT SELL</small>
          <span key={`b${tick?.n}`} className="flash">{px(bid)}</span>
        </button>
        <div className="mid">
          <small>{live ? "LIVE" : "REPLAY"} · last</small>
          <span key={`m${tick?.n}`} className={`flash big ${tick?.dir === 1 ? "up" : tick?.dir === -1 ? "down" : ""}`}>{px(last)}</span>
          <small>spread {num(ask - bid, 4)}</small>
        </div>
        <button className="mkt buy" disabled={!sym || !qty} onClick={() => oneClick("BUY")} title="Buy at market, one click">
          <small>MKT BUY</small>
          <span key={`a${tick?.n}`} className="flash">{px(ask)}</span>
        </button>
      </div>

      <div className="row">
        <button aria-pressed={side === "BUY"} className={side === "BUY" ? "on buy" : ""} onClick={() => setSide("BUY")}>BUY</button>
        <button aria-pressed={side === "SELL"} className={side === "SELL" ? "on sell" : ""} onClick={() => setSide("SELL")}>SELL</button>
        <label>Type
          <select aria-label="Type" value={type} onChange={(e) => setType(e.target.value)}>
            {["MARKET", "LIMIT", "STOP", "STOP_LIMIT"].map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label>TIF
          <select aria-label="TIF" value={tif} onChange={(e) => setTif(e.target.value)}>
            {["DAY", "GTC", "IOC", "FOK"].map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
      </div>
      <div className="row">
        <label>Quantity<input aria-label="Quantity" value={qty} onChange={(e) => setQty(e.target.value)} size={10} /></label>
        {[0.1, 0.25, 0.5, 1].map((p) => <button key={p} onClick={() => pct(p)}>{p * 100}%</button>)}
        {needLimit && <label>Limit<input aria-label="Limit price" value={limit} onChange={(e) => setLimit(e.target.value)} size={10} /></label>}
        {needStop && <label>Stop<input aria-label="Stop price" value={stop} onChange={(e) => setStop(e.target.value)} size={10} /></label>}
      </div>
      <div className="row">
        <button className="send" onClick={send} disabled={!sym || !qty}>SEND {side}</button>
      </div>
      {msg.t && <div className={msg.err ? "err" : "ok"} role="status">{msg.t}</div>}
      <div className="dim">
        BUY: % of equity at the current price. SELL: % of the position.{" "}
        {live ? "Live: market orders fill on the next real-time quote (~1 s)." : "Replay: the order enters from the next bar (no lookahead)."}
      </div>
    </div>
  );
}
