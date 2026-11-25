// Thin client for the backend API. Decimals and dates arrive as strings.

const OFFLINE = "Cannot reach the API. Start it with dev.cmd (Windows) or ./dev.sh, then try again.";
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  // Reads are idempotent: retry through a brief API restart. Writes are never retried.
  const tries = method === "GET" ? 3 : 1;
  let res: Response | undefined;
  for (let i = 0; i < tries; i++) {
    try {
      res = await fetch(path, {
        method,
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (![502, 503, 504].includes(res.status)) break; // proxy answers these while the API is down
    } catch {
      res = undefined; // network error: server unreachable
    }
    if (i < tries - 1) await sleep(400 * (i + 1));
  }
  if (!res || [502, 503, 504].includes(res.status)) throw new Error(OFFLINE);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* corpo não é JSON */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  try {
    return (await res.json()) as T;
  } catch {
    // HTML instead of JSON = the dev server is not proxying /api to the API
    throw new Error("The server answered with something that is not the API. Restart with dev.cmd / ./dev.sh.");
  }
}

export interface Bar { symbol: string; ts: string; freq: string; open: string; high: string; low: string; close: string; volume: string }
export interface Quote { symbol: string; currency: string; last: string; prev_close: string; volume: string; ts: string | null; bid?: string | null; ask?: string | null; market?: MarketStatus | null }
export interface MarketStatus { open: boolean; next_change: string | null; hours: string }
export interface Fill { order_id: string; symbol: string; side: "BUY" | "SELL"; qty: string; price: string; ts: string; fee: string }
export interface OrderRec {
  id: string; symbol: string; side: "BUY" | "SELL"; type: string; qty: string; ts: string;
  limit_price: string | null; stop_price: string | null; tif: string; oco?: string | null; display_qty?: string | null;
}
export interface OrderState { order: OrderRec; status: string; filled_qty: string; avg_price: string; reject_reason: string }
export interface Position { symbol: string; qty: string; avg_price: string; mark: string; unrealized: string }
export interface SymbolCfg {
  symbol: string; currency: string; tick_size: string; lot_size: string; multiplier: string;
  borrow_rate_annual?: string; locate_limit?: string | null;
}
export interface AlgoTask {
  id: string; algo: "TWAP" | "VWAP"; symbol: string; side: "BUY" | "SELL";
  total_qty: string; slices: number; filled_slices: number; executed_qty: string; active: boolean;
}
export interface BotRec {
  id: string; name: string; strategy: "SMA_CROSS" | "RSI_REV" | "TURTLE_20" | "VWAP_TREND";
  symbol: string; qty: string; active: boolean; params: Record<string, number>;
  signals_count: number; last_signal: string; last_signal_ts: string | null;
}
export interface MacroEventRec { date: string; headline: string; scenario: string }
export interface PortfolioGreeks { delta_dollars: number; gamma: number; theta_daily: number; vega: number }
export interface CorporateActionRec { ts: string; symbol: string; kind: "SPLIT" | "DIVIDEND"; value: string }
export interface Snapshot {
  id: number;
  meta: {
    mode?: "replay" | "live"; freq?: string; start?: string; end?: string | null; symbols?: SymbolCfg[];
    ticks?: string[];
    scenario?: string | null;
    feed?: Record<string, { provider: string; delay_s: number; official: boolean }>;
  };
  quotes: Quote[];
  fills: Fill[];
  clock: { now: string; done: boolean; remaining: number };
  base_currency: string;
  cash: Record<string, string>;
  equity: string;
  gross_exposure: string;
  net_exposure: string;
  margin: { initial_required: string; maintenance_required: string; margin_call: boolean };
  realized: Record<string, string>;
  fees: Record<string, string>;
  borrow_fees?: Record<string, string>;
  live?: { last_poll?: string; errors?: number; last_tick?: string; tick_errors?: number; last_error?: string };
  positions: Position[];
  greeks?: PortfolioGreeks;
  orders: OrderState[];
  algos?: AlgoTask[];
  bots?: BotRec[];
  corporate_actions?: CorporateActionRec[];
  macro_events?: MacroEventRec[];
}
export interface OptionLeg {
  price: number; bid: number; ask: number; delta: number; gamma: number; theta: number; vega: number;
  intrinsic: number; extrinsic: number; itm: boolean;
}
export interface OptionChainRow { strike: number; iv: number; call: OptionLeg; put: OptionLeg }
export interface OptionChainResp {
  symbol: string; spot: number; expiry_days: number; rate: number; base_iv: number; chain: OptionChainRow[];
}
export interface ScreenerRow {
  symbol: string; last: number; chg_pct: number; rvol: number; rsi14: number | null;
  high_20: number; low_20: number; breakout: "HIGH_BREAK" | "LOW_BREAK" | "INSIDE"; vol_annual: number; bars: number;
}
export interface CorrelationResp {
  symbols: string[]; benchmark: string | null; matrix: number[][]; betas: Record<string, number>;
}
export interface MonteCarloResp {
  synthetic: boolean; sample_size: number; paths: number; horizon_trades: number; initial_equity: number;
  win_rate: number; profit_factor: number; expectancy: number; prob_ruin_pct: number;
  equity_p5: number; equity_p50: number; equity_p95: number;
  max_dd_p50_pct: number; max_dd_p95_pct: number; fan_paths: number[][];
}
export interface BookData {
  symbol: string; source: string; bids: [string, string][]; asks: [string, string][];
  trades: { ts: string; price: string; qty: string; side: "BUY" | "SELL" }[];
}
export interface SessionStatsResp {
  total_return_pct: number; benchmark_return_pct: number; alpha_pct: number;
  sharpe: number; sortino: number; calmar: number; max_drawdown_pct: number;
  win_rate_pct: number; profit_factor: number; trades_closed: number;
  curve: { ts: string; equity: number; eq_base100: number; bench_base100: number }[];
}
export interface HistoricalScenario {
  id: string; title: string; description: string; freq: string; start: string; end: string;
  symbols: string; events: { date: string; headline: string }[];
}
export type MarketEvent =
  | { type: "bar"; bar: Bar }
  | { type: "fill"; fill: Fill }
  | { type: "order" }
  | { type: "clock" }
  | { type: "tick"; symbol: string; price: string; bid: string; ask: string; ts: string }
  | { type: "feed_error"; symbol: string; error: string }
  | { type: "macro_event"; event: MacroEventRec };
