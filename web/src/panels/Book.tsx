import { useEffect, useState } from "react";
import { api, type BookData } from "../api";
import { num, px } from "../fmt";
import { useBars, useMarket } from "../store";

const LEVELS = 8;

/** Live Binance crypto: real depth and trades. Replay (candles only): simulated and labelled as such. */
export function Book({ symbol }: { symbol: string }) {
  const { snapshot } = useMarket();
  const real = snapshot?.meta.mode === "live" && symbol.startsWith("CRYPTO:BINANCE:");
  return real ? <LiveBook symbol={symbol} /> : <SimBook symbol={symbol} />;
}

function Depth({ asks, bids }: { asks: [string, string][]; bids: [string, string][] }) {
  const max = Math.max(1e-9, ...asks.map((a) => Number(a[1])), ...bids.map((b) => Number(b[1])));
  const row = (side: "ask" | "bid", [p, q]: [string, string]) => (
    <tr key={`${side}${p}`} className="ladder">
      <td className="r bar-cell">
        <span className={`bar ${side}`} style={{ width: `${(Number(q) / max) * 100}%` }} />
        <span className="bar-txt">{num(q, 5)}</span>
      </td>
      <td className={`r ${side === "ask" ? "down" : "up"}`}>{px(p)}</td>
    </tr>
  );
  return (
    <table className="grid ladder-tbl">
      <thead><tr><th className="r">Size</th><th className="r">Price</th></tr></thead>
      <tbody>
        {[...asks].reverse().map((a) => row("ask", a))}
        {bids.map((b) => row("bid", b))}
      </tbody>
    </table>
  );
}

/** Real order book and trades from Binance, polled every 2 s (no WebSocket yet). */
function LiveBook({ symbol }: { symbol: string }) {
  const [book, setBook] = useState<BookData | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let alive = true;
    const load = () =>
      api<BookData>("GET", `/api/book?symbol=${encodeURIComponent(symbol)}&limit=10`).then(
        (b) => alive && (setBook(b), setErr("")),
        (e) => alive && setErr(String(e)),
      );
    void load();
    const t = window.setInterval(load, 2000);
    return () => { alive = false; window.clearInterval(t); };
  }, [symbol]);
  if (!book) return <div className="panel-body dim">{err || "Loading Binance order book…"}</div>;
  const spread = Number(book.asks[0]?.[0]) - Number(book.bids[0]?.[0]);
  return (
    <div className="panel-body">
      <div className="live-tag">LIVE: real Binance order book and trades, refreshed every 2 s</div>
      {err && <div className="err">{err}</div>}
      <div className="two">
        <div>
          <Depth asks={book.asks} bids={book.bids} />
          <div className="dim">Spread {num(spread, 4)}</div>
        </div>
        <table className="grid">
          <thead><tr><th>Time (UTC)</th><th className="r">Price</th><th className="r">Size</th><th>Aggressor</th></tr></thead>
          <tbody>
            {book.trades.map((t, i) => (
              <tr key={`${t.ts}${i}`}>
                <td>{t.ts.slice(11, 19)}</td>
                <td className={`r ${t.side === "BUY" ? "up" : "down"}`}>{px(t.price)}</td>
                <td className="r">{num(t.qty, 5)}</td>
                <td className={t.side === "BUY" ? "up" : "down"}>{t.side === "BUY" ? "buyer" : "seller"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * Replay only has candles, no real depth. The ladder is built from the last price and the tick
 * size, and the screen says so.
 */
function SimBook({ symbol }: { symbol: string }) {
  const { snapshot } = useMarket();
  const bars = useBars(symbol);
  const cfg = snapshot?.meta.symbols?.find((c) => c.symbol === symbol);
  const q = snapshot?.quotes.find((x) => x.symbol === symbol);
  if (!snapshot || !q) return <div className="panel-body dim">No session with this security. Press F10 (REPLAY).</div>;

  const tick = Number(cfg?.tick_size ?? 0.01);
  const last = Number(q.last);
  const asks = Array.from({ length: LEVELS }, (_, i) => last + tick * (LEVELS - i));
  const bids = Array.from({ length: LEVELS }, (_, i) => last - tick * (i + 1));
  const prints = bars.slice(-12).reverse();

  return (
    <div className="panel-body">
      <div className="warn">SIMULATED: ladder derived from the last price and tick size. Replay has no real depth.</div>
      <div className="two">
        <table className="grid">
          <thead><tr><th className="r">Price</th><th>Side</th></tr></thead>
          <tbody>
            {asks.map((p) => <tr key={`a${p}`}><td className="r down">{px(p)}</td><td className="dim">ask</td></tr>)}
            <tr><td className="r last">{px(last)}</td><td className="dim">last</td></tr>
            {bids.map((p) => <tr key={`b${p}`}><td className="r up">{px(p)}</td><td className="dim">bid</td></tr>)}
          </tbody>
        </table>
        <table className="grid">
          <thead><tr><th>Bar (UTC)</th><th className="r">Close</th><th className="r">Volume</th></tr></thead>
          <tbody>
            {prints.map((b) => (
              <tr key={b.ts}><td>{b.ts.slice(5, 16).replace("T", " ")}</td><td className="r">{px(b.close)}</td><td className="r">{num(b.volume, 2)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
