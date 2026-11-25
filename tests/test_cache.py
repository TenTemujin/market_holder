import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from market_holder.domain.models import Bar, Freq
from market_holder.domain.symbol import Symbol
from market_holder.providers.base import Capabilities
from market_holder.providers.cache import BarCache, CachedProvider

SYM = Symbol.parse("RATE:FRED:DGS10")
DAY = timedelta(days=1)


def d(day):
    return datetime(2024, 1, day, tzinfo=UTC)


def daily(day):
    return Bar(SYM, d(day), Freq.D1, D(day), D(day), D(day), D(day))


class Fake:
    """Dias úteis (seg-sex) de janeiro/2024; registra as consultas."""

    capabilities = Capabilities("fake", frozenset(), frozenset({Freq.D1}), delay_s=0)

    def __init__(self):
        self.calls = []

    async def search(self, q):
        return []

    async def history(self, symbol, start, end, freq):
        self.calls.append((start, end))
        days = [start + i * DAY for i in range((end - start).days)]
        return [daily(x.day) for x in days if x.weekday() < 5]


def run(coro):
    return asyncio.run(coro)


def test_missing_and_merge_of_adjacent_coverage():
    c = BarCache()
    assert c.missing(SYM, Freq.D1, d(1), d(10)) == [(d(1), d(10))]
    c.put(SYM, Freq.D1, d(3), d(5), [])
    c.put(SYM, Freq.D1, d(5), d(7), [])  # adjacente: funde em [3, 7)
    assert c.missing(SYM, Freq.D1, d(1), d(10)) == [(d(1), d(3)), (d(7), d(10))]
    assert c.missing(SYM, Freq.D1, d(4), d(6)) == []


def test_put_ignores_bars_outside_range():
    c = BarCache()
    c.put(SYM, Freq.D1, d(2), d(4), [daily(1), daily(2), daily(3), daily(4)])
    assert [b.ts.day for b in c.get(SYM, Freq.D1, d(1), d(10))] == [2, 3]


def test_cached_provider_fetches_only_gaps_and_remembers_empty_days():
    inner, cache = Fake(), BarCache()
    p = CachedProvider(inner, cache, now=lambda: d(30))
    first = run(p.history(SYM, d(1), d(8), Freq.D1))  # 1 jan é segunda
    assert [b.ts.day for b in first] == [1, 2, 3, 4, 5]
    assert inner.calls == [(d(1), d(8))]
    run(p.history(SYM, d(1), d(8), Freq.D1))  # fim de semana (6, 7) já coberto
    assert len(inner.calls) == 1
    again = run(p.history(SYM, d(5), d(12), Freq.D1))  # só 8..12 é novo
    assert inner.calls[1] == (d(8), d(12))
    assert [b.ts.day for b in again] == [5, 8, 9, 10, 11]
    assert [b.ts.day for b in run(p.history(SYM, d(1), d(12), Freq.D1))] == [
        1, 2, 3, 4, 5, 8, 9, 10, 11
    ]


def test_recent_tail_is_never_cached():
    inner, cache = Fake(), BarCache()
    # delay 0, período 1 dia: agora = 10/jan 12:00 -> seguro até 9/jan 12:00
    p = CachedProvider(inner, cache, now=lambda: d(10) + timedelta(hours=12))
    run(p.history(SYM, d(8), d(12), Freq.D1))
    covered_end = max(e for _, e in cache._coverage(SYM, Freq.D1))
    assert covered_end == d(10) - timedelta(hours=-12) - DAY  # 9/jan 12:00
    n = len(inner.calls)
    run(p.history(SYM, d(8), d(12), Freq.D1))
    assert len(inner.calls) == n + 1  # só a cauda foi consultada de novo
    assert inner.calls[-1][0] == covered_end
