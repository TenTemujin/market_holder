"""Modo ao vivo: mesma interface do ReplayClock, mas as barras chegam por `push`.

Ao vivo e replay usam o mesmo caminho (`Session.step` consome `next_batch`); só a fonte do tempo
muda. `LiveFeed` consulta o provedor em intervalo fixo e empurra só barras FECHADAS e novas.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

from market_holder.domain.models import Bar, Freq
from market_holder.domain.symbol import Symbol
from market_holder.providers.base import Provider

PERIOD_S = {Freq.M1: 60, Freq.M5: 300, Freq.H1: 3600, Freq.D1: 86400, Freq.W1: 604800}


class LiveClock:
    def __init__(self, start: datetime) -> None:
        self._pending: list[Bar] = []
        self.now: datetime | None = start

    @property
    def done(self) -> bool:
        return False  # o mercado ao vivo não acaba

    @property
    def remaining(self) -> int:
        return len(self._pending)

    def push(self, bars: list[Bar]) -> None:
        self._pending = sorted(self._pending + bars, key=lambda b: (b.ts, str(b.symbol)))

    def peek_ts(self) -> datetime | None:
        return self._pending[0].ts if self._pending else None

    def next_batch(self) -> list[Bar]:
        if not self._pending:
            return []
        ts = self._pending[0].ts
        n = 0
        while n < len(self._pending) and self._pending[n].ts == ts:
            n += 1
        batch, self._pending = self._pending[:n], self._pending[n:]
        self.now = ts
        return batch


def poll_interval(freq: Freq) -> float:
    """Consulta ~6 vezes por barra, entre 5 s e 60 s."""
    return min(60.0, max(5.0, PERIOD_S[freq] / 6))


class LiveFeed:
    def __init__(
        self,
        provider_for: Callable[[Symbol], Provider],
        symbols: list[Symbol],
        freq: Freq,
        clock: LiveClock,
        step: Callable[[], object],
        *,
        started: datetime,
        interval_s: float | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_error: Callable[[Symbol, Exception], None] = lambda s, e: None,
        status: dict | None = None,
    ) -> None:
        self.status = status if status is not None else {}
        self.provider_for = provider_for
        self.symbols = symbols
        self.freq = freq
        self.clock = clock
        self.step = step
        self.interval_s = interval_s if interval_s is not None else poll_interval(freq)
        self._now, self._sleep, self._on_error = now, sleep, on_error
        self._period = timedelta(seconds=PERIOD_S[freq])
        # só barras que abrem depois do início da sessão entram no motor
        self._seen: dict[Symbol, datetime] = {s: started - self._period for s in symbols}
        self.errors = 0

    async def poll_once(self) -> int:
        """Busca barras novas e fechadas de cada símbolo e avança a sessão. Devolve quantas."""
        now = self._now()
        self.status.update(last_poll=now.isoformat(), errors=self.errors)
        fresh: list[Bar] = []
        for sym in self.symbols:
            lo = self._seen[sym] + timedelta(microseconds=1)
            try:
                got = await self.provider_for(sym).history(sym, lo, now, self.freq)
            except Exception as e:  # rede instável não derruba a sessão: tenta de novo
                self.errors += 1
                self.status.update(errors=self.errors, last_error=f"{sym}: {e!r}")
                self._on_error(sym, e)
                continue
            closed = [b for b in got if b.ts > self._seen[sym] and b.ts + self._period <= now]
            if closed:
                self._seen[sym] = max(b.ts for b in closed)
                fresh += closed
        if fresh:
            self.clock.push(fresh)
            while self.clock.remaining:
                self.step()
        return len(fresh)

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception as e:  # um erro isolado não pode matar a sessão ao vivo
                self.errors += 1
                self.status.update(errors=self.errors, last_error=repr(e))
                self._on_error(self.symbols[0], e)
            await self._sleep(self.interval_s)


class TickFeed:
    """Cotações em tempo real (bid/ask) por polling curto; alimenta `Session.tick`."""

    def __init__(
        self,
        quotes: Callable[[list[Symbol]], Awaitable[dict[Symbol, tuple]]],
        symbols: list[Symbol],
        on_quote: Callable[[Symbol, datetime, object, object], object],
        *,
        interval_s: float = 1.0,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        status: dict | None = None,
    ) -> None:
        self.quotes, self.symbols, self.on_quote = quotes, symbols, on_quote
        self.interval_s, self._now, self._sleep = interval_s, now, sleep
        self.status = status if status is not None else {}
        self.errors = 0

    async def poll_once(self) -> int:
        try:
            got = await self.quotes(self.symbols)
        except Exception as e:  # rede instável: tenta de novo no próximo ciclo
            self.errors += 1
            self.status.update(tick_errors=self.errors, last_tick_error=repr(e))
            return 0
        ts = self._now()
        for sym, (bid, ask) in got.items():
            try:
                self.on_quote(sym, ts, bid, ask)
            except ValueError as e:  # cotação inválida: descarta, não derruba o feed
                self.status.update(last_tick_error=repr(e))
        self.status.update(last_tick=ts.isoformat(), tick_errors=self.errors)
        return len(got)

    async def run(self) -> None:
        while True:
            await self.poll_once()
            await self._sleep(self.interval_s)


class StreamTickFeed:
    """Cotações por WebSocket com queda para polling enquanto a conexão está fora.

    No máximo `min_interval_s` entre cotações do mesmo símbolo (a tela não precisa de mais).
    """

    def __init__(
        self,
        stream: Callable[[list[Symbol]], AsyncIterator[tuple[Symbol, object, object]]],
        symbols: list[Symbol],
        on_quote: Callable[[Symbol, datetime, object, object], object],
        poller: TickFeed,
        *,
        min_interval_s: float = 0.1,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        status: dict | None = None,
    ) -> None:
        self.stream, self.symbols, self.on_quote, self.poller = stream, symbols, on_quote, poller
        self.min_interval = timedelta(seconds=min_interval_s)
        self._now, self._sleep = now, sleep
        self.status = status if status is not None else {}
        self._last: dict[Symbol, datetime] = {}
        self.reconnects = 0

    async def run_once(self) -> int:
        """Uma conexão: consome o stream até acabar ou falhar. Devolve cotações entregues."""
        n = 0
        self.status.update(stream="connecting")
        try:
            async for sym, bid, ask in self.stream(self.symbols):
                self.status.update(stream="up")
                ts = self._now()
                last = self._last.get(sym)
                if last is not None and ts - last < self.min_interval:
                    continue
                self._last[sym] = ts
                try:
                    self.on_quote(sym, ts, bid, ask)
                    n += 1
                except ValueError as e:
                    self.status.update(last_tick_error=repr(e))
            self.status.update(stream="closed")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # conexão caiu: o chamador reconecta
            self.status.update(stream="down", last_tick_error=repr(e))
        return n

    async def run(self) -> None:
        backoff = 1.0
        while True:
            n = await self.run_once()
            self.reconnects += 1
            backoff = 1.0 if n else min(30.0, backoff * 2)
            waited = 0.0
            while waited < backoff:  # fora do ar: segue com polling de 1 s
                await self.poller.poll_once()
                await self._sleep(1.0)
                waited += 1.0
