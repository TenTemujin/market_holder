// Estado compartilhado dos painéis: snapshot da sessão (REST + WebSocket) e barras processadas.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type Bar, type MarketEvent, type Snapshot } from "./api";

type Listener = (e: MarketEvent) => void;
interface Market {
  snapshot: Snapshot | null;
  connected: boolean;
  refresh: () => Promise<void>;
  subscribe: (fn: Listener) => () => void;
}
const Ctx = createContext<Market | null>(null);

export function MarketProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const listeners = useRef(new Set<Listener>());
  const timer = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      setSnapshot(await api<Snapshot>("GET", "/api/session"));
    } catch {
      setSnapshot(null); // no active session (409) or API down
    }
  }, []);
  const scheduleRefresh = useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(refresh, 120);
  }, [refresh]);

  useEffect(() => {
    let ws: WebSocket | undefined;
    let retry: number | undefined;
    let closed = false;
    const connect = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      ws.onopen = () => {
        setConnected(true);
        void refresh();
      };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data as string);
        if (msg.type === "snapshot") return setSnapshot(msg as Snapshot);
        listeners.current.forEach((fn) => fn(msg as MarketEvent));
        scheduleRefresh();
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = window.setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(retry);
      ws?.close();
    };
  }, [refresh, scheduleRefresh]);

  const subscribe = useCallback((fn: Listener) => {
    listeners.current.add(fn);
    return () => void listeners.current.delete(fn);
  }, []);
  const value = useMemo(() => ({ snapshot, connected, refresh, subscribe }), [snapshot, connected, refresh, subscribe]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useMarket(): Market {
  const m = useContext(Ctx);
  if (!m) throw new Error("useMarket outside MarketProvider");
  return m;
}

/** Barras já processadas do símbolo (nunca futuras), mais as novas via WebSocket. */
export function useBars(symbol: string | undefined): Bar[] {
  const { snapshot, subscribe } = useMarket();
  const [bars, setBars] = useState<Bar[]>([]);
  const sessionId = snapshot?.id;
  useEffect(() => {
    setBars([]);
    if (!symbol || sessionId === undefined) return;
    let alive = true;
    const append = (b: Bar) =>
      setBars((cur) => (cur.length && cur[cur.length - 1].ts >= b.ts ? cur : [...cur, b]));
    const off = subscribe((e) => e.type === "bar" && e.bar.symbol === symbol && alive && append(e.bar));
    api<{ bars: Bar[] }>("GET", `/api/session/bars?symbol=${encodeURIComponent(symbol)}`).then(
      (r) =>
        alive &&
        setBars((cur) => {
          const last = r.bars.length ? r.bars[r.bars.length - 1].ts : "";
          return [...r.bars, ...cur.filter((b) => b.ts > last)];
        }),
      () => undefined,
    );
    return () => {
      alive = false;
      off();
    };
  }, [symbol, sessionId, subscribe]);
  return bars;
}

export interface TickState { price: number; bid: number; ask: number; dir: -1 | 0 | 1; n: number }

/** Latest live quote of a symbol (bid/ask/mid) and the direction of the last move, for flashing. */
export function useTick(symbol: string | undefined): TickState | null {
  const { snapshot, subscribe } = useMarket();
  const [t, setT] = useState<TickState | null>(null);
  const q = snapshot?.quotes.find((x) => x.symbol === symbol);
  useEffect(() => {
    setT(null);
    if (!symbol) return;
    return subscribe((e) => {
      if (e.type !== "tick" || e.symbol !== symbol) return;
      const price = Number(e.price);
      setT((cur) => ({ price, bid: Number(e.bid), ask: Number(e.ask), dir: !cur ? 0 : price > cur.price ? 1 : price < cur.price ? -1 : cur.dir, n: (cur?.n ?? 0) + 1 }));
    });
  }, [symbol, subscribe]);
  if (t) return t;
  if (q?.bid && q.ask) return { price: Number(q.last), bid: Number(q.bid), ask: Number(q.ask), dir: 0, n: 0 };
  return null;
}

// open panels from other panels de outros painéis (ex.: clicar numa linha do MON abre o GP)
import type { FnCode } from "./commands/parse";
export const PanelsCtx = createContext<{ open: (fn: FnCode, symbol?: string) => void }>({ open: () => undefined });
export const usePanels = () => useContext(PanelsCtx);
