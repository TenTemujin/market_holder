/** Ready-made baskets: [label, CLASS:MARKET:TICKER:CCY]. Everything but crypto comes from Yahoo (unofficial, delayed). */
const eq = (m: string, c: string, t: string[]): [string, string][] => t.map((x) => [x, `EQ:${m}:${x}:${c}`]);

export const UNIVERSE: Record<string, [string, string][]> = {
  "Indices": [
    ["S&P 500", "INDEX:US:GSPC:USD"], ["Nasdaq", "INDEX:US:IXIC:USD"], ["Dow", "INDEX:US:DJI:USD"],
    ["Russell 2000", "INDEX:US:RUT:USD"], ["VIX", "INDEX:US:VIX:USD"], ["FTSE 100", "INDEX:YAHOO:FTSE:GBP"],
    ["DAX", "INDEX:YAHOO:GDAXI:EUR"], ["Nikkei", "INDEX:YAHOO:N225:JPY"], ["Hang Seng", "INDEX:YAHOO:HSI:HKD"],
    ["Ibovespa", "INDEX:YAHOO:BVSP:BRL"],
  ],
  "US mega caps": eq("US", "USD", ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "JPM", "V", "UNH", "XOM", "WMT", "LLY", "AVGO"]),
  "US tech": eq("US", "USD", ["AMD", "INTC", "ORCL", "CRM", "ADBE", "NFLX", "QCOM", "CSCO", "IBM", "PLTR", "UBER", "SHOP", "SNOW", "PANW", "MU"]),
  "US finance & energy": eq("US", "USD", ["BAC", "GS", "MS", "C", "WFC", "MA", "AXP", "BLK", "CVX", "COP", "SLB", "OXY", "KO", "PEP", "DIS"]),
  "ETFs": eq("US", "USD", ["SPY", "QQQ", "IWM", "DIA", "EEM", "EFA", "GLD", "SLV", "TLT", "HYG", "XLF", "XLE", "XLK", "ARKK", "VNQ"]),
  "Brazil (B3)": eq("B3", "BRL", ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "ABEV3", "WEGE3", "RENT3", "B3SA3", "SUZB3", "GGBR4", "ITSA4", "RADL3", "RDOR3", "MGLU3"]),
  "Europe": [
    ...eq("XETRA", "EUR", ["SAP", "SIE", "ALV", "BMW", "VOW3", "ADS"]),
    ...eq("EURONEXT", "EUR", ["MC", "OR", "AIR", "TTE", "SAN"]),
    ...eq("AMS", "EUR", ["ASML", "INGA"]), ...eq("LSE", "GBX", ["SHEL", "AZN", "HSBA", "BP"]),
    ...eq("SIX", "CHF", ["NESN", "UBSG", "NOVN", "ZURN"]),
  ],
  "Asia-Pacific": [
    ...eq("TSE", "JPY", ["7203", "6758", "9984", "8306"]), ...eq("HKEX", "HKD", ["0700", "9988", "1299", "0005"]),
    ...eq("KRX", "KRW", ["005930", "000660"]), ...eq("NSE", "INR", ["RELIANCE", "TCS", "INFY", "HDFCBANK"]),
    ...eq("ASX", "AUD", ["BHP", "CBA", "CSL"]), ...eq("TWSE", "TWD", ["2330"]),
  ],
  "Commodities & FX": [
    ["Gold", "CMDTY:CME:GC:USD"], ["Silver", "CMDTY:CME:SI:USD"], ["Crude WTI", "CMDTY:CME:CL:USD"],
    ["Nat Gas", "CMDTY:CME:NG:USD"], ["Copper", "CMDTY:CME:HG:USD"], ["Corn", "CMDTY:CME:ZC:USD"],
    ["Soybeans", "CMDTY:CME:ZS:USD"], ["EUR/USD", "FX:YAHOO:EURUSD:USD"], ["GBP/USD", "FX:YAHOO:GBPUSD:USD"],
    ["USD/JPY", "FX:YAHOO:USDJPY:JPY"], ["USD/BRL", "FX:YAHOO:USDBRL:BRL"], ["AUD/USD", "FX:YAHOO:AUDUSD:USD"],
  ],
  "Crypto": ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"].map((x): [string, string] => [x, `CRYPTO:BINANCE:${x}USDT:USDT`]),
};
