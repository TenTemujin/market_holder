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
export const utc = (iso: string | null | undefined): string => {
  if (!iso) return "–";
  if (blindMode) {
    const ms = Date.parse(iso);
    if (Number.isFinite(ms)) {
      const day = Math.floor((ms % (365 * 86400_000)) / 86400_000) + 1;
      const time = iso.slice(11, 16);
      return `DAY-${String(day).padStart(3, "0")} ${time}`;
    }
  }
  return iso.slice(0, 16).replace("T", " ");
};

let blindMode = false;
const blindAliases = new Map<string, string>();

export const setBlindMode = (on: boolean): void => {
  blindMode = on;
  if (!on) blindAliases.clear();
};

export const isBlindMode = (): boolean => blindMode;

const EXCH_NAMES: Record<string, string> = { B3: "BZ", LSE: "LN", XETRA: "GR", TSE: "JT", HKEX: "HK" };
const SECTOR_NAMES: Record<string, string> = {
  EQ: "Equity", CRYPTO: "Crypto", FX: "Curncy", RATE: "Govt", INDEX: "Index", CMDTY: "Comdty", FUND: "Equity", OPT: "Equity", FUT: "Comdty",
};
/** CLASS:MARKET:TICKER becomes the screen name "TICKER EXCH Sector" (e.g. PETR4 BZ Equity). */
export const secName = (symbol: string): string => {
  if (blindMode && symbol) {
    let alias = blindAliases.get(symbol);
    if (!alias) {
      alias = `BLIND-${String.fromCharCode(65 + (blindAliases.size % 26))}${blindAliases.size >= 26 ? blindAliases.size : ""}`;
      blindAliases.set(symbol, alias);
    }
    return `${alias} MYST Asset`;
  }
  const [cls, market, ticker] = symbol.split(":");
  return ticker ? `${ticker} ${EXCH_NAMES[market] ?? market} ${SECTOR_NAMES[cls] ?? cls}` : symbol;
};
