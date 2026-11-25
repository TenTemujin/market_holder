"""Modelo de domínio. Preços e quantidades em Decimal; tempos em UTC com fuso."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from market_holder.domain.symbol import Symbol

ZERO = Decimal(0)


def _require_utc(ts: datetime, what: str) -> None:
    if ts.tzinfo is None or ts.utcoffset() != UTC.utcoffset(None):
        raise ValueError(f"{what}: datetime precisa ser tz-aware em UTC")


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(StrEnum):
    """Validade da ordem (FIX tag 59): DAY, GTC, IOC, FOK."""

    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderStatus(StrEnum):
    """Estado da ordem (subconjunto do FIX OrdStatus, tag 39)."""

    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

    @property
    def active(self) -> bool:
        return self in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)


class Freq(StrEnum):
    TICK = "tick"
    M1 = "1m"
    M5 = "5m"
    H1 = "1h"
    D1 = "1d"
    W1 = "1w"


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: Symbol
    currency: str
    name: str = ""
    tick_size: Decimal = Decimal("0.01")
    lot_size: Decimal = Decimal(1)
    multiplier: Decimal = Decimal(1)  # tamanho do contrato (futuros, opções)
    borrow_rate_annual: Decimal = Decimal(0)  # taxa anual de aluguel para short (ex.: 0.03)
    locate_limit: Decimal | None = None  # estoque máximo disponível para short (None = ilimitado)

    def __post_init__(self) -> None:
        if self.tick_size <= 0 or self.lot_size <= 0 or self.multiplier <= 0:
            raise ValueError("tick_size, lot_size e multiplier devem ser positivos")
        if self.borrow_rate_annual < 0:
            raise ValueError("borrow_rate_annual não pode ser negativa")
        if self.locate_limit is not None and self.locate_limit < 0:
            raise ValueError("locate_limit não pode ser negativo")


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: Symbol
    ts: datetime  # abertura da barra
    freq: Freq
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = ZERO

    def __post_init__(self) -> None:
        _require_utc(self.ts, "Bar.ts")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("Bar inconsistente: low/high não contêm open/close")
        if self.low > self.high or self.volume < 0:
            raise ValueError("Bar inconsistente: low > high ou volume negativo")


@dataclass(frozen=True, slots=True)
class Tick:
    symbol: Symbol
    ts: datetime
    price: Decimal
    size: Decimal = ZERO
    source: str = ""  # origem do dado
    delay_s: int = 0  # atraso declarado da fonte, em segundos
    simulated: bool = False

    def __post_init__(self) -> None:
        _require_utc(self.ts, "Tick.ts")
        if self.price <= 0 or self.size < 0 or self.delay_s < 0:
            raise ValueError("Tick inválido")


@dataclass(frozen=True, slots=True)
class Order:
    id: str
    symbol: Symbol
    side: Side
    type: OrderType
    qty: Decimal
    ts: datetime
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    tif: TimeInForce = TimeInForce.DAY
    oco: str | None = None  # grupo OCO: quando uma ordem do grupo executa, as outras são canceladas
    display_qty: Decimal | None = None  # lote aparente (Iceberg): limita execução por barra

    def __post_init__(self) -> None:
        _require_utc(self.ts, "Order.ts")
        if self.qty <= 0:
            raise ValueError("qty deve ser positiva")
        if self.display_qty is not None and (self.display_qty <= 0 or self.display_qty > self.qty):
            raise ValueError("display_qty deve estar entre 0 (exclusivo) e qty")
        needs_limit = self.type in (OrderType.LIMIT, OrderType.STOP_LIMIT)
        needs_stop = self.type in (OrderType.STOP, OrderType.STOP_LIMIT)
        if needs_limit != (self.limit_price is not None):
            raise ValueError(f"limit_price incompatível com {self.type}")
        if needs_stop != (self.stop_price is not None):
            raise ValueError(f"stop_price incompatível com {self.type}")
        for p in (self.limit_price, self.stop_price):
            if p is not None and p <= 0:
                raise ValueError("preços de ordem devem ser positivos")


@dataclass(frozen=True, slots=True)
class Fill:
    order_id: str
    symbol: Symbol
    side: Side
    qty: Decimal
    price: Decimal
    ts: datetime
    fee: Decimal = ZERO

    def __post_init__(self) -> None:
        _require_utc(self.ts, "Fill.ts")
        if self.qty <= 0 or self.price <= 0 or self.fee < 0:
            raise ValueError("Fill inválido")


@dataclass(slots=True)
class Position:
    symbol: Symbol
    qty: Decimal = ZERO  # positivo = comprado, negativo = vendido
    avg_price: Decimal = ZERO

    def apply(self, side: Side, qty: Decimal, price: Decimal) -> Decimal:
        """Aplica uma execução e devolve o P&L realizado (sem taxas)."""
        signed = side.sign * qty
        if self.qty == 0 or (self.qty > 0) == (signed > 0):
            total = self.qty + signed
            self.avg_price = (self.avg_price * abs(self.qty) + price * qty) / abs(total)
            self.qty = total
            return ZERO
        closing = min(abs(self.qty), qty)
        realized = closing * (price - self.avg_price) * (1 if self.qty > 0 else -1)
        remaining = self.qty + signed
        if remaining == 0:
            self.avg_price = ZERO
        elif (remaining > 0) != (self.qty > 0):
            self.avg_price = price  # virou a posição
        self.qty = remaining
        return realized


@dataclass(slots=True)
class Portfolio:
    base_currency: str
    cash: dict[str, Decimal] = field(default_factory=dict)
    positions: dict[Symbol, Position] = field(default_factory=dict)
