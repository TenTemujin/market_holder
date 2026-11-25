import { useState } from "react";
import { api } from "../api";
import { num, px, secName, sign } from "../fmt";
import { useMarket } from "../store";

export function Port() {
  const { snapshot: s, refresh } = useMarket();
  const [caSym, setCaSym] = useState("");
  const [caKind, setCaKind] = useState<"SPLIT" | "DIVIDEND">("SPLIT");
  const [caVal, setCaVal] = useState("2");
  const [caMsg, setCaMsg] = useState("");

  if (!s) return <div className="panel-body dim">No session. Press F10 (REPLAY) to start one.</div>;
  const realized = Object.values(s.realized).reduce((a, v) => a + Number(v), 0);
  const unrealized = s.positions.reduce((a, p) => a + Number(p.unrealized), 0);
  const fees = Object.values(s.fees).reduce((a, v) => a + Number(v), 0);
  const borrowFees = Object.values(s.borrow_fees ?? {}).reduce((a, v) => a + Number(v), 0);
  const cancel = (id: string) => void api("DELETE", `/api/orders/${id}`);

  const applyCa = async () => {
    const target = caSym || s.quotes[0]?.symbol;
    if (!target) return;
    try {
      await api("POST", "/api/session/corporate_action", { symbol: target, kind: caKind, value: caVal });
      setCaMsg(`Applied ${caKind} (${caVal}) on ${secName(target)}`);
      void refresh();
    } catch (e) {
      setCaMsg(String(e));
    }
  };

  return (
    <div className="panel-body">
      <div className="kpis">
        <span>Equity <b>{num(s.equity)}</b> {s.base_currency}</span>
        <span>Gross <b>{num(s.gross_exposure)}</b></span>
        <span>Net <b>{num(s.net_exposure)}</b></span>
        <span>Initial margin <b>{num(s.margin.initial_required)}</b></span>
        <span>Maintenance <b>{num(s.margin.maintenance_required)}</b></span>
        <span className={sign(realized)}>Realized P&amp;L <b>{num(realized)}</b></span>
        <span className={sign(unrealized)}>Unrealized P&amp;L <b>{num(unrealized)}</b></span>
        <span>Fees <b>{num(fees)}</b></span>
        {borrowFees > 0 && <span className="down">Short Borrow <b>{num(borrowFees)}</b></span>}
        {s.margin.margin_call && <span className="err blink">MARGIN CALL</span>}
      </div>
      <h4>Positions</h4>
      <table className="grid">
        <thead>
          <tr><th>Security</th><th className="r">Qty</th><th className="r">Avg Px</th><th className="r">Mark</th><th className="r">Unrealized P&amp;L</th></tr>
        </thead>
        <tbody>
          {s.positions.length === 0 && <tr><td colSpan={5} className="dim">No positions.</td></tr>}
          {s.positions.map((p) => (
            <tr key={p.symbol}>
              <td className="sym">{secName(p.symbol)}</td>
              <td className="r">{num(p.qty, 4)}</td>
              <td className="r">{px(p.avg_price)}</td>
              <td className="r">{px(p.mark)}</td>
              <td className={`r ${sign(p.unrealized)}`}>{num(p.unrealized)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="dim">Cash: {Object.entries(s.cash).map(([c, v]) => `${num(v)} ${c}`).join(" · ")}</div>

      {s.algos && s.algos.length > 0 && (
        <>
          <h4>Institutional Execution Algos (TWAP / VWAP)</h4>
          <table className="grid">
            <thead>
              <tr><th>ID</th><th>Algo</th><th>Security</th><th>Side</th><th className="r">Filled / Total</th><th className="r">Slices</th><th>Status</th></tr>
            </thead>
            <tbody>
              {s.algos.map((a) => (
                <tr key={a.id}>
                  <td>{a.id}</td>
                  <td className="sym">{a.algo}</td>
                  <td className="sym">{secName(a.symbol)}</td>
                  <td className={a.side === "BUY" ? "up" : "down"}>{a.side}</td>
                  <td className="r">{num(a.executed_qty, 4)} / {num(a.total_qty, 4)}</td>
                  <td className="r">{a.filled_slices} / {a.slices}</td>
                  <td className={a.active ? "up" : "dim"}>{a.active ? "WORKING" : "COMPLETED"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h4>Order blotter</h4>
      <table className="grid">
        <thead>
          <tr><th>ID</th><th>Security</th><th>Side</th><th>Type</th><th className="r">Qty</th><th>Status</th><th className="r">Filled</th><th className="r">Avg Px</th><th>Reason / Flags</th><th /></tr>
        </thead>
        <tbody>
          {[...s.orders].reverse().map((o) => (
            <tr key={o.order.id}>
              <td>{o.order.id}</td>
              <td className="sym">{secName(o.order.symbol)}</td>
              <td className={o.order.side === "BUY" ? "up" : "down"}>{o.order.side}</td>
              <td>{o.order.type}{o.order.display_qty ? ` (ICE ${o.order.display_qty})` : ""}{o.order.oco ? ` [${o.order.oco}]` : ""}</td>
              <td className="r">{num(o.order.qty, 4)}</td>
              <td className={`st-${o.status}`}>{o.status}</td>
              <td className="r">{num(o.filled_qty, 4)}</td>
              <td className="r">{Number(o.avg_price) ? px(o.avg_price) : "–"}</td>
              <td className="dim">{o.reject_reason}</td>
              <td>{["NEW", "PARTIALLY_FILLED"].includes(o.status) && <button className="mini" onClick={() => cancel(o.order.id)}>Cancel</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h4>Fills</h4>
      <table className="grid">
        <thead><tr><th>Time (UTC)</th><th>Order</th><th>Security</th><th>Side</th><th className="r">Qty</th><th className="r">Price</th><th className="r">Fee</th></tr></thead>
        <tbody>
          {[...s.fills].reverse().slice(0, 50).map((f, i) => (
            <tr key={`${f.order_id}${f.ts}${i}`}>
              <td>{f.ts.slice(0, 19).replace("T", " ")}</td><td>{f.order_id}</td><td className="sym">{secName(f.symbol)}</td>
              <td className={f.side === "BUY" ? "up" : "down"}>{f.side}</td>
              <td className="r">{num(f.qty, 4)}</td><td className="r">{px(f.price)}</td><td className="r">{num(f.fee)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4>Corporate Actions Simulator (Splits &amp; Cash Dividends)</h4>
      <div className="form">
        <div className="row">
          <label>Security
            <select aria-label="CA Security" value={caSym || s.quotes[0]?.symbol || ""} onChange={(e) => setCaSym(e.target.value)}>
              {s.quotes.map((q) => <option key={q.symbol} value={q.symbol}>{secName(q.symbol)}</option>)}
            </select>
          </label>
          <label>Event
            <select aria-label="CA Event" value={caKind} onChange={(e) => setCaKind(e.target.value as "SPLIT" | "DIVIDEND")}>
              <option value="SPLIT">Stock Split / Reverse Split (Ratio)</option>
              <option value="DIVIDEND">Cash Dividend (Per Share)</option>
            </select>
          </label>
          <label>{caKind === "SPLIT" ? "Ratio (e.g. 2 = 2:1)" : "Dividend / Share"}
            <input aria-label="CA Value" value={caVal} onChange={(e) => setCaVal(e.target.value)} size={8} />
          </label>
          <button onClick={applyCa}>Apply Event</button>
          {caMsg && <span className="dim">{caMsg}</span>}
        </div>
      </div>
    </div>
  );
}
