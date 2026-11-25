"""Yahoo Finance (endpoint de gráfico, NÃO oficial): ações, ETFs, futuros e câmbio globais.

Aviso: API não documentada, pode mudar ou bloquear sem aviso (por isso official=False).
Mapa de símbolos: EQ:US:AAPL -> AAPL; EQ:B3:PETR4 -> PETR4.SA; CMDTY:CME:GC -> GC=F;
FX:YAHOO:EURUSD -> EURUSD=X;
INDEX:US:GSPC -> ^GSPC. Preços são os brutos (sem ajuste de dividendos).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import quote

from market_holder.domain.models import Bar, Freq, Instrument, Tick
from market_holder.domain.symbol import AssetClass, Symbol
from market_holder.providers._util import check_symbol
from market_holder.providers.base import Capabilities
from market_holder.providers.http import Fetcher, UrlFetcher, aget

URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
INTERVALS = {Freq.M1: "1m", Freq.M5: "5m", Freq.H1: "60m", Freq.D1: "1d", Freq.W1: "1wk"}
_CLASSES = frozenset(
    {AssetClass.EQ, AssetClass.CMDTY, AssetClass.FX, AssetClass.FUND, AssetClass.INDEX}
)
# mercado interno -> (sufixo Yahoo, moeda). GBX/ILA/ZAC = subunidade (pence, agorot, cents).
_EXCH: dict[str, tuple[str, str]] = {
    "US": ("", "USD"), "B3": (".SA", "BRL"), "LSE": (".L", "GBX"), "XETRA": (".DE", "EUR"),
    "TSE": (".T", "JPY"), "HKEX": (".HK", "HKD"), "EURONEXT": (".PA", "EUR"),
    "AMS": (".AS", "EUR"), "MIL": (".MI", "EUR"), "BME": (".MC", "EUR"), "BRU": (".BR", "EUR"),
    "LIS": (".LS", "EUR"), "HEL": (".HE", "EUR"), "VIE": (".VI", "EUR"), "SIX": (".SW", "CHF"),
    "TSX": (".TO", "CAD"), "TSXV": (".V", "CAD"), "ASX": (".AX", "AUD"), "NZX": (".NZ", "NZD"),
    "NSE": (".NS", "INR"), "BSE": (".BO", "INR"), "KRX": (".KS", "KRW"), "KOSDAQ": (".KQ", "KRW"),
    "SSE": (".SS", "CNY"), "SZSE": (".SZ", "CNY"), "SGX": (".SI", "SGD"), "TWSE": (".TW", "TWD"),
    "TASE": (".TA", "ILA"), "STO": (".ST", "SEK"), "OSL": (".OL", "NOK"), "CPH": (".CO", "DKK"),
    "WSE": (".WA", "PLN"), "IST": (".IS", "TRY"), "MEX": (".MX", "MXN"), "BCBA": (".BA", "ARS"),
    "JSE": (".JO", "ZAC"), "SET": (".BK", "THB"), "IDX": (".JK", "IDR"), "KLSE": (".KL", "MYR"),
}
_EQ_SUFFIX = {m: s for m, (s, _) in _EXCH.items()}
_BY_SUFFIX = {s: (m, c) for m, (s, c) in _EXCH.items() if s}
SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
_QTYPES = {"EQUITY": AssetClass.EQ, "ETF": AssetClass.EQ, "MUTUALFUND": AssetClass.FUND}


def to_yahoo(symbol: Symbol) -> str:
    if symbol.asset_class in (AssetClass.EQ, AssetClass.FUND):
        try:
            return symbol.ticker + _EQ_SUFFIX[symbol.market]
        except KeyError:
            raise ValueError(f"mercado sem mapa no yahoo: {symbol}") from None
    if symbol.asset_class is AssetClass.INDEX:
        return "^" + symbol.ticker
    if symbol.asset_class is AssetClass.CMDTY:
        return symbol.ticker + "=F"
    return symbol.ticker + "=X"


def from_yahoo(ysym: str, qtype: str, name: str = "") -> Instrument | None:
    """Símbolo Yahoo -> Instrument na nossa simbologia; None se o tipo/bolsa não for atendido."""
    try:
        if qtype == "INDEX" and ysym.startswith("^"):
            return Instrument(Symbol(AssetClass.INDEX, "YAHOO", ysym[1:]), "USD", name)
        if qtype == "CURRENCY" and ysym.endswith("=X"):
            return Instrument(Symbol(AssetClass.FX, "YAHOO", ysym[:-2]), "USD", name)
        if qtype == "FUTURE" and ysym.endswith("=F"):
            return Instrument(Symbol(AssetClass.CMDTY, "CME", ysym[:-2]), "USD", name)
        cls = _QTYPES.get(qtype)
        if cls is None or not ysym.isascii():
            return None
        base, dot, suf = ysym.rpartition(".")
        if dot and f".{suf}" in _BY_SUFFIX:
            market, ccy = _BY_SUFFIX[f".{suf}"]
            return Instrument(Symbol(cls, market, base), ccy, name)
        if dot or "-" in ysym or "=" in ysym:
            return None  # classe de ação alternativa ou sufixo desconhecido: sem mapa confiável
        return Instrument(Symbol(cls, "US", ysym), "USD", name)
    except ValueError:
        return None


def parse_search(payload: dict) -> list[Instrument]:
    out = []
    for q in payload.get("quotes", []):
        name = q.get("shortname") or q.get("longname") or ""
        inst = from_yahoo(q.get("symbol", ""), q.get("quoteType", ""), name)
        if inst:
            out.append(inst)
    return out


def _dec(x: float) -> Decimal:
    return Decimal(str(round(x, 4)))  # o Yahoo devolve ruído de ponto flutuante


def parse_chart(symbol: Symbol, freq: Freq, payload: dict) -> list[Bar]:
    chart = payload["chart"]
    if chart.get("error"):
        raise ValueError(f"yahoo: {chart['error']}")
    result = chart["result"][0]
    stamps = result.get("timestamp") or []
    q = result["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(stamps):
        o, h, lo, c = (q[k][i] for k in ("open", "high", "low", "close"))
        if None in (o, h, lo, c):
            continue  # barra sem negócio
        o, h, lo, c = _dec(o), _dec(h), _dec(lo), _dec(c)
        # o arredondamento pode deixar high/low fora de open/close por 1 casa: corrige
        out.append(
            Bar(
                symbol,
                datetime.fromtimestamp(ts, UTC),
                freq,
                o,
                max(h, o, c),
                min(lo, o, c),
                c,
                Decimal(q["volume"][i] or 0),
            )
        )
    return out


class YahooProvider:
    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or UrlFetcher(min_interval_s=0.5)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            name="yahoo",
            asset_classes=_CLASSES,
            freqs=frozenset(INTERVALS),
            delay_s=900,
            official=False,
        )

    async def search(self, query: str) -> list[Instrument]:
        url = f"{SEARCH_URL}?q={quote(query)}&quotesCount=25&newsCount=0&listsCount=0"
        return parse_search(json.loads(await aget(self.fetcher, url)))

    async def history(
        self, symbol: Symbol, start: datetime, end: datetime, freq: Freq
    ) -> list[Bar]:
        check_symbol(symbol, "yahoo", _CLASSES)
        if freq not in INTERVALS:
            raise ValueError(f"yahoo não atende {freq}")
        url = (
            f"{URL}{quote(to_yahoo(symbol), safe='')}"
            f"?period1={int(start.timestamp())}&period2={int(end.timestamp())}"
            f"&interval={INTERVALS[freq]}&events=history"
        )
        payload = json.loads(await aget(self.fetcher, url))
        return [b for b in parse_chart(symbol, freq, payload) if start <= b.ts < end]

    def stream(self, symbol: Symbol) -> AsyncIterator[Tick]:
        raise NotImplementedError("yahoo sem streaming nesta fase")
