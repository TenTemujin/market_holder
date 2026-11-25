"""Cache de barras em SQLite (stdlib) com controle de lacunas.

A tabela `coverage` guarda intervalos [início, fim) já consultados no provedor, inclusive os
que voltaram vazios (fim de semana, feriado), para não repetir a consulta.
O trecho recente (barra ainda aberta ou dado ainda não publicado) nunca entra na cobertura.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from market_holder.domain.models import Bar, Freq, Instrument, Tick
from market_holder.domain.symbol import Symbol
from market_holder.providers.base import Capabilities, Provider

PERIOD_S = {Freq.M1: 60, Freq.M5: 300, Freq.H1: 3600, Freq.D1: 86400, Freq.W1: 604800}
_FMT = "%Y-%m-%dT%H:%M:%S.%f+00:00"  # largura fixa: a ordem lexicográfica é a cronológica

Interval = tuple[datetime, datetime]


def _s(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime(_FMT)


def _t(text: str) -> datetime:
    return datetime.fromisoformat(text)


class BarCache:
    def __init__(self, path: str = ":memory:") -> None:
        # acesso serializado pelo laço de eventos (só o fetch roda em thread), então é seguro
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS bars (
                symbol TEXT, freq TEXT, ts TEXT,
                open TEXT, high TEXT, low TEXT, close TEXT, volume TEXT,
                PRIMARY KEY (symbol, freq, ts));
            CREATE TABLE IF NOT EXISTS coverage (
                symbol TEXT, freq TEXT, start TEXT, end TEXT);
            """
        )

    def _coverage(self, symbol: Symbol, freq: Freq) -> list[Interval]:
        rows = self.db.execute(
            "SELECT start, end FROM coverage WHERE symbol=? AND freq=? ORDER BY start",
            (str(symbol), freq.value),
        ).fetchall()
        return [(_t(a), _t(b)) for a, b in rows]

    def missing(self, symbol: Symbol, freq: Freq, start: datetime, end: datetime) -> list[Interval]:
        gaps: list[Interval] = []
        cur = start
        for s, e in self._coverage(symbol, freq):
            if e <= cur:
                continue
            if s >= end:
                break
            if s > cur:
                gaps.append((cur, min(s, end)))
            cur = max(cur, e)
            if cur >= end:
                break
        if cur < end:
            gaps.append((cur, end))
        return gaps

    def put(
        self, symbol: Symbol, freq: Freq, start: datetime, end: datetime, bars: list[Bar]
    ) -> None:
        """Grava as barras em [start, end) e marca o intervalo inteiro como coberto."""
        with self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?)",
                [
                    (str(symbol), freq.value, _s(b.ts), str(b.open), str(b.high), str(b.low),
                     str(b.close), str(b.volume))
                    for b in bars
                    if start <= b.ts < end
                ],
            )
            merged: list[list[datetime]] = []
            for s, e in sorted([*self._coverage(symbol, freq), (start, end)]):
                if merged and s <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], e)
                else:
                    merged.append([s, e])
            self.db.execute(
                "DELETE FROM coverage WHERE symbol=? AND freq=?", (str(symbol), freq.value)
            )
            self.db.executemany(
                "INSERT INTO coverage VALUES (?,?,?,?)",
                [(str(symbol), freq.value, _s(s), _s(e)) for s, e in merged],
            )

    def get(self, symbol: Symbol, freq: Freq, start: datetime, end: datetime) -> list[Bar]:
        rows = self.db.execute(
            "SELECT ts, open, high, low, close, volume FROM bars "
            "WHERE symbol=? AND freq=? AND ts>=? AND ts<? ORDER BY ts",
            (str(symbol), freq.value, _s(start), _s(end)),
        ).fetchall()
        return [
            Bar(symbol, _t(ts), freq, Decimal(o), Decimal(h), Decimal(lo), Decimal(c), Decimal(v))
            for ts, o, h, lo, c, v in rows
        ]


class CachedProvider:
    """Envolve um Provider: busca só as lacunas e serve o resto do cache."""

    def __init__(
        self,
        inner: Provider,
        cache: BarCache,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.inner = inner
        self.cache = cache
        self._now = now

    @property
    def capabilities(self) -> Capabilities:
        return self.inner.capabilities

    async def search(self, query: str) -> list[Instrument]:
        return await self.inner.search(query)

    def stream(self, symbol: Symbol) -> AsyncIterator[Tick]:
        return self.inner.stream(symbol)

    async def history(
        self, symbol: Symbol, start: datetime, end: datetime, freq: Freq
    ) -> list[Bar]:
        lag = timedelta(seconds=PERIOD_S[freq] + self.inner.capabilities.delay_s)
        safe_end = min(end, self._now() - lag)
        result: list[Bar] = []
        if start < safe_end:
            for gap_start, gap_end in self.cache.missing(symbol, freq, start, safe_end):
                bars = await self.inner.history(symbol, gap_start, gap_end, freq)
                self.cache.put(symbol, freq, gap_start, gap_end, bars)
            result = self.cache.get(symbol, freq, start, safe_end)
        if end > safe_end:  # cauda ainda aberta ou não publicada: sempre consulta, nunca grava
            tail_start = max(start, safe_end)
            result += [
                b
                for b in await self.inner.history(symbol, tail_start, end, freq)
                if tail_start <= b.ts < end
            ]
        return result
