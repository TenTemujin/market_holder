"""Relógio de replay: entrega barras em ordem de tempo. O resultado não depende do tempo real.

`ReplayClock` é puro e determinístico (mesmas barras, mesma ordem de eventos).
`ReplayPlayer` só controla o ritmo: chama `step` (que deve consumir um lote do relógio, por
exemplo `Session.step`) respeitando velocidade, pausa e teto de espera entre eventos.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime

from market_holder.domain.models import Bar


class ReplayClock:
    def __init__(self, bars: Iterable[Bar]) -> None:
        # desempate por símbolo: a ordem dos eventos no mesmo instante é sempre a mesma
        self._events = sorted(bars, key=lambda b: (b.ts, str(b.symbol)))
        self._i = 0
        self.now: datetime | None = self._events[0].ts if self._events else None

    @property
    def done(self) -> bool:
        return self._i >= len(self._events)

    @property
    def remaining(self) -> int:
        return len(self._events) - self._i

    def peek_ts(self) -> datetime | None:
        return None if self.done else self._events[self._i].ts

    def next_batch(self) -> list[Bar]:
        """Todas as barras do próximo instante (vários símbolos podem coincidir)."""
        if self.done:
            return []
        ts = self._events[self._i].ts
        j = self._i
        while j < len(self._events) and self._events[j].ts == ts:
            j += 1
        batch = self._events[self._i : j]
        self._i = j
        self.now = ts
        return batch

    def reset(self) -> None:
        self._i = 0
        self.now = self._events[0].ts if self._events else None


class ReplayPlayer:
    def __init__(
        self,
        clock: ReplayClock,
        step: Callable[[], object],
        speed: float = 1.0,
        max_sleep_s: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.clock = clock
        self.step = step
        self.max_sleep_s = max_sleep_s
        self._sleep = sleep
        self._running = asyncio.Event()
        self._running.set()
        self.speed = speed

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, value: float) -> None:
        if value <= 0:
            raise ValueError("speed deve ser positiva")
        self._speed = value

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    async def run(self) -> None:
        while not self.clock.done:
            await self._running.wait()
            self.step()
            nxt = self.clock.peek_ts()
            if nxt is not None and self.clock.now is not None:
                gap = (nxt - self.clock.now).total_seconds() / self._speed
                await self._sleep(min(gap, self.max_sleep_s))
