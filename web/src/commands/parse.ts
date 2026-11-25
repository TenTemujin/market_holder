// Barra de comando: "<ativo> <função>" (ex.: "AAPL GP", "PETR4.B3 GP", "MON", "SAVE meu").
// Mnemônicos próprios e genéricos (inspirados em terminais profissionais, sem copiar nenhum).

export const FUNCTIONS = {
  GP: { title: "Price Chart & Technicals", needsSymbol: true },
  HP: { title: "Historical Prices", needsSymbol: true },
  DES: { title: "Security Description", needsSymbol: true },
  BOOK: { title: "Order Book & Time and Sales", needsSymbol: true },
  OMON: { title: "Option Monitor & Greeks (Black-Scholes)", needsSymbol: false },
  ORD: { title: "Order & Execution Ticket", needsSymbol: false },
  MON: { title: "Multi-Asset Monitor", needsSymbol: false },
  EQS: { title: "Equity Screener & Scanner", needsSymbol: false },
  PORT: { title: "Portfolio, Risk & Blotter", needsSymbol: false },
  CORR: { title: "Correlation Matrix & Beta", needsSymbol: false },
  MC: { title: "Monte Carlo Risk & Ruin Simulator", needsSymbol: false },
  JRNL: { title: "Trade Journal & Tag Analytics", needsSymbol: false },
  ALRT: { title: "Price & Execution Alerts", needsSymbol: false },
  CURVE: { title: "Sovereign Yield Curve & Spreads", needsSymbol: false },
  ECO: { title: "Macro Series & Economic Releases", needsSymbol: false },
  FX: { title: "FX Cross Matrix & Rates", needsSymbol: false },
  REPLAY: { title: "Session, Clock & Blind Replay", needsSymbol: false },
  HELP: { title: "Terminal Command Reference", needsSymbol: false },
} as const;

export type FnCode = keyof typeof FUNCTIONS;

export const SHELL_COMMANDS = ["SAVE", "LOAD", "LAYOUTS", "RESET", "CLOSE", "WS"] as const;
export type ShellCmd = (typeof SHELL_COMMANDS)[number];

export type Parsed =
  | { kind: "panel"; fn: FnCode; symbol?: string }
  | { kind: "shell"; cmd: ShellCmd; arg?: string }
  | { kind: "error"; message: string };

const CLASSES = new Set(["EQ", "CRYPTO", "FX", "RATE", "CMDTY", "FUND", "INDEX", "OPT", "FUT"]);
// classe padrão por mercado, para a forma curta TICKER.MERCADO
const MARKET_CLASS: Record<string, string> = {
  US: "EQ", B3: "EQ", LSE: "EQ", XETRA: "EQ", TSE: "EQ", HKEX: "EQ",
  BINANCE: "CRYPTO", FRED: "RATE", TESOURO: "RATE", BCB: "RATE",
};
const PART = /^[A-Z0-9_\-=^]+$/;
// Sintaxe de linha de comando de terminal profissional: "<ticker> <bolsa> <setor> <função>"
// (ex.: "PETR4 BZ Equity GP", "BTCUSDT Crypto GP"). Códigos de bolsa e setores de uso corrente no mercado.
export const EXCH_CODES: Record<string, string> = { US: "US", BZ: "B3", LN: "LSE", GR: "XETRA", JT: "TSE", HK: "HKEX" };
export const SECTORS: Record<string, string> = {
  EQUITY: "EQ", CRYPTO: "CRYPTO", CURNCY: "FX", INDEX: "INDEX", RATE: "RATE", COMDTY: "CMDTY",
};
const SECTOR_DEFAULT_MARKET: Record<string, string> = { EQ: "US", CRYPTO: "BINANCE", FX: "BCB", RATE: "FRED", INDEX: "US" };

/** Aceita "TICKER [BOLSA] [SETOR]" e devolve CLASSE:MERCADO:TICKER. */
export function resolveTerminalStyle(parts: string[]): string | undefined {
  const up = parts.map((p) => p.toUpperCase());
  const cls = up.length > 1 && up[up.length - 1] in SECTORS ? SECTORS[up.pop() as string] : undefined;
  if (up.length < 1 || up.length > 2 || !PART.test(up[0])) return undefined;
  const market = up.length === 2 ? (EXCH_CODES[up[1]] ?? up[1]) : cls ? SECTOR_DEFAULT_MARKET[cls] : undefined;
  if (!market) return up.length === 1 ? resolveSymbol(up[0]) : undefined;
  if (!(market in MARKET_CLASS)) return undefined; // bolsa desconhecida
  const klass = cls ?? MARKET_CLASS[market];
  return klass && PART.test(market) ? resolveSymbol(`${klass}:${market}:${up[0]}`) : undefined;
}

const isFn = (t: string): t is FnCode => Object.hasOwn(FUNCTIONS, t) || Object.hasOwn(ALIASES, t);
const isShell = (t: string): t is ShellCmd => (SHELL_COMMANDS as readonly string[]).includes(t);

/** Aceita CLASSE:MERCADO:TICKER, TICKER.MERCADO ou TICKER (= EQ:US:TICKER). */
export function resolveSymbol(text: string): string | undefined {
  const t = text.trim().toUpperCase();
  const colon = t.split(":");
  if (colon.length === 3) {
    const [cls, market, ticker] = colon;
    return CLASSES.has(cls) && PART.test(market) && PART.test(ticker) ? t : undefined;
  }
  if (colon.length !== 1) return undefined;
  const dot = t.split(".");
  if (dot.length === 1) return PART.test(t) ? `EQ:US:${t}` : undefined;
  if (dot.length === 2 && PART.test(dot[0]) && dot[1] in MARKET_CLASS) {
    return `${MARKET_CLASS[dot[1]]}:${dot[1]}:${dot[0]}`;
  }
  return undefined;
}

export function parseCommand(input: string): Parsed {
  const tokens = input.trim().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return { kind: "error", message: "Empty command. HELP lists the commands." };

  const head = tokens[0].toUpperCase();
  if (isShell(head)) {
    const arg = tokens.slice(1).join(" ") || undefined;
    return { kind: "shell", cmd: head, arg };
  }

  const fnIdx = [tokens.length - 1, 0].find((i) => isFn(tokens[i].toUpperCase()));
  if (fnIdx === undefined) {
    if (tokens.length === 1) return parseCommand(`${tokens[0]} GP`); // a bare security opens its chart
    return { kind: "error", message: `Unknown function in "${input.trim()}". HELP lists the commands.` };
  }
  const word = tokens[fnIdx].toUpperCase();
  const fn = (ALIASES[word] ?? word) as FnCode;
  const rest = tokens.filter((_, i) => i !== fnIdx);
  if (rest.length > 1) {
    const sym = resolveTerminalStyle(rest);
    if (sym) return { kind: "panel", fn, symbol: sym };
    return { kind: "error", message: `Invalid security: "${rest.join(" ")}". Example: PETR4 BZ Equity ${fn}` };
  }
  if (rest.length === 0) {
    return FUNCTIONS[fn].needsSymbol
      ? { kind: "error", message: `${fn} needs a security. Example: AAPL US Equity ${fn}` }
      : { kind: "panel", fn };
  }
  const symbol = resolveSymbol(rest[0]);
  if (!symbol) {
    return {
      kind: "error",
      message: `Invalid security: "${rest[0]}". Use TICKER, TICKER EXCH SECTOR or CLASS:MARKET:TICKER.`,
    };
  }
  return { kind: "panel", fn, symbol };
}

export const HELP_TEXT =
  "Functions: " + Object.keys(FUNCTIONS).join(" ") +
  " | Layout: WS <SCALP|MACRO|QUANT|OPTIONS> · SAVE <name> · LOAD <name> · LAYOUTS · RESET · CLOSE" +
  " | Security: AAPL US Equity GP · PETR4 BZ Equity GP · BTCUSDT Crypto GP · USDBRL Curncy GP" +
  " | Keys: F1 help · F2..F10 panels · ` or / command line · Esc exit · Alt+←/→ tabs · Alt+W close";

// aliases de funções conhecidas do mercado
export const ALIASES: Record<string, FnCode> = {
  GC: "CURVE",
  FXC: "FX",
  EMSX: "ORD",
  CHAIN: "OMON",
  OPT: "OMON",
  SCAN: "EQS",
  BLIND: "REPLAY",
};
