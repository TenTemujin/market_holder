import { Layout, Model, type TabNode } from "flexlayout-react";
import { useCallback, useEffect, useReducer, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { FUNCTIONS, parseCommand, type FnCode } from "./commands/parse";
import { num, px, secName } from "./fmt";
import {
  activeTab, allTabs, closeActive, cycleTab, DEFAULT_LAYOUT, focusTab, openPanel,
} from "./layout/model";
import { CURRENT, LayoutStore } from "./layout/store";
import { Panel } from "./panels/Panel";
import { PanelsCtx, useMarket } from "./store";

const store = new LayoutStore(window.localStorage);

function initialModel(): Model {
  try {
    return Model.fromJson(store.load(CURRENT) ?? DEFAULT_LAYOUT);
  } catch {
    return Model.fromJson(DEFAULT_LAYOUT); // saved layout is incompatible: fall back to default
  }
}

type Msg = { text: string; error: boolean };

// Function keys: F1 help; F2..F10 open panels (security panels use the active tab's security or the first in the session)
const FKEYS: { key: string; label: string; fn: FnCode }[] = [
  { key: "F1", label: "HELP", fn: "HELP" }, { key: "F2", label: "MON", fn: "MON" }, { key: "F3", label: "GP", fn: "GP" },
  { key: "F4", label: "BOOK", fn: "BOOK" }, { key: "F5", label: "ORD", fn: "ORD" }, { key: "F6", label: "PORT", fn: "PORT" },
  { key: "F7", label: "CURVE", fn: "CURVE" }, { key: "F8", label: "ECO", fn: "ECO" }, { key: "F9", label: "FX", fn: "FX" },
  { key: "F10", label: "REPLAY", fn: "REPLAY" },
];

const ZONES: [string, string][] = [
  ["NY", "America/New_York"], ["LON", "Europe/London"], ["TKY", "Asia/Tokyo"], ["SAO", "America/Sao_Paulo"],
];

function Clocks({ now }: { now: Date }) {
  return (
    <span className="clocks">
      {ZONES.map(([n, tz]) => (
        <span key={n}><span className="dim">{n}</span> {now.toLocaleTimeString("en-GB", { timeZone: tz, hour12: false })}</span>
      ))}
    </span>
  );
}

/** Scrolling quote tape of the current session's securities. */
function Tape() {
  const { snapshot } = useMarket();
  if (!snapshot || snapshot.quotes.length === 0) return <div className="tape dim">&nbsp;MARKET HOLDER · no active session · press F10 to start one</div>;
  const items = snapshot.quotes.map((q) => {
    const last = Number(q.last);
    const chg = last - Number(q.prev_close);
    const pct = Number(q.prev_close) ? (chg / Number(q.prev_close)) * 100 : 0;
    return (
      <span key={q.symbol} className="tape-item">
        <b className="sym">{secName(q.symbol)}</b> {px(last)} <span className={chg >= 0 ? "up" : "down"}>{chg >= 0 ? "▲" : "▼"} {num(Math.abs(pct), 2)}%</span>
      </span>
    );
  });
  return <div className="tape"><div className="tape-inner">{items}{items}{items}</div></div>;
}

type Toast = { id: number; text: string; kind: "buy" | "sell" | "err" };
let audio: AudioContext | undefined;
function beep(freq: number) {
  try {
    audio ??= new AudioContext();
    const o = audio.createOscillator();
    const g = audio.createGain();
    o.frequency.value = freq;
    g.gain.value = 0.04;
    o.connect(g).connect(audio.destination);
    o.start();
    o.stop(audio.currentTime + 0.12);
  } catch {
    /* audio not available */
  }
}

export default function App() {
  const { snapshot, subscribe } = useMarket();
  const [toasts, setToasts] = useState<Toast[]>([]);
  useEffect(
    () =>
      subscribe((e) => {
        let t: Toast | undefined;
        if (e.type === "fill") {
          const f = (e as unknown as { fill: { side: string; qty: string; price: string; symbol: string } }).fill;
          t = { id: Date.now() + Math.random(), kind: f.side === "BUY" ? "buy" : "sell", text: `FILLED ${f.side} ${num(f.qty, 5)} ${secName(f.symbol)} @ ${px(f.price)}` };
          beep(f.side === "BUY" ? 880 : 520);
        } else if (e.type === "order") {
          const o = e as unknown as { status: string; reject_reason: string; order: { id: string } };
          if (o.status === "REJECTED") {
            t = { id: Date.now() + Math.random(), kind: "err", text: `REJECTED ${o.order.id}: ${o.reject_reason}` };
            beep(200);
          }
        }
        if (t) {
          const toast = t;
          setToasts((cur) => [...cur.slice(-3), toast]);
          window.setTimeout(() => setToasts((cur) => cur.filter((x) => x.id !== toast.id)), 6000);
        }
      }),
    [subscribe],
  );
  const snapRef = useRef(snapshot);
  snapRef.current = snapshot;
  const [model, setModel] = useState<Model>(initialModel);
  const [input, setInput] = useState("");
  const [msg, setMsg] = useState<Msg>({ text: "Type HELP or press F1 for the command list", error: false });
  const [api, setApi] = useState<"ok" | "off" | "?">("?");
  const [now, setNow] = useState(() => new Date());
  const [, redraw] = useReducer((n: number) => n + 1, 0); // the layout model mutates outside React
  const barRef = useRef<HTMLInputElement>(null);
  const modelRef = useRef(model);
  modelRef.current = model;
  const history = useRef<string[]>([]);
  const hIdx = useRef(-1);

  const say = (text: string, error = false) => setMsg({ text, error });
  const persist = (m: Model) => {
    store.save(CURRENT, m.toJson());
    redraw();
  };
  const replaceModel = (m: Model) => {
    setModel(m);
    persist(m);
  };

  const openFromPanel = (fn: FnCode, symbol?: string) => {
    const next = openPanel(modelRef.current, fn, symbol);
    if (next !== modelRef.current) setModel(next);
    persist(next);
  };

  const execute = (text: string) => {
    const p = parseCommand(text);
    if (p.kind === "error") return say(p.message, true);
    if (p.kind === "panel") {
      const next = openPanel(model, p.fn, p.symbol);
      if (next !== model) setModel(next);
      persist(next);
      return say(`${p.fn} ${p.symbol ? secName(p.symbol) : ""} opened`.trim());
    }
    switch (p.cmd) {
      case "SAVE":
        if (!p.arg || !LayoutStore.validName(p.arg)) return say("SAVE <name>: letters, digits, - or _ (up to 32).", true);
        store.save(p.arg, model.toJson());
        return say(`Layout "${p.arg}" saved`);
      case "LOAD": {
        if (!p.arg) return say("LOAD <name>. LAYOUTS lists the saved ones.", true);
        const json = store.load(p.arg);
        if (!json) return say(`Layout "${p.arg}" does not exist or is corrupted.`, true);
        try {
          replaceModel(Model.fromJson(json));
        } catch {
          return say(`Layout "${p.arg}" is incompatible with this version.`, true);
        }
        return say(`Layout "${p.arg}" loaded`);
      }
      case "LAYOUTS":
        return say(`Layouts: ${store.list().join(", ") || "(none saved)"}`);
      case "RESET":
        replaceModel(Model.fromJson(DEFAULT_LAYOUT));
        return say("Default layout restored");
      case "CLOSE":
        if (closeActive(model)) persist(model);
        return say("Tab closed");
    }
  };

  const runFKey = (k: (typeof FKEYS)[number]) => {
    if (!FUNCTIONS[k.fn].needsSymbol) return execute(k.fn);
    const cfg = activeTab(modelRef.current)?.getConfig() as { symbol?: string } | undefined;
    const sym = cfg?.symbol ?? snapRef.current?.quotes[0]?.symbol;
    if (!sym) return say(`${k.fn} needs a security: start a session in REPLAY (F10).`, true);
    const next = openPanel(modelRef.current, k.fn, sym);
    if (next !== modelRef.current) setModel(next);
    persist(next);
    say(`${k.fn} ${secName(sym)} opened`);
  };
  const runFKeyRef = useRef(runFKey);
  runFKeyRef.current = runFKey;

  const onBarKey = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      const text = input.trim();
      if (!text) return;
      history.current.unshift(text);
      hIdx.current = -1;
      execute(text);
      setInput("");
    } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      const next = hIdx.current + (e.key === "ArrowUp" ? 1 : -1);
      if (next < -1 || next >= history.current.length) return;
      hIdx.current = next;
      setInput(next === -1 ? "" : history.current[next]);
    }
  };

  // atalhos globais: teclado primeiro
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const m = modelRef.current;
      const fk = FKEYS.find((k) => k.key === e.key);
      if (fk) {
        e.preventDefault();
        runFKeyRef.current(fk);
        return;
      }
      const typing = e.target instanceof HTMLElement && ["INPUT", "TEXTAREA"].includes(e.target.tagName);
      if (!typing && (e.key === "`" || e.key === "/")) {
        e.preventDefault();
        barRef.current?.focus();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        barRef.current?.focus();
      } else if (e.key === "Escape") {
        barRef.current?.blur();
        setInput("");
      } else if (e.altKey && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
        e.preventDefault();
        cycleTab(m, e.key === "ArrowRight" ? 1 : -1);
        persist(m);
      } else if (e.altKey && /^Digit[1-9]$/.test(e.code)) {
        e.preventDefault();
        const tab = allTabs(m)[Number(e.code.slice(5)) - 1];
        if (tab) {
          focusTab(m, tab.getId());
          persist(m);
        }
      } else if (e.altKey && e.code === "KeyW") {
        e.preventDefault();
        if (closeActive(m)) persist(m);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const tick = setInterval(() => setNow(new Date()), 1000);
    const ping = () =>
      fetch("/api/health").then((r) => setApi(r.ok ? "ok" : "off"), () => setApi("off"));
    ping();
    const poll = setInterval(ping, 10_000);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
    };
  }, []);

  const factory = useCallback((node: TabNode) => {
    const cfg = node.getConfig() as { fn: FnCode; symbol?: string };
    return <Panel fn={cfg.fn} symbol={cfg.symbol} />;
  }, []);

  const active = activeTab(model);
  return (
    <PanelsCtx.Provider value={{ open: openFromPanel }}>
    <div className="app">
      <div className="cmdbar">
        <span className="prompt">&gt;</span>
        <input
          ref={barRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onBarKey}
          placeholder="<security> <function> <GO>   e.g. PETR4 BZ Equity GP · BTCUSDT Crypto GP · MON · HELP"
          spellCheck={false}
          autoComplete="off"
          aria-label="Command line"
        />
        <span className="go">&lt;GO&gt;</span>
        <Clocks now={now} />
      </div>
      <Tape />
      <div className="layout">
        <Layout model={model} factory={factory} onModelChange={(m) => persist(m)} />
      </div>
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}
      </div>
      <div className="fkeys">
        {FKEYS.map((k) => (
          <button key={k.key} onClick={() => runFKey(k)} title={`${k.key}: open ${k.fn}`}>
            <span className="k">{k.key}</span> {k.label}
          </button>
        ))}
      </div>
      <div className={`status${msg.error ? " err" : ""}`}>
        <span className="msg">{msg.text}</span>
        <span className="right">
          {active ? `${active.getName()} · ` : ""}
          {allTabs(model).length} tabs · API {api} · {now.toISOString().slice(0, 19).replace("T", " ")} UTC
        </span>
      </div>
    </div>
    </PanelsCtx.Provider>
  );
}

