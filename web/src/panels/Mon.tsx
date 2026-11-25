import { num, px, secName, sign, utc } from "../fmt";
import { useMarket, usePanels, useTick } from "../store";
import { fmtChg } from "./util";

function Row({ symbol }: { symbol: string }) {
  const { snapshot } = useMarket();
  const { open } = usePanels();
  const tick = useTick(symbol);
  const q = snapshot?.quotes.find((x) => x.symbol === symbol);
  if (!q || !snapshot) return null;
  const live = snapshot.meta.mode === "live";
  const f = snapshot.meta.feed?.[symbol];
  const last = tick?.price ?? Number(q.last);
  const { chg, pct } = fmtChg(String(last), q.prev_close);
  return (
    <tr className="click" tabIndex={0} onDoubleClick={() => open("GP", symbol)} onKeyDown={(e) => e.key === "Enter" && open("GP", symbol)}>
      <td className="sym">{secName(symbol)}</td>
      <td key={`l${tick?.n}`} className={`flash r ${tick?.dir === 1 ? "up" : tick?.dir === -1 ? "down" : ""}`}>{px(last)}</td>
      <td className={`r ${sign(chg)}`}>{chg >= 0 ? "+" : ""}{num(chg, 4)}</td>
      <td className={`r ${sign(chg)}`}>{chg >= 0 ? "+" : ""}{num(pct, 2)}%</td>
      <td className="r">{tick ? px(tick.bid) : "–"}</td>
      <td className="r">{tick ? px(tick.ask) : "–"}</td>
      <td className="r">{num(q.volume, 2)}</td>
      <td>{q.currency}</td>
      <td>{live ? f?.provider ?? "?" : "replay"}</td>
      <td className={live ? "ok" : "dim"}>{live ? (tick ? "real-time" : `${f?.delay_s ?? 0}s + ${snapshot.meta.freq} bar`) : "simulated"}</td>
      <td>{utc(q.ts)}</td>
    </tr>
  );
}

export function Mon() {
  const { snapshot } = useMarket();
  if (!snapshot) return <div className="panel-body dim">No session. Press F10 (REPLAY) to start one.</div>;
  const live = snapshot.meta.mode === "live";
  return (
    <div className="panel-body">
      {live && <div className="live-tag">LIVE · real data with the delay shown per row</div>}
      <table className="grid">
        <thead>
          <tr>
            <th>Security</th><th className="r">Last</th><th className="r">Net Chg</th><th className="r">%Chg</th>
            <th className="r">Bid</th><th className="r">Ask</th><th className="r">Volume</th><th>Ccy</th><th>Source</th><th>Delay</th><th>Time (UTC)</th>
          </tr>
        </thead>
        <tbody>{snapshot.quotes.map((q) => <Row key={q.symbol} symbol={q.symbol} />)}</tbody>
      </table>
      <div className="dim">Double-click or Enter opens the chart. {live ? "" : "Replay quotes are historical and simulated."}</div>
    </div>
  );
}
