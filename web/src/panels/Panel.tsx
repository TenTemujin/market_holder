import { FUNCTIONS, HELP_TEXT, type FnCode } from "../commands/parse";
import { num, px, secName, sign, utc } from "../fmt";
import { useBars, useMarket, useTick } from "../store";
import { Book } from "./Book";
import { Gp } from "./Gp";
import { Curve, Eco } from "./Macro";
import { Mon } from "./Mon";
import { Ord } from "./Ord";
import { Port } from "./Port";
import { Replay } from "./Replay";
import { fmtChg } from "./util";

function Hp({ symbol }: { symbol: string }) {
  const bars = useBars(symbol).slice(-200).reverse();
  return (
    <div className="panel-body">
      <table className="grid">
        <thead><tr><th>Date (UTC)</th><th className="r">Open</th><th className="r">High</th><th className="r">Low</th><th className="r">Close</th><th className="r">Volume</th></tr></thead>
        <tbody>
          {bars.map((b) => (
            <tr key={b.ts}>
              <td>{utc(b.ts)}</td><td className="r">{px(b.open)}</td><td className="r">{px(b.high)}</td><td className="r">{px(b.low)}</td>
              <td className="r">{px(b.close)}</td><td className="r">{num(b.volume, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {bars.length === 0 && <div className="dim">No bars yet.</div>}
    </div>
  );
}

function Des({ symbol }: { symbol: string }) {
  const { snapshot } = useMarket();
  const c = snapshot?.meta.symbols?.find((x) => x.symbol === symbol);
  if (!c) return <div className="panel-body dim">Security is not in the current session.</div>;
  const f = snapshot?.meta.feed?.[symbol];
  return (
    <div className="panel-body">
      <table className="grid">
        <tbody>
          <tr><td className="dim">Security</td><td className="sym">{secName(c.symbol)}</td></tr>
          <tr><td className="dim">Internal id</td><td>{c.symbol}</td></tr>
          <tr><td className="dim">Currency</td><td>{c.currency}</td></tr>
          <tr><td className="dim">Tick size</td><td>{c.tick_size}</td></tr>
          <tr><td className="dim">Lot size</td><td>{c.lot_size}</td></tr>
          <tr><td className="dim">Multiplier</td><td>{c.multiplier}</td></tr>
          <tr><td className="dim">Data source</td><td>{f ? `${f.provider}${f.official ? " (official)" : " (unofficial)"}` : "–"}</td></tr>
          <tr><td className="dim">Source delay</td><td>{f ? `${f.delay_s}s` : "–"}</td></tr>
        </tbody>
      </table>
    </div>
  );
}

function Help() {
  return (
    <div className="panel-body">
      <h4>Functions</h4>
      <table className="grid">
        <thead><tr><th>Code</th><th>Description</th><th>Needs security</th></tr></thead>
        <tbody>
          {(Object.keys(FUNCTIONS) as FnCode[]).map((k) => (
            <tr key={k}><td className="sym">{k}</td><td>{FUNCTIONS[k].title}</td><td>{FUNCTIONS[k].needsSymbol ? "yes" : "no"}</td></tr>
          ))}
        </tbody>
      </table>
      <h4>Command line</h4>
      <div>
        Type <b>/</b> or <b>`</b> to focus it. Examples: <b>AAPL US Equity GP</b> · <b>PETR4 BZ Equity GP</b> · <b>BTCUSDT Crypto BOOK</b> ·{" "}
        <b>USDBRL Curncy GP</b> · <b>MON</b> · <b>PORT</b>. Aliases: GC (yield curve), FXC (currencies), EMSX (order entry).
      </div>
      <h4>Layouts</h4>
      <div>SAVE &lt;name&gt; · LOAD &lt;name&gt; · LAYOUTS · RESET · CLOSE</div>
      <h4>Keys</h4>
      <div className="dim">{HELP_TEXT.split("| Keys: ")[1]}</div>
    </div>
  );
}

function Body({ fn, symbol }: { fn: FnCode; symbol?: string }) {
  switch (fn) {
    case "REPLAY": return <Replay />;
    case "MON": return <Mon />;
    case "PORT": return <Port />;
    case "ORD": return <Ord symbol={symbol} />;
    case "CURVE": return <Curve />;
    case "ECO": return <Eco />;
    case "FX": return <Eco initial="FX:BCB:USDBRL" />;
    case "HELP": return <Help />;
    case "GP": return symbol ? <Gp symbol={symbol} /> : null;
    case "HP": return symbol ? <Hp symbol={symbol} /> : null;
    case "DES": return symbol ? <Des symbol={symbol} /> : null;
    case "BOOK": return symbol ? <Book symbol={symbol} /> : null;
  }
}

/** Quote strip at the top of every security panel: last, change, bid/ask, volume, source and delay. */
function Banner({ symbol }: { symbol: string }) {
  const { snapshot } = useMarket();
  const tick = useTick(symbol);
  const q = snapshot?.quotes.find((x) => x.symbol === symbol);
  if (!q || !snapshot) return null;
  const last = tick?.price ?? Number(q.last);
  const { chg, pct } = fmtChg(String(last), q.prev_close);
  const live = snapshot.meta.mode === "live";
  const f = snapshot.meta.feed?.[symbol];
  return (
    <div className="banner">
      <span key={tick?.n} className={`last flash ${tick?.dir === 1 ? "up" : tick?.dir === -1 ? "down" : ""}`}>{px(last)}</span>
      <span className={sign(chg)}>{chg >= 0 ? "+" : ""}{num(chg, 4)} ({chg >= 0 ? "+" : ""}{num(pct, 2)}%)</span>
      {tick && <><span className="dim">Bid</span> <span className="up">{px(tick.bid)}</span> <span className="dim">Ask</span> <span className="down">{px(tick.ask)}</span></>}
      <span className="dim">Vol</span> <span>{num(q.volume, 2)}</span>
      <span className="dim">{q.currency}</span>
      <span className="dim">{utc(q.ts)} UTC</span>
      <span className={live ? "tag-live" : "tag-sim"}>
        {live ? `LIVE · ${f?.provider ?? "?"} · ${tick ? "real-time" : `delay ${f?.delay_s ?? 0}s + bar`}` : "REPLAY · simulated"}
      </span>
    </div>
  );
}

export function Panel({ fn, symbol }: { fn: FnCode; symbol?: string }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <span className="fn">{fn}</span>
        {symbol && <span className="sym">{secName(symbol)}</span>}
        <span className="title">{FUNCTIONS[fn].title}</span>
      </div>
      {symbol && <Banner symbol={symbol} />}
      <div className="panel-scroll"><Body fn={fn} symbol={symbol} /></div>
    </div>
  );
}
