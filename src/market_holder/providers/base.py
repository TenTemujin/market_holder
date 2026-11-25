"""Interface única de provedor de dados. Um adaptador por fonte; o motor não os conhece."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from market_holder.domain.models import Bar, Freq, Instrument, Tick
from market_holder.domain.symbol import AssetClass, Symbol


@dataclass(frozen=True, slots=True)
class Capabilities:
    """O que o provedor entrega de fato. Obrigatório: evita mostrar dado atrasado como ao vivo."""

    name: str
    asset_classes: frozenset[AssetClass]
    freqs: frozenset[Freq]
    delay_s: int  # atraso típico do dado, em segundos (0 = tempo real)
    streaming: bool = False
    official: bool = False  # fonte oficial (BCB, B3, FRED...) ou não


@runtime_checkable
class Provider(Protocol):
    @property
    def capabilities(self) -> Capabilities: ...

    async def search(self, query: str) -> list[Instrument]: ...

    async def history(
        self, symbol: Symbol, start: datetime, end: datetime, freq: Freq
    ) -> list[Bar]: ...

    def stream(self, symbol: Symbol) -> AsyncIterator[Tick]:
        """Só vale se capabilities.streaming for True; senão levanta NotImplementedError."""
        ...
