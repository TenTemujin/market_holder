"""Motor de simulação: ciclo de vida de ordens (estados FIX) contra candles.

Regra anti-lookahead: uma ordem enviada antes de on_bar/on_tick só é elegível ao candle
cujo ts for >= order.ts. O candle seguinte ao envio é o primeiro em que ela pode executar.
O ts do Fill é o ts do candle (a hora exata intra-candle é desconhecida).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from market_holder.domain.hours import session_date_for
from market_holder.domain.models import (
    ZERO,
    Bar,
    Fill,
    Order,
    OrderStatus,
    OrderType,
    Side,
    Tick,
    TimeInForce,
)
from market_holder.domain.symbol import Symbol
from market_holder.engine.account import Account, MissingRateError
from market_holder.engine.execution import (
    Candle,
    ExecutionModel,
    FeeSchedule,
    fill_price,
    reference,
)


def _utc_date(ts: datetime) -> Any:
    return ts.date()


@dataclass(slots=True)
class OrderState:
    order: Order
    session: Any  # sessão no envio, para expirar ordens DAY
    status: OrderStatus = OrderStatus.NEW
    filled_qty: Decimal = ZERO
    avg_price: Decimal = ZERO
    reject_reason: str = ""
    triggered: bool = False

    @property
    def leaves_qty(self) -> Decimal:
        return self.order.qty - self.filled_qty


_STOPS = (OrderType.STOP, OrderType.STOP_LIMIT)


class Engine:
    def __init__(
        self,
        account: Account,
        model: ExecutionModel | None = None,
        fees: FeeSchedule | None = None,
        # chisle: sessão = data UTC; trocar por calendário do pregão (B3, NYSE) na Fase 2
        session_of: Callable[[datetime], Any] = _utc_date,
    ) -> None:
        self.account = account
        self.model = model or ExecutionModel()
        self.fees = fees or FeeSchedule()
        self.session_of = session_of
        self.orders: dict[str, OrderState] = {}
        self.fills: list[Fill] = []
        self._last_session: Any = None
        self._liq_seq: int = 0

    # --- ordens ---

    def _session_key(self, symbol: Symbol, ts: datetime) -> Any:
        if self.session_of is _utc_date:
            return session_date_for(symbol, ts)
        return self.session_of(ts)

    def submit(self, order: Order) -> OrderState:
        if order.id in self.orders:
            raise ValueError(f"id de ordem duplicado: {order.id}")
        state = OrderState(order, self._session_key(order.symbol, order.ts))
        reason = self._validate(order)
        if reason:
            state.status = OrderStatus.REJECTED
            state.reject_reason = reason
        self.orders[order.id] = state
        return state

    def cancel(self, order_id: str) -> bool:
        state = self.orders[order_id]
        if not state.status.active:
            return False
        state.status = OrderStatus.CANCELED
        return True

    def _validate(self, order: Order) -> str | None:
        inst = self.account.instruments.get(order.symbol)
        if inst is None:
            return "unknown instrument"
        if order.tif in (TimeInForce.IOC, TimeInForce.FOK) and order.type not in (
            OrderType.MARKET,
            OrderType.LIMIT,
        ):
            return "IOC/FOK only for MARKET and LIMIT"
        if order.qty % inst.lot_size != 0:
            return "qty not multiple of lot size"
        if order.display_qty is not None and order.display_qty % inst.lot_size != 0:
            return "display_qty not multiple of lot size"
        for price in (order.limit_price, order.stop_price):
            if price is not None and price % inst.tick_size != 0:
                return "price not on tick size"
        ref = order.limit_price or order.stop_price or self.account.marks.get(order.symbol)
        if ref is None:
            return "no reference price"
        try:
            return self.account.check_order(order.symbol, order.side, order.qty, ref)
        except MissingRateError:
            return "no fx rate"

    # --- mercado ---

    def on_bar(self, bar: Bar) -> list[Fill]:
        return self._process(bar.symbol, Candle.from_bar(bar))

    def on_tick(self, tick: Tick) -> list[Fill]:
        return self._process(tick.symbol, Candle.from_tick(tick))

    def _process(self, symbol: Symbol, c: Candle) -> list[Fill]:
        inst = self.account.instruments.get(symbol)
        if inst is None:
            raise ValueError(f"instrumento desconhecido: {symbol}")
        budget: Decimal | None = None
        if self.model.max_participation is not None and c.volume > 0:
            budget = c.volume * self.model.max_participation
        fills: list[Fill] = []
        session = self._session_key(symbol, c.ts)
        utc_day = _utc_date(c.ts)
        if self._last_session is not None and utc_day != self._last_session:
            self.account.charge_borrow_fee(1)
        self._last_session = utc_day
        done_oco: set[str] = set()

        # OCO: se stop e alvo do mesmo grupo cabem na mesma barra, o stop vem primeiro (pior caso
        # para quem opera; o candle não diz qual foi tocado antes)
        todo = [s for s in self.orders.values() if s.order.symbol == symbol]
        todo.sort(key=lambda s: 0 if s.order.oco and s.order.type in _STOPS else 1)
        for st in todo:
            o = st.order
            if not st.status.active or o.ts > c.ts:
                continue
            if o.oco and o.oco in done_oco:
                st.status = OrderStatus.CANCELED
                continue
            if o.tif is TimeInForce.DAY and st.session != session:
                st.status = OrderStatus.EXPIRED
                continue
            ref = reference(o, c, st.triggered)
            st.triggered = ref.triggered
            if ref.price is None:
                if o.tif in (TimeInForce.IOC, TimeInForce.FOK):
                    st.status = OrderStatus.CANCELED
                continue

            qty = st.leaves_qty
            if o.display_qty is not None:
                qty = min(qty, o.display_qty)
            if budget is not None:
                lots = (budget / inst.lot_size).to_integral_value(ROUND_FLOOR)
                qty = min(qty, lots * inst.lot_size)
            if o.tif is TimeInForce.FOK and qty < st.leaves_qty:
                st.status = OrderStatus.CANCELED
                continue
            if qty <= 0:
                if o.tif is TimeInForce.IOC:
                    st.status = OrderStatus.CANCELED
                continue

            price = fill_price(ref.price, o.side, ref.slippage, c, qty, inst.tick_size, self.model)
            notional = qty * price * inst.multiplier
            fee = self.fees.fee(notional, first_fill=st.filled_qty == 0)
            fill = Fill(o.id, symbol, o.side, qty, price, c.ts, fee)
            self.account.apply_fill(fill)
            st.avg_price = (st.avg_price * st.filled_qty + price * qty) / (st.filled_qty + qty)
            st.filled_qty += qty
            if budget is not None:
                budget -= qty
            if st.leaves_qty == 0:
                st.status = OrderStatus.FILLED
            elif o.tif is TimeInForce.IOC:
                st.status = OrderStatus.CANCELED  # resto cancelado, execução parcial mantida
            else:
                st.status = OrderStatus.PARTIALLY_FILLED
            fills.append(fill)
            self.fills.append(fill)
            if o.oco:
                done_oco.add(o.oco)
                for other in self.orders.values():  # irmãs em outros símbolos ou já avaliadas
                    if other is not st and other.order.oco == o.oco and other.status.active:
                        other.status = OrderStatus.CANCELED

        self.account.marks[symbol] = c.close
        if self.account.policy.auto_liquidate and self.account.margin_status().margin_call:
            fills += self._auto_liquidate(c.ts)
        return fills

    def _auto_liquidate(self, ts: datetime) -> list[Fill]:
        """Liquida posições abertas a preço de marcação quando equity < maintenance_required."""
        liq_fills: list[Fill] = []
        # Cancela ordens ativas que poderiam aumentar exposição durante margin call
        for st in self.orders.values():
            if st.status.active:
                st.status = OrderStatus.CANCELED
        positions = [
            (s, p)
            for s, p in self.account.portfolio.positions.items()
            if p.qty != 0
        ]
        # Liquida primeiro a maior exposição bruta
        positions.sort(
            key=lambda sp: abs(
                self.account._position_value_base(sp[0], sp[1].qty, self.account.mark(sp[0]))
            ),
            reverse=True,
        )
        for sym, pos in positions:
            if not self.account.margin_status().margin_call:
                break
            if pos.qty == 0:
                continue
            inst = self.account.instruments[sym]
            price = self.account.mark(sym)
            side = Side.SELL if pos.qty > 0 else Side.BUY
            qty = abs(pos.qty)
            notional = qty * price * inst.multiplier
            fee = self.fees.fee(notional, first_fill=True)
            self._liq_seq += 1
            oid = f"LIQ{self._liq_seq}"
            order = Order(oid, sym, side, OrderType.MARKET, qty, ts)
            st = OrderState(
                order,
                self.session_of(ts),
                status=OrderStatus.FILLED,
                filled_qty=qty,
                avg_price=price,
                reject_reason="MARGIN_CALL_LIQUIDATION",
            )
            self.orders[oid] = st
            fill = Fill(oid, sym, side, qty, price, ts, fee)
            self.account.apply_fill(fill)
            self.fills.append(fill)
            liq_fills.append(fill)
        return liq_fills
