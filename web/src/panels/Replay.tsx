import { useEffect, useState } from "react";
import { api, type Quote } from "../api";
import { isBlindMode, secName, setBlindMode, utc } from "../fmt";
import { useMarket } from "../store";
import { UNIVERSE } from "../universe";

const today = () => new Date().toISOString().slice(0, 10);
const ago = (d: number) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);

/** Aberto/fechado por mercado. No replay vale o relógio simulado; ao vivo, o relógio real. */
function MarketHours({ quotes, live }: { quotes: Quote[]; live: boolean }) {
  const groups = new Map<string, Quote["market"]>();
  for (const q of quotes) {
    if (q.market) groups.set(q.symbol.split(":").slice(0, 2).join(":"), q.market);
  }
  if (groups.size === 0) return null;
  const closed = [...groups.values()].filter((m) => m && !m.open).length;
  return (
    <div className="block">
      <div className="dim">Market hours ({live ? "real clock" : "simulated clock"}) · regular session only, no holidays</div>
      {live && closed === groups.size && (
        <div className="warn">All markets are closed: no new bars until the next open, so the session will sit idle.</div>
      )}
      {[...groups].map(([k, m]) => (
        <div key={k} title={m!.hours}>
          <b>{k}</b> <span className={m!.open ? "buy" : "sell"}>{m!.open ? "OPEN" : "CLOSED"}</span>
          {m!.next_change && <> · {m!.open ? "closes" : "opens"} {utc(m!.next_change)} UTC</>}
        </div>
      ))}
    </div>
  );
}

export function Replay() {
  const { snapshot, refresh } = useMarket();
  const [mode, setMode] = useState<"replay" | "live">("replay");
  const [symbols, setSymbols] = useState("INDEX:US:GSPC:USD INDEX:US:IXIC:USD CRYPTO:BINANCE:BTCUSDT:USDT");
  const [freq, setFreq] = useState("1h");
  const [start, setStart] = useState(ago(7));
  const [end, setEnd] = useState(today());
  const [cash, setCash] = useState("100000");
  const [base, setBase] = useState("USD");
  const [borrowRate, setBorrowRate] = useState("0.03");
  const [autoLiq, setAutoLiq] = useState(true);
  const [blind, setBlind] = useState(isBlindMode);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ symbol: string; currency: string; name: string }[]>([]);
  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return; }
    let alive = true;
    const t = window.setTimeout(() => {
      api<{ results: typeof hits }>("GET", `/api/search?q=${encodeURIComponent(q.trim())}`).then(
        (r) => alive && setHits(r.results), () => alive && setHits([]),
      );
    }, 350);
    return () => { alive = false; window.clearTimeout(t); };
  }, [q]);
  const picked = symbols.split(/[\s,]+/).filter(Boolean);
  const toggle = (s: string) => setSymbols((picked.includes(s) ? picked.filter((x) => x !== s) : [...picked, s]).join(" "));
  const [speed, setSpeed] = useState("1000");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const toggleBlind = (next: boolean) => {
    setBlindMode(next);
    setBlind(next);
    void refresh();
  };

  const create = async (overrideSymbols?: string, overrideStart?: string, overrideEnd?: string) => {
    setErr("");
    setBusy(true);
    try {
      const symText = overrideSymbols ?? symbols;
      // format: CLASS:MARKET:TICKER:CURRENCY separated by space or comma (currency = last field)
      const cfgs = symText
        .split(/[\s,]+/)
        .filter(Boolean)
        .map((t) => {
          const i = t.lastIndexOf(":");
          const symbol = t.slice(0, i);
          // crypto is fractional; stocks trade in lots of 1
          return symbol.startsWith("CRYPTO:")
            ? { symbol, currency: t.slice(i + 1), lot_size: "0.00001", borrow_rate_annual: borrowRate }
            : { symbol, currency: t.slice(i + 1), borrow_rate_annual: borrowRate };
        });
      // stablecoin and USD are treated as 1:1 (simulation); other currencies need a real rate
      const fx: Record<string, string> = {};
      for (const c of cfgs) if (c.currency !== base && ["USD", "USDT"].includes(c.currency) && ["USD", "USDT"].includes(base)) fx[c.currency] = "1";
      await api("POST", "/api/session", {
        mode, symbols: cfgs, freq, base_currency: base, cash, fx,
        ...(mode === "replay" ? { start: overrideStart ?? start, end: overrideEnd ?? end } : {}),
        fees: { bps: "5" }, model: { half_spread_bps: "1" },
        margin: { initial_rate: "0.5", maintenance_rate: "0.25", allow_short: true, auto_liquidate: autoLiq },
      });
      await refresh();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const startBlindTraining = async () => {
    const allPool = Object.values(UNIVERSE).flat().map(([, s]) => s);
    const chosen = allPool[Math.floor(Math.random() * allPool.length)] ?? "EQ:US:AAPL:USD";
    const offsetDays = 30 + Math.floor(Math.random() * 180);
    const sDate = ago(offsetDays + 14);
    const eDate = ago(offsetDays);
    toggleBlind(true);
    setSymbols(chosen);
    setStart(sDate);
    setEnd(eDate);
    await create(chosen, sDate, eDate);
  };

  const clock = (body: object) => api("POST", "/api/clock", body).then(refresh, (e) => setErr(String(e)));

  return (
    <div className="panel-body form">
      {snapshot?.meta.mode === "live" ? (
        <div className="block">
          <div>
            <span className="live-tag">LIVE</span> Session #{snapshot.id} · {snapshot.meta.freq} bars · since {utc(snapshot.meta.start)} UTC
            {snapshot.meta.ticks?.length ? " · real-time quotes (1 s)" : " · closed bars only"}
          </div>
          <div>
            Last bar processed: <b>{utc(snapshot.clock.now)}</b> UTC. Time is the real clock; there is no step or speed control.
          </div>
          {snapshot.live?.last_error && <div className="err">Feed: {snapshot.live.last_error}</div>}
        </div>
      ) : snapshot ? (
        <div className="block">
          <div>
            Session #{snapshot.id} · {snapshot.meta.freq} · {utc(snapshot.meta.start)} → {utc(snapshot.meta.end)}
            {blind && <span className="warn" style={{ marginLeft: 8 }}>BLIND REPLAY MODE (IDENTITY MASKED)</span>}
          </div>
          <div>
            Simulated time: <b>{utc(snapshot.clock.now)}</b> UTC · {snapshot.clock.remaining} events left
            {snapshot.clock.done ? " · END" : ""}
          </div>
          <div className="row">
            <button onClick={() => clock({ action: "step" })}>Step</button>
            <button onClick={() => clock({ action: "play" })}>Play</button>
            <button onClick={() => clock({ action: "pause" })}>Pause</button>
            <input aria-label="Speed" value={speed} onChange={(e) => setSpeed(e.target.value)} size={6} />
            <button onClick={() => clock({ action: "speed", speed: Number(speed) })}>Set speed</button>
            <button onClick={() => clock({ action: "fast_forward", steps: 10000 })} title="Run up to 10,000 bars headless at max CPU speed">
              Fast-Forward 10,000x (Headless)
            </button>
            <button className={blind ? "on sell" : ""} onClick={() => toggleBlind(!blind)}>
              {blind ? "Reveal Real Tickers & Dates" : "Mask Identity (Blind Mode)"}
            </button>
          </div>
        </div>
      ) : (
        <div className="dim">No session. Create one below (real data, simulated execution).</div>
      )}
      {snapshot && !blind && <MarketHours quotes={snapshot.quotes} live={snapshot.meta.mode === "live"} />}
      <div className="block">
        <div className="row">
          <button aria-pressed={mode === "replay"} className={mode === "replay" ? "on buy" : ""} onClick={() => setMode("replay")}>REPLAY</button>
          <button aria-pressed={mode === "live"} className={mode === "live" ? "on buy" : ""} onClick={() => setMode("live")}>LIVE</button>
          {mode === "replay" && (
            <button disabled={busy} onClick={startBlindTraining} title="Pick a random security and historical date window with masked identity">
              🎲 Start Random Blind Replay
            </button>
          )}
        </div>
        {Object.entries(UNIVERSE).map(([group, items]) => {
          const all = items.map(([, s]) => s);
          const full = all.every((s) => picked.includes(s));
          return (
            <div key={group} className="row presets">
              <button className={full ? "on sell" : ""} onClick={() => setSymbols((full ? picked.filter((x) => !all.includes(x)) : [...new Set([...picked, ...all])]).join(" "))}>
                {group} ({items.length}) {full ? "−" : "+"}
              </button>
              {items.map(([label, s]) => (
                <button key={s} aria-pressed={picked.includes(s)} className={picked.includes(s) ? "on buy" : ""} onClick={() => toggle(s)}>{label}</button>
              ))}
            </div>
          );
        })}
        <label>Search any security (name or ticker: stocks worldwide, indices, FX, futures, crypto)
          <input aria-label="Search" value={q} placeholder="e.g. nasdaq, petrobras, toyota, gold, ETHUSDT" onChange={(e) => setQ(e.target.value)} />
        </label>
        {hits.length > 0 && (
          <div className="hits">
            {hits.map((h) => {
              const s = `${h.symbol}:${h.currency}`;
              return (
                <button key={s} className={picked.includes(s) ? "on buy" : ""} onClick={() => toggle(s)}>
                  <b>{secName(h.symbol)}</b> {h.name} <span className="dim">{h.currency}</span>
                </button>
              );
            })}
          </div>
        )}
        <label>Securities (CLASS:MARKET:TICKER:CURRENCY)
          <input aria-label="Securities" value={symbols} onChange={(e) => setSymbols(e.target.value)} />
        </label>
        <div className="row">
          <label>Freq
            <select aria-label="Freq" value={freq} onChange={(e) => setFreq(e.target.value)}>
              {["1m", "5m", "1h", "1d", "1w"].map((f) => <option key={f}>{f}</option>)}
            </select>
          </label>
          {mode === "replay" && (
            <>
              <label>Start<input aria-label="Start" value={start} onChange={(e) => setStart(e.target.value)} size={10} /></label>
              <label>End<input aria-label="End" value={end} onChange={(e) => setEnd(e.target.value)} size={10} /></label>
            </>
          )}
          <label title="Annual short borrow rate (e.g. 0.03 = 3% p.a.)">Short Borrow Rate
            <input aria-label="Borrow Rate" value={borrowRate} onChange={(e) => setBorrowRate(e.target.value)} size={6} />
          </label>
          <button aria-pressed={autoLiq} className={autoLiq ? "on buy" : ""} onClick={() => setAutoLiq(!autoLiq)}>
            Auto-Liquidate Margin Call: {autoLiq ? "ON" : "OFF"}
          </button>
        </div>
        <div className="row">
          <label>Cash<input aria-label="Cash" value={cash} onChange={(e) => setCash(e.target.value)} size={10} /></label>
          <label>Base currency<input aria-label="Base currency" value={base} onChange={(e) => setBase(e.target.value)} size={6} /></label>
          <button disabled={busy} onClick={() => create()}>{busy ? "Loading…" : mode === "live" ? "Start live" : "Create session"}</button>
        </div>
        {err && <div className="err">{err}</div>}
      </div>
    </div>
  );
}
