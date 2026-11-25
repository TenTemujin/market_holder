"""Tesouro Direto (Tesouro Transparente, CSV oficial): preço unitário de venda por título.

Ticker = TIPO-VENCIMENTO, ex.: RATE:TESOURO:SELIC-20270301, PREFIXADO-20270101,
IPCA_PLUS-20350815. A barra D1 tem open=high=low=close=PU de venda (manhã).
O CSV completo tem ~15 MB: é baixado uma vez e mantido em memória por `ttl_s`.
"""

from __future__ import annotations

import csv
import io
import re
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from decimal import Decimal

from market_holder.domain.models import Bar, Freq, Instrument, Tick
from market_holder.domain.symbol import AssetClass, Symbol
from market_holder.providers._util import check_symbol
from market_holder.providers.base import Capabilities
from market_holder.providers.http import Fetcher, UrlFetcher, aget

URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv"
)
_CLASSES = frozenset({AssetClass.RATE})


def _slug(tipo: str) -> str:
    s = tipo.upper().replace("TESOURO ", "", 1).replace("+", " PLUS ")
    return re.sub(r"[^A-Z0-9]+", "_", s).strip("_")


def _ymd(br_date: str) -> str:
    d, m, y = br_date.split("/")
    return f"{y}{m}{d}"


def parse_csv(text: str) -> dict[str, dict[datetime, Decimal]]:
    """ticker -> {data: PU de venda}. Linhas sem PU de venda são ignoradas."""
    series: dict[str, dict[datetime, Decimal]] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        pu = row["PU Venda Manha"].strip()
        if not pu:
            continue
        ticker = f"{_slug(row['Tipo Titulo'])}-{_ymd(row['Data Vencimento'])}"
        d, m, y = (int(x) for x in row["Data Base"].split("/"))
        series.setdefault(ticker, {})[datetime(y, m, d, tzinfo=UTC)] = Decimal(
            pu.replace(".", "").replace(",", ".")
        )
    return series


class TesouroProvider:
    def __init__(
        self,
        fetcher: Fetcher | None = None,
        ttl_s: float = 6 * 3600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.fetcher = fetcher or UrlFetcher(timeout_s=180)
        self._ttl_s = ttl_s
        self._clock = clock
        self._data: dict[str, dict[datetime, Decimal]] | None = None
        self._loaded_at = 0.0

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            name="tesouro",
            asset_classes=_CLASSES,
            freqs=frozenset({Freq.D1}),
            delay_s=86400,
            official=True,
        )

    async def _series(self) -> dict[str, dict[datetime, Decimal]]:
        if self._data is None or self._clock() - self._loaded_at > self._ttl_s:
            raw = await aget(self.fetcher, URL)
            self._data = parse_csv(raw.decode("latin-1"))
            self._loaded_at = self._clock()
        return self._data

    async def search(self, query: str) -> list[Instrument]:
        q = query.upper()
        return [
            Instrument(Symbol(AssetClass.RATE, "TESOURO", t), "BRL", name=t)
            for t in sorted(await self._series())
            if q in t
        ][:50]

    async def history(
        self, symbol: Symbol, start: datetime, end: datetime, freq: Freq
    ) -> list[Bar]:
        check_symbol(symbol, "tesouro", _CLASSES, "TESOURO")
        if freq is not Freq.D1:
            raise ValueError("tesouro só entrega barras diárias")
        rows = (await self._series()).get(symbol.ticker, {})
        return [
            Bar(symbol, ts, Freq.D1, v, v, v, v)
            for ts, v in sorted(rows.items())
            if start <= ts < end
        ]

    def stream(self, symbol: Symbol) -> AsyncIterator[Tick]:
        raise NotImplementedError("tesouro não tem streaming")
