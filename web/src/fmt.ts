export const num = (s: string | number | null | undefined, dp = 2): string => {
  if (s === null || s === undefined || s === "") return "–";
  const n = Number(s);
  return Number.isFinite(n) ? n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp }) : String(s);
};
/** Decimal places that fit the price size (cheap crypto needs more). */
export const px = (s: string | number | null | undefined): string => {
  const n = Number(s);
  return num(s, !Number.isFinite(n) ? 2 : n >= 100 ? 2 : n >= 1 ? 4 : 6);
};
export const sign = (s: string | number): string => (Number(s) > 0 ? "up" : Number(s) < 0 ? "down" : "");
export const utc = (iso: string | null | undefined): string => (iso ? iso.slice(0, 16).replace("T", " ") : "–");

const EXCH_NAMES: Record<string, string> = { B3: "BZ", LSE: "LN", XETRA: "GR", TSE: "JT", HKEX: "HK" };
const SECTOR_NAMES: Record<string, string> = {
  EQ: "Equity", CRYPTO: "Crypto", FX: "Curncy", RATE: "Govt", INDEX: "Index", CMDTY: "Comdty", FUND: "Equity", OPT: "Equity", FUT: "Comdty",
};
/** CLASS:MARKET:TICKER becomes the screen name "TICKER EXCH Sector" (e.g. PETR4 BZ Equity). */
export const secName = (symbol: string): string => {
  const [cls, market, ticker] = symbol.split(":");
  return ticker ? `${ticker} ${EXCH_NAMES[market] ?? market} ${SECTOR_NAMES[cls] ?? cls}` : symbol;
};
