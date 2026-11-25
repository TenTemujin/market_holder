import { useEffect, useState } from "react";
import { api, type OptionChainResp, type OptionLeg } from "../api";
import { num, px, secName } from "../fmt";
import { useMarket } from "../store";

export function Omon({ symbol }: { symbol?: string }) {
  const { snapshot, refresh } = useMarket();
  const [sym, setSym] = useState(symbol ?? "");
  const [expiry, setExpiry] = useState(30);
  const [rate, setRate] = useState("4.50");
  const [ivOverride, setIvOverride] = useState("");
  const [qty, setQty] = useState("1");
  const [chain, setChain] = useState<OptionChainResp | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState<{ t: string; err: boolean }>({ t: "", err: false });

  useEffect(() => {
    if (symbol) setSym(symbol);
    else if (!sym && snapshot?.quotes.length) {
      const firstNonOpt = snapshot.quotes.find((q) => !q.symbol.startsWith("OPT:")) ?? snapshot.quotes[0];
      if (firstNonOpt) setSym(firstNonOpt.symbol);
    }
  }, [symbol, snapshot, sym]);

  useEffect(() => {
    if (!sym || !snapshot) return;
    let alive = true;
    setErr("");
    const r = (Number(rate) || 4.5) / 100;
    const ivParam = ivOverride.trim() ? `&iv=${(Number(ivOverride) || 25) / 100}` : "";
    api<OptionChainResp>(
      "GET",
      `/api/options/chain?symbol=${encodeURIComponent(sym)}&expiry_days=${expiry}&rate=${r}${ivParam}`,
    ).then(
      (res) => alive && setChain(res),
      (e) => alive && setErr(String(e)),
    );
    return () => { alive = false; };
  }, [sym, expiry, rate, ivOverride, snapshot?.clock.now, snapshot?.id]);

  if (!snapshot) return <div className="panel-body dim">No session. Press F10 (REPLAY) to start one.</div>;

  const tradeOption = async (right: "CALL" | "PUT", strike: number, side: "BUY" | "SELL", leg: OptionLeg) => {
    const execPx = side === "BUY" ? leg.ask : leg.bid;
    try {
      const res = await api<{ order_id: string; symbol: string }>("POST", "/api/options/order", {
        underlying: sym,
        right,
        strike: String(strike),
        expiry_days: expiry,
        side,
        qty: String(Number(qty) || 1),
        price: String(execPx),
      });
      setMsg({
        t: `FILLED ${side} ${qty}x ${secName(res.symbol)} @ ${px(execPx)} (100x mult)`,
        err: false,
      });
      void refresh();
    } catch (e) {
      setMsg({ t: String(e), err: true });
    }
  };

  const tradeSpread = async (kind: "STRADDLE" | "BULL_CALL" | "IRON_CONDOR") => {
    if (!chain || chain.chain.length < 3) return;
    const midIdx = Math.floor(chain.chain.length / 2);
    const atm = chain.chain[midIdx];
    const otmCall = chain.chain[Math.min(chain.chain.length - 1, midIdx + 2)];
    const otmPut = chain.chain[Math.max(0, midIdx - 2)];
    try {
      if (kind === "STRADDLE") {
        await tradeOption("CALL", atm.strike, "BUY", atm.call);
        await tradeOption("PUT", atm.strike, "BUY", atm.put);
        setMsg({ t: `LONG STRADDLE executed @ Strike ${atm.strike}`, err: false });
      } else if (kind === "BULL_CALL") {
        await tradeOption("CALL", atm.strike, "BUY", atm.call);
        await tradeOption("CALL", otmCall.strike, "SELL", otmCall.call);
        setMsg({ t: `BULL CALL SPREAD +${atm.strike}C / -${otmCall.strike}C executed`, err: false });
      } else {
        await tradeOption("PUT", otmPut.strike, "SELL", otmPut.put);
        await tradeOption("CALL", otmCall.strike, "SELL", otmCall.call);
        setMsg({ t: `SHORT STRANGLE / CONDOR CORE -${otmPut.strike}P / -${otmCall.strike}C executed`, err: false });
      }
    } catch (e) {
      setMsg({ t: String(e), err: true });
    }
  };

  const underlyings = snapshot.quotes.filter((q) => !q.symbol.startsWith("OPT:"));

  return (
    <div className="panel-body form">
      <div className="row">
        <label>Underlying
          <select aria-label="Underlying" value={sym} onChange={(e) => setSym(e.target.value)}>
            {underlyings.map((q) => <option key={q.symbol} value={q.symbol}>{secName(q.symbol)}</option>)}
          </select>
        </label>
        <label>Expiry (DTE)
          <select aria-label="Expiry" value={expiry} onChange={(e) => setExpiry(Number(e.target.value))}>
            {[7, 14, 30, 60, 90, 180].map((d) => <option key={d} value={d}>{d} Days</option>)}
          </select>
        </label>
        <label>Risk-Free %<input aria-label="Risk-Free" value={rate} onChange={(e) => setRate(e.target.value)} size={5} /></label>
        <label>Base IV % (blank=auto)<input aria-label="Base IV" value={ivOverride} placeholder={chain ? num(chain.base_iv * 100, 1) : "auto"} onChange={(e) => setIvOverride(e.target.value)} size={6} /></label>
        <label>Contracts (x100)<input aria-label="Contracts" value={qty} onChange={(e) => setQty(e.target.value)} size={4} /></label>
        {chain && (
          <span className="kv">
            Spot <b>{px(chain.spot)}</b> · Realized/Base IV <b>{num(chain.base_iv * 100, 1)}%</b>
          </span>
        )}
      </div>
      <div className="row">
        <span className="dim">1-Click Strategies:</span>
        <button onClick={() => tradeSpread("STRADDLE")}>Buy ATM Straddle</button>
        <button onClick={() => tradeSpread("BULL_CALL")}>Buy Bull Call Spread</button>
        <button onClick={() => tradeSpread("IRON_CONDOR")}>Sell OTM Strangle</button>
      </div>
      {msg.t && <div className={msg.err ? "err" : "ok"} role="status">{msg.t}</div>}
      {err && <div className="err">{err}</div>}
      {!chain && !err && <div className="dim">Calculating Black-Scholes option chain…</div>}
      {chain && (
        <table className="grid omon-tbl">
          <thead>
            <tr>
              <th>Trade Call</th>
              <th className="r">Bid</th>
              <th className="r">Ask</th>
              <th className="r">Delta</th>
              <th className="r">Gamma</th>
              <th className="r">Theta/d</th>
              <th className="r">Vega</th>
              <th className="c strike-hdr">STRIKE</th>
              <th className="r">IV %</th>
              <th className="r">Delta</th>
              <th className="r">Theta/d</th>
              <th className="r">Bid</th>
              <th className="r">Ask</th>
              <th>Trade Put</th>
            </tr>
          </thead>
          <tbody>
            {chain.chain.map((r) => (
              <tr key={r.strike} className={Math.abs(r.strike - chain.spot) / chain.spot < 0.015 ? "atm-row" : ""}>
                <td>
                  <button className="mini up" onClick={() => tradeOption("CALL", r.strike, "BUY", r.call)} title="Buy Call at Ask">B</button>{" "}
                  <button className="mini down" onClick={() => tradeOption("CALL", r.strike, "SELL", r.call)} title="Write Call at Bid">S</button>
                </td>
                <td className={`r ${r.call.itm ? "itm" : ""}`}>{num(r.call.bid, 2)}</td>
                <td className={`r ${r.call.itm ? "itm" : ""}`}>{num(r.call.ask, 2)}</td>
                <td className="r up">{num(r.call.delta, 2)}</td>
                <td className="r dim">{num(r.call.gamma, 4)}</td>
                <td className="r down">{num(r.call.theta, 3)}</td>
                <td className="r">{num(r.call.vega, 3)}</td>
                <td className="c sym strike-cell">{px(r.strike)}</td>
                <td className="r dim">{num(r.iv * 100, 1)}%</td>
                <td className="r down">{num(r.put.delta, 2)}</td>
                <td className="r down">{num(r.put.theta, 3)}</td>
                <td className={`r ${r.put.itm ? "itm" : ""}`}>{num(r.put.bid, 2)}</td>
                <td className={`r ${r.put.itm ? "itm" : ""}`}>{num(r.put.ask, 2)}</td>
                <td>
                  <button className="mini up" onClick={() => tradeOption("PUT", r.strike, "BUY", r.put)} title="Buy Put at Ask">B</button>{" "}
                  <button className="mini down" onClick={() => tradeOption("PUT", r.strike, "SELL", r.put)} title="Write Put at Bid">S</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="dim">
        SIMULATED OPTION CHAIN: European Black-Scholes pricing with volatility smile skew, synchronized with session spot and realized volatility. Multiplier = 100.
      </div>
    </div>
  );
}
