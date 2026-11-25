"""Casamento de ordens contra candles (barras ou ticks), slippage e taxas.

Regras de casamento (convenção de backtest, conservadora):
- MARKET executa na abertura do candle.
- LIMIT executa a min(abertura, limite) na compra e max(abertura, limite) na venda
  (gap a favor dá melhoria de preço; nunca pior que o limite).
- STOP dispara quando o candle toca o stop; executa a max(abertura, stop) na compra e
  min(abertura, stop) na venda (gap contra dá preço pior) e vira ordem a mercado.
- STOP_LIMIT dispara como o STOP e então vira LIMIT. Se o preço de disparo já violar o
  limite, a ordem fica ativa como LIMIT e só executa a partir do candle seguinte,
  porque a ordem intra-candle de eventos é desconhecida.
- Spread e impacto de volume só valem para MARKET e STOP disparado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from market_holder.domain.models import ZERO, Bar, Order, OrderType, Side, Tick

BPS = Decimal(10_000)


@dataclass(frozen=True, slots=True)
class Candle:
    """Visão comum de barra e tick para o casamento. volume 0 = desconhecido (sem limite)."""

    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = ZERO

    @classmethod
    def from_bar(cls, bar: Bar) -> Candle:
        return cls(bar.ts, bar.open, bar.high, bar.low, bar.close, bar.volume)

    @classmethod
    def from_tick(cls, tick: Tick) -> Candle:
        # volume do tick ignorado: limitar participação em um único negócio não faz sentido
        return cls(tick.ts, tick.price, tick.price, tick.price, tick.price, ZERO)


@dataclass(frozen=True, slots=True)
class ExecutionModel:
    half_spread_bps: Decimal = ZERO  # meio spread, em pontos-base
    impact_bps: Decimal = ZERO  # pontos-base extras a 100% de participação (linear)
    max_participation: Decimal | None = None  # fração do volume do candle; None = sem limite


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    bps: Decimal = ZERO  # sobre o valor financeiro
    per_order: Decimal = ZERO  # fixo, cobrado na primeira execução da ordem
    minimum: Decimal = ZERO  # mínimo por ordem, aplicado na primeira execução

    def fee(self, notional: Decimal, first_fill: bool) -> Decimal:
        fee = notional * self.bps / BPS
        if first_fill:
            fee = max(fee + self.per_order, self.minimum)
        return fee


@dataclass(frozen=True, slots=True)
class Reference:
    price: Decimal | None  # None = sem execução neste candle
    triggered: bool  # stop já disparado (agora ou antes)
    slippage: bool  # aplica spread e impacto


def _limit_reference(limit: Decimal, c: Candle, buy: bool, triggered: bool) -> Reference:
    reachable = c.low <= limit if buy else c.high >= limit
    if not reachable:
        return Reference(None, triggered, False)
    price = min(c.open, limit) if buy else max(c.open, limit)
    return Reference(price, triggered, False)


def reference(order: Order, c: Candle, triggered: bool) -> Reference:
    buy = order.side is Side.BUY
    kind = order.type
    if triggered and kind is OrderType.STOP:
        kind = OrderType.MARKET
    elif triggered and kind is OrderType.STOP_LIMIT:
        kind = OrderType.LIMIT

    if kind is OrderType.MARKET:
        return Reference(c.open, triggered, True)
    if kind is OrderType.LIMIT:
        assert order.limit_price is not None
        return _limit_reference(order.limit_price, c, buy, triggered)

    assert order.stop_price is not None
    stop = order.stop_price
    hit = c.high >= stop if buy else c.low <= stop
    if not hit:
        return Reference(None, False, False)
    trigger_price = max(c.open, stop) if buy else min(c.open, stop)
    if kind is OrderType.STOP:
        return Reference(trigger_price, True, True)

    assert order.limit_price is not None
    limit = order.limit_price
    within = trigger_price <= limit if buy else trigger_price >= limit
    return Reference(trigger_price if within else None, True, False)


def fill_price(
    ref_price: Decimal,
    side: Side,
    slippage: bool,
    c: Candle,
    qty: Decimal,
    tick_size: Decimal,
    model: ExecutionModel,
) -> Decimal:
    price = ref_price
    if slippage:
        participation = qty / c.volume if c.volume > 0 else ZERO
        bps = model.half_spread_bps + model.impact_bps * participation
        price = price * (1 + side.sign * bps / BPS)
    price = max(c.low, min(c.high, price))  # nunca fora da faixa negociada do candle
    rounding = ROUND_CEILING if side is Side.BUY else ROUND_FLOOR  # arredonda contra o operador
    return (price / tick_size).to_integral_value(rounding) * tick_size
