// Thin client for the backend API. Decimals and dates arrive as strings.

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
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
  return (await res.json()) as T;
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
export interface CorporateActionRec { ts: string; symbol: string; kind: "SPLIT" | "DIVIDEND"; value: string }
export interface Snapshot {
  id: number;
  meta: {
    mode?: "replay" | "live"; freq?: string; start?: string; end?: string | null; symbols?: SymbolCfg[];
    ticks?: string[];
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
  orders: OrderState[];
  algos?: AlgoTask[];
  corporate_actions?: CorporateActionRec[];
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
export type MarketEvent =
  | { type: "bar"; bar: Bar }
  | { type: "fill"; fill: Fill }
  | { type: "order" }
  | { type: "clock" }
  | { type: "tick"; symbol: string; price: string; bid: string; ask: string; ts: string }
  | { type: "feed_error"; symbol: string; error: string };
