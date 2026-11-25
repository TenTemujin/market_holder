"""Banco Central do Brasil: séries SGS (Selic, CDI, IPCA) e PTAX do dólar (Olinda). Fonte oficial.

Convenções: série diária vira barra D1 com open=high=low=close=valor. IPCA é mensal: a barra
fica no primeiro dia do mês. PTAX tem até 4 boletins por dia: open = primeiro, close = último
(o último é a PTAX de fechamento), high/low = extremos, sobre a cotação de venda.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from market_holder.domain.models import Bar, Freq, Instrument, Tick
from market_holder.domain.symbol import AssetClass, Symbol
from market_holder.providers._util import check_symbol, last_day
from market_holder.providers.base import Capabilities
from market_holder.providers.http import Fetcher, UrlFetcher, aget

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
PTAX_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
)
SGS_SERIES = {  # ticker -> (código SGS, descrição)
    "SELIC": (11, "Selic diária (% a.d.)"),
    "CDI": (12, "CDI diário (% a.d.)"),
    "SELIC_META": (432, "Meta Selic (% a.a.)"),
    "IPCA": (433, "IPCA variação mensal (%)"),
}
_CLASSES = frozenset({AssetClass.FX, AssetClass.RATE})
_CHUNK = timedelta(days=365 * 5)  # o SGS limita o intervalo de séries diárias por consulta


def _midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def parse_sgs(symbol: Symbol, rows: list[dict]) -> list[Bar]:
    out = []
    for r in rows:
        d = datetime.strptime(r["data"], "%d/%m/%Y").date()
        v = Decimal(r["valor"])
        out.append(Bar(symbol, _midnight(d), Freq.D1, v, v, v, v))
    return out


def parse_ptax(symbol: Symbol, payload: dict) -> list[Bar]:
    by_day: dict[str, list[tuple[str, Decimal]]] = {}
    for r in payload["value"]:
        stamp = r["dataHoraCotacao"]
        by_day.setdefault(stamp[:10], []).append((stamp, Decimal(str(r["cotacaoVenda"]))))
    out = []
    for day, quotes in sorted(by_day.items()):
        prices = [p for _, p in sorted(quotes)]
        d = date.fromisoformat(day)
        out.append(
            Bar(symbol, _midnight(d), Freq.D1, prices[0], max(prices), min(prices), prices[-1])
        )
    return out


class BcbProvider:
    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or UrlFetcher()

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            name="bcb",
            asset_classes=_CLASSES,
            freqs=frozenset({Freq.D1}),
            delay_s=86400,
            official=True,
        )

    async def search(self, query: str) -> list[Instrument]:
        q = query.upper()
        found = [
            Instrument(Symbol(AssetClass.RATE, "BCB", t), "PCT", name=desc)
            for t, (_, desc) in SGS_SERIES.items()
            if q in t or q in desc.upper()
        ]
        if q in "USDBRL" or "PTAX" in q:
            found.append(
                Instrument(Symbol(AssetClass.FX, "BCB", "USDBRL"), "BRL", name="PTAX dólar (venda)")
            )
        return found

    async def history(
        self, symbol: Symbol, start: datetime, end: datetime, freq: Freq
    ) -> list[Bar]:
        check_symbol(symbol, "bcb", _CLASSES, "BCB")
        if freq is not Freq.D1:
            raise ValueError("bcb só entrega barras diárias")
        first, last = start.date(), last_day(end)
        if symbol.asset_class is AssetClass.FX and symbol.ticker == "USDBRL":
            bars = await self._ptax(symbol, first, last)
        elif symbol.asset_class is AssetClass.RATE and symbol.ticker in SGS_SERIES:
            bars = await self._sgs(symbol, first, last)
        else:
            raise ValueError(f"série desconhecida no bcb: {symbol}")
        return [b for b in bars if start <= b.ts < end]

    async def _sgs(self, symbol: Symbol, first: date, last: date) -> list[Bar]:
        code = SGS_SERIES[symbol.ticker][0]
        out: list[Bar] = []
        cur = first
        while cur <= last:
            chunk_end = min(last, cur + _CHUNK)
            url = (
                f"{SGS_URL.format(code=code)}?formato=json"
                f"&dataInicial={cur:%d/%m/%Y}&dataFinal={chunk_end:%d/%m/%Y}"
            )
            out += parse_sgs(symbol, json.loads(await aget(self.fetcher, url)))
            cur = chunk_end + timedelta(days=1)
        return out

    async def _ptax(self, symbol: Symbol, first: date, last: date) -> list[Bar]:
        url = (
            f"{PTAX_URL}?@dataInicial='{first:%m-%d-%Y}'&@dataFinalCotacao='{last:%m-%d-%Y}'"
            "&$format=json&$top=100000"
        )
        payload = json.loads(await aget(self.fetcher, url))
        return parse_ptax(symbol, payload)

    def stream(self, symbol: Symbol) -> AsyncIterator[Tick]:
        raise NotImplementedError("bcb não tem streaming")
