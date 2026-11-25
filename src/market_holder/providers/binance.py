"""Binance spot: API pública, sem chave. Fonte primária dos preços da própria Binance."""

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

BASE = "https://api.binance.com/api/v3"
WS_BASE = "wss://stream.binance.com:9443/stream"
INTERVALS = {Freq.M1: "1m", Freq.M5: "5m", Freq.H1: "1h", Freq.D1: "1d", Freq.W1: "1w"}
LIMIT = 1000
_CLASSES = frozenset({AssetClass.CRYPTO})


def _ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


def parse_klines(symbol: Symbol, freq: Freq, rows: list[list]) -> list[Bar]:
    return [
        Bar(
            symbol,
            datetime.fromtimestamp(r[0] // 1000, UTC),
            freq,
            Decimal(r[1]),
            Decimal(r[2]),
            Decimal(r[3]),
            Decimal(r[4]),
            Decimal(r[5]),  # volume no ativo-base
        )
        for r in rows
    ]


def parse_exchange_info(payload: dict, query: str) -> list[Instrument]:
    out = []
    for s in payload["symbols"]:
        if s.get("status") != "TRADING" or query.upper() not in s["symbol"]:
            continue
        filters = {f["filterType"]: f for f in s["filters"]}
        out.append(
            Instrument(
                Symbol(AssetClass.CRYPTO, "BINANCE", s["symbol"]),
                s["quoteAsset"],
                name=f"{s['baseAsset']}/{s['quoteAsset']}",
                tick_size=Decimal(filters["PRICE_FILTER"]["tickSize"]).normalize(),
                lot_size=Decimal(filters["LOT_SIZE"]["stepSize"]).normalize(),
            )
        )
    return out[:50]


class BinanceProvider:
    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or UrlFetcher()
        # livro tem fetcher próprio: a consulta de 2 s da tela não disputa limite com o feed ao vivo
        self._book_fetcher = fetcher or UrlFetcher()

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            name="binance",
            asset_classes=_CLASSES,
            freqs=frozenset(INTERVALS),
            delay_s=0,
            streaming=False,  # WebSocket entra na Fase 3
            official=True,
        )

    async def search(self, query: str) -> list[Instrument]:
        payload = json.loads(await aget(self.fetcher, f"{BASE}/exchangeInfo"))
        return parse_exchange_info(payload, query)

    async def history(
        self, symbol: Symbol, start: datetime, end: datetime, freq: Freq
    ) -> list[Bar]:
        check_symbol(symbol, "binance", _CLASSES, "BINANCE")
        if freq not in INTERVALS:
            raise ValueError(f"binance não atende {freq}")
        cur, end_ms = _ms(start), _ms(end)
        out: list[Bar] = []
        while cur < end_ms:
            url = (
                f"{BASE}/klines?symbol={symbol.ticker}&interval={INTERVALS[freq]}"
                f"&startTime={cur}&endTime={end_ms - 1}&limit={LIMIT}"
            )
            rows = json.loads(await aget(self.fetcher, url))
            if not rows:
                break
            out += parse_klines(symbol, freq, rows)
            cur = rows[-1][0] + 1
            if len(rows) < LIMIT:
                break
        return out

    async def quotes(self, symbols: list[Symbol]) -> dict[Symbol, tuple[Decimal, Decimal]]:
        """Melhor compra e venda agora (bookTicker), uma consulta para todos os símbolos."""
        for sym in symbols:
            check_symbol(sym, "binance", _CLASSES, "BINANCE")
        names = json.dumps([s.ticker for s in symbols], separators=(",", ":"))
        url = f"{BASE}/ticker/bookTicker?symbols={quote(names)}"
        raw = json.loads(await aget(self._book_fetcher, url))
        by_name = {s.ticker: s for s in symbols}
        return {
            by_name[r["symbol"]]: (Decimal(r["bidPrice"]), Decimal(r["askPrice"]))
            for r in raw
            if r["symbol"] in by_name
        }

    async def quote_stream(
        self, symbols: list[Symbol], connect=None
    ) -> AsyncIterator[tuple[Symbol, Decimal, Decimal]]:
        """Melhor compra/venda por WebSocket (bookTicker): push em ~100 ms, sem polling.

        Termina (ou levanta) quando a conexão cai; quem chama decide reconectar.
        """
        for sym in symbols:
            check_symbol(sym, "binance", _CLASSES, "BINANCE")
        if connect is None:
            import websockets  # extra opcional "api"

            connect = websockets.connect
        by_name = {s.ticker: s for s in symbols}
        streams = "/".join(f"{s.ticker.lower()}@bookTicker" for s in symbols)
        async with connect(f"{WS_BASE}?streams={streams}", open_timeout=10) as ws:
            async for raw in ws:
                data = json.loads(raw).get("data", {})
                sym = by_name.get(data.get("s", ""))
                if sym is not None:
                    yield sym, Decimal(data["b"]), Decimal(data["a"])

    async def book(self, symbol: Symbol, limit: int = 10) -> dict:
        """Livro de ofertas e últimas negociações (dado real, atraso de uma consulta)."""
        check_symbol(symbol, "binance", _CLASSES, "BINANCE")
        tk = symbol.ticker
        fetch = self._book_fetcher
        depth = json.loads(await aget(fetch, f"{BASE}/depth?symbol={tk}&limit={limit}"))
        raw = json.loads(await aget(fetch, f"{BASE}/trades?symbol={tk}&limit=20"))
        return {
            "bids": [[p, q] for p, q in depth["bids"]],
            "asks": [[p, q] for p, q in depth["asks"]],
            "trades": [
                {
                    "ts": datetime.fromtimestamp(t["time"] / 1000, UTC).isoformat(),
                    "price": t["price"],
                    "qty": t["qty"],
                    "side": "SELL" if t["isBuyerMaker"] else "BUY",  # lado do agressor
                }
                for t in reversed(raw)
            ],
        }

    def stream(self, symbol: Symbol) -> AsyncIterator[Tick]:
        raise NotImplementedError("streaming da Binance entra na Fase 3")
