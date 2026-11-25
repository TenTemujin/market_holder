"""FRED (Fed de St. Louis): juros, câmbio e commodities. Endpoint CSV público, sem chave.

Qualquer série do FRED serve: o ticker é o id da série (ex.: RATE:FRED:DGS10,
FX:FRED:DEXBZUS, CMDTY:FRED:DCOILWTICO). Valor ausente (".") é ignorado.
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal

from market_holder.domain.models import Bar, Freq, Instrument, Tick
from market_holder.domain.symbol import AssetClass, Symbol
from market_holder.providers._util import check_symbol, last_day
from market_holder.providers.base import Capabilities
from market_holder.providers.http import Fetcher, UrlFetcher, aget

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_CLASSES = frozenset({AssetClass.RATE, AssetClass.FX, AssetClass.CMDTY})


def parse_fred_csv(symbol: Symbol, text: str) -> list[Bar]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        raw = row[symbol.ticker]
        if raw in ("", "."):
            continue
        d = date.fromisoformat(row["observation_date"])
        v = Decimal(raw)
        out.append(Bar(symbol, datetime(d.year, d.month, d.day, tzinfo=UTC), Freq.D1, v, v, v, v))
    return out


class FredProvider:
    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or UrlFetcher()

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            name="fred",
            asset_classes=_CLASSES,
            freqs=frozenset({Freq.D1}),
            delay_s=86400,
            official=True,
        )

    async def search(self, query: str) -> list[Instrument]:
        # chisle: sem catálogo; o FRED aceita qualquer id e o usuário digita o id da série
        return []

    async def history(
        self, symbol: Symbol, start: datetime, end: datetime, freq: Freq
    ) -> list[Bar]:
        check_symbol(symbol, "fred", _CLASSES, "FRED")
        if freq is not Freq.D1:
            raise ValueError("fred só entrega barras diárias")
        first, last = start.date(), last_day(end)
        if first > last:
            return []
        url = f"{URL}?id={symbol.ticker}&cosd={first:%Y-%m-%d}&coed={last:%Y-%m-%d}"
        text = (await aget(self.fetcher, url)).decode("utf-8")
        return [b for b in parse_fred_csv(symbol, text) if start <= b.ts < end]

    def stream(self, symbol: Symbol) -> AsyncIterator[Tick]:
        raise NotImplementedError("fred não tem streaming")
