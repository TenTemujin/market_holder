"""Sessão de negociação: motor + relógio de replay + eventos para a interface.

Ordens enviadas na sessão levam `ts = agora simulado` (ts da última barra processada),
logo só executam a partir da barra seguinte (regra anti-lookahead do motor).
No início, o preço de referência de cada símbolo é a abertura da sua primeira barra, que é o
preço "de agora" do instante inicial; assim já dá para enviar ordens antes da primeira barra.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Any, Literal

from market_holder.clock.live import LiveClock
from market_holder.clock.replay import ReplayClock
from market_holder.domain.hours import market_status
from market_holder.domain.models import (
    Bar,
    Fill,
    Order,
    OrderStatus,
    OrderType,
    Side,
    Tick,
    TimeInForce,
)
from market_holder.domain.serde import bar_to_dict, fill_to_dict, order_to_dict
from market_holder.domain.symbol import Symbol
from market_holder.engine.engine import Engine, OrderState

Event = dict[str, Any]


@dataclass(slots=True)
class AlgoTask:
    id: str
    algo: Literal["TWAP", "VWAP"]
    symbol: Symbol
    side: Side
    total_qty: Decimal
    slices: int
    filled_slices: int = 0
    executed_qty: Decimal = Decimal(0)
    active: bool = True
    child_order_ids: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "algo": self.algo,
            "symbol": str(self.symbol),
            "side": self.side.value,
            "total_qty": str(self.total_qty),
            "slices": self.slices,
            "filled_slices": self.filled_slices,
            "executed_qty": str(self.executed_qty),
            "active": self.active,
            "child_order_ids": self.child_order_ids or [],
        }


def state_to_dict(st: OrderState) -> dict[str, Any]:
    return {
        "order": order_to_dict(st.order),
        "status": st.status.value,
        "filled_qty": str(st.filled_qty),
        "avg_price": str(st.avg_price),
        "reject_reason": st.reject_reason,
    }


class Session:
    def __init__(
        self,
        engine: Engine,
        bars: list[Bar],
        start: datetime,
        clock: ReplayClock | LiveClock | None = None,
    ) -> None:
        self.engine = engine
        self.clock = clock if clock is not None else ReplayClock(bars)
        self.now = start
        self.id = 0  # definido pela API: muda a cada nova sessão
        self.live: dict[str, Any] = {}  # estado do feed ao vivo: last_poll, errors, last_error
        self.meta: dict[str, Any] = {}  # freq, intervalo e símbolos pedidos
        self.quote_book: dict[Symbol, dict[str, Any]] = {}  # último bid/ask ao vivo
        self.history: dict[Symbol, list[Bar]] = {}  # só barras já processadas (sem lookahead)
        self.listeners: list[Callable[[Event], None]] = []
        self._seq = 0
        self._algo_seq = 0
        self._seen: dict[str, tuple[str, Decimal]] = {}
        self._brackets: dict[str, tuple[Decimal, Decimal]] = {}  # entrada -> (stop, alvo)
        self.algos: dict[str, AlgoTask] = {}
        self.corporate_actions: list[dict[str, Any]] = []
        first: dict[Symbol, Bar] = {}
        for b in sorted(bars, key=lambda b: (b.ts, str(b.symbol))):
            first.setdefault(b.symbol, b)
        for sym, b in first.items():
            engine.account.marks[sym] = b.open

    def seed(self, bars: list[Bar]) -> None:
        """Contexto ao vivo: barras passadas só para o gráfico e o preço de referência."""
        for b in sorted(bars, key=lambda b: (b.ts, str(b.symbol))):
            self.history.setdefault(b.symbol, []).append(b)
            self.engine.account.marks[b.symbol] = b.close

    def emit(self, event: Event) -> None:
        for fn in list(self.listeners):
            fn(event)

    # --- ordens ---

    def place(
        self,
        symbol: Symbol,
        side: Side,
        type_: OrderType,
        qty: Decimal,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
        tif: TimeInForce = TimeInForce.DAY,
        oco: str | None = None,
        display_qty: Decimal | None = None,
    ) -> OrderState:
        self._seq += 1
        order = Order(
            f"O{self._seq}",
            symbol,
            side,
            type_,
            qty,
            self.now,
            limit_price,
            stop_price,
            tif,
            oco,
            display_qty,
        )
        st = self.engine.submit(order)
        self._seen[order.id] = (st.status.value, st.filled_qty)
        self.emit({"type": "order", **state_to_dict(st)})
        return st

    def place_algo(
        self,
        symbol: Symbol,
        side: Side,
        algo: Literal["TWAP", "VWAP"],
        total_qty: Decimal,
        slices: int = 5,
    ) -> AlgoTask:
        """Agenda execução algorítmica fatiada ao longo das próximas `slices` barras."""
        if symbol not in self.engine.account.instruments:
            raise ValueError(f"instrumento desconhecido: {symbol}")
        if total_qty <= 0 or slices < 1 or slices > 200:
            raise ValueError("parâmetros inválidos para algo (qty > 0, 1 <= slices <= 200)")
        self._algo_seq += 1
        task = AlgoTask(
            id=f"A{self._algo_seq}",
            algo=algo,
            symbol=symbol,
            side=side,
            total_qty=total_qty,
            slices=slices,
            child_order_ids=[],
        )
        self.algos[task.id] = task
        self._step_algo_slice(task)
        return task

    def _step_algo_slice(self, task: AlgoTask) -> None:
        if not task.active:
            return
        remaining_slices = task.slices - task.filled_slices
        rem_qty = task.total_qty - task.executed_qty
        if remaining_slices <= 0 or rem_qty <= 0:
            task.active = False
            return
        inst = self.engine.account.instruments[task.symbol]
        if remaining_slices == 1:
            slice_qty = rem_qty
        elif task.algo == "TWAP":
            raw = rem_qty / Decimal(remaining_slices)
            lots = max(Decimal(1), (raw / inst.lot_size).to_integral_value(ROUND_FLOOR))
            slice_qty = min(rem_qty, lots * inst.lot_size)
        else:
            weight = Decimal(1) / Decimal(remaining_slices)
            hist = self.history.get(task.symbol, [])
            if len(hist) >= 2:
                vols = [b.volume for b in hist[-10:] if b.volume > 0]
                if vols:
                    avg_v = sum(vols) / Decimal(len(vols))
                    cur_v = hist[-1].volume
                    ratio = (cur_v / avg_v) if avg_v > 0 else Decimal(1)
                    ratio = max(Decimal("0.5"), min(Decimal("1.8"), ratio))
                    weight = min(Decimal("0.9"), weight * ratio)
            raw = rem_qty * weight
            lots = max(Decimal(1), (raw / inst.lot_size).to_integral_value(ROUND_FLOOR))
            slice_qty = min(rem_qty, lots * inst.lot_size)
        if slice_qty <= 0:
            task.active = False
            return
        st = self.place(task.symbol, task.side, OrderType.MARKET, slice_qty, tif=TimeInForce.GTC)
        if task.child_order_ids is not None:
            task.child_order_ids.append(st.order.id)
        task.filled_slices += 1
        task.executed_qty += slice_qty
        if task.filled_slices >= task.slices or task.executed_qty >= task.total_qty:
            task.active = False

    def modify_order(
        self,
        order_id: str,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
    ) -> OrderState:
        """Altera o preço de uma ordem ativa (ex.: arrastar linha no gráfico GP)."""
        if order_id not in self.engine.orders:
            raise ValueError("ordem não encontrada")
        old_st = self.engine.orders[order_id]
        if not old_st.status.active:
            raise ValueError("só ordens ativas podem ser alteradas")
        old_o = old_st.order
        rem_qty = old_st.leaves_qty
        new_limit = limit_price if limit_price is not None else old_o.limit_price
        new_stop = stop_price if stop_price is not None else old_o.stop_price
        self.cancel(order_id)
        return self.place(
            old_o.symbol,
            old_o.side,
            old_o.type,
            rem_qty,
            new_limit,
            new_stop,
            old_o.tif,
            old_o.oco,
            old_o.display_qty,
        )

    def place_bracket(
        self,
        symbol: Symbol,
        side: Side,
        qty: Decimal,
        entry_type: OrderType,
        stop: Decimal,
        target: Decimal,
        entry_limit: Decimal | None = None,
        tif: TimeInForce = TimeInForce.DAY,
    ) -> OrderState:
        """Entrada + stop-loss + take-profit; stop e alvo viram par OCO quando a entrada enche."""
        if entry_type not in (OrderType.MARKET, OrderType.LIMIT):
            raise ValueError("entrada do bracket deve ser MARKET ou LIMIT")
        mark = self.engine.account.marks.get(symbol)
        ref = entry_limit if entry_type is OrderType.LIMIT else mark
        if ref is None:
            raise ValueError("sem preço de referência para validar o bracket")
        ok = stop < ref < target if side is Side.BUY else target < ref < stop
        if not ok:
            raise ValueError(
                "bracket inválido: compra exige stop < entrada < alvo; "
                "venda exige alvo < entrada < stop"
            )
        st = self.place(symbol, side, entry_type, qty, entry_limit, None, tif)
        if st.status.active or st.status is OrderStatus.FILLED:
            self._brackets[st.order.id] = (stop, target)
        return st

    def place_exits(
        self, symbol: Symbol, stop: Decimal | None, target: Decimal | None
    ) -> list[OrderState]:
        """Stop e/ou alvo para a posição aberta, em grupo OCO (reaproveita o grupo já existente)."""
        pos = self.engine.account.portfolio.positions.get(symbol)
        if pos is None or pos.qty == 0:
            raise ValueError("sem posição aberta para proteger")
        if stop is None and target is None:
            raise ValueError("informe stop e/ou alvo")
        side = Side.SELL if pos.qty > 0 else Side.BUY
        qty = abs(pos.qty)
        mark = self.engine.account.marks.get(symbol)
        if mark is not None:
            if stop is not None and (stop >= mark if pos.qty > 0 else stop <= mark):
                raise ValueError("stop do lado errado do preço atual")
            if target is not None and (target <= mark if pos.qty > 0 else target >= mark):
                raise ValueError("alvo do lado errado do preço atual")
        group = next(
            (
                st.order.oco
                for st in self.engine.orders.values()
                if st.status.active and st.order.symbol == symbol and st.order.oco
                and st.order.oco.startswith("X") and st.order.side is side
            ),
            None,
        ) or f"X{self._seq + 1}"
        out = []
        if stop is not None:
            out.append(
                self.place(symbol, side, OrderType.STOP, qty, None, stop, TimeInForce.GTC, group)
            )
        if target is not None:
            out.append(
                self.place(symbol, side, OrderType.LIMIT, qty, target, None, TimeInForce.GTC, group)
            )
        return out

    def cancel(self, order_id: str) -> bool:
        ok = self.engine.cancel(order_id)
        if ok:
            st = self.engine.orders[order_id]
            self._seen[order_id] = (st.status.value, st.filled_qty)
            self.emit({"type": "order", **state_to_dict(st)})
        return ok

    # --- tempo ---

    def step(self) -> list[Fill]:
        batch = self.clock.next_batch()
        fills: list[Fill] = []
        touched_symbols: set[Symbol] = set()
        for bar in batch:
            fills += self.engine.on_bar(bar)
            self.history.setdefault(bar.symbol, []).append(bar)
            touched_symbols.add(bar.symbol)
            self.emit({"type": "bar", "bar": bar_to_dict(bar)})
        if self.clock.now is not None:
            self.now = max(self.now, self.clock.now)  # o relógio nunca anda para trás
        self._flush(fills)
        for task in list(self.algos.values()):
            if task.active and task.symbol in touched_symbols:
                self._step_algo_slice(task)
        self.emit({"type": "clock", **self.clock_state()})
        return fills

    def fast_forward(self, steps: int = 10000) -> list[Fill]:
        """Executa até `steps` passos em modo headless (sem emitir cada barra no WebSocket)."""
        saved = list(self.listeners)
        self.listeners.clear()
        fills: list[Fill] = []
        try:
            count = 0
            while not self.clock.done and count < steps:
                fills += self.step()
                count += 1
        finally:
            self.listeners[:] = saved
        return fills

    def _arm_brackets(self) -> None:
        for oid, (stop, target) in list(self._brackets.items()):
            st = self.engine.orders[oid]
            if st.status is OrderStatus.FILLED:
                del self._brackets[oid]
                exit_side = Side.SELL if st.order.side is Side.BUY else Side.BUY
                group = f"X{self._seq + 1}"
                sym, qty = st.order.symbol, st.filled_qty
                gtc = TimeInForce.GTC
                self.place(sym, exit_side, OrderType.STOP, qty, None, stop, gtc, group)
                self.place(sym, exit_side, OrderType.LIMIT, qty, target, None, gtc, group)
            elif not st.status.active:
                del self._brackets[oid]  # entrada cancelada, rejeitada ou expirada: sem saídas

    def _flush(self, fills: list[Fill]) -> None:
        for f in fills:
            self.emit({"type": "fill", "fill": fill_to_dict(f)})
        self._arm_brackets()
        for oid, st in self.engine.orders.items():  # mudanças de estado, com ou sem execução
            key = (st.status.value, st.filled_qty)
            if self._seen.get(oid) != key:
                self._seen[oid] = key
                self.emit({"type": "order", **state_to_dict(st)})

    def tick(self, symbol: Symbol, ts: datetime, bid: Decimal, ask: Decimal) -> list[Fill]:
        """Cotação em tempo real (ao vivo): casa ordens no preço médio e avança o 'agora'."""
        if bid <= 0 or ask < bid:
            raise ValueError("cotação inválida")
        mid = (bid + ask) / 2
        self.now = max(self.now, ts)
        self.quote_book[symbol] = {"bid": bid, "ask": ask, "ts": ts}
        fills = self.engine.on_tick(Tick(symbol, ts, mid, source="live"))
        self.emit({
            "type": "tick", "symbol": str(symbol), "price": str(mid),
            "bid": str(bid), "ask": str(ask), "ts": ts.isoformat(),
        })
        self._flush(fills)
        return fills

    def run_until(self, until: datetime) -> list[Fill]:
        fills: list[Fill] = []
        while (nxt := self.clock.peek_ts()) is not None and nxt <= until:
            fills += self.step()
        return fills

    def clock_state(self) -> dict[str, Any]:
        return {
            "now": self.now.isoformat(),
            "done": self.clock.done,
            "remaining": self.clock.remaining,
        }

    # --- visão da conta ---

    def quotes(self) -> list[dict[str, Any]]:
        out = []
        # ao vivo vale o relógio de parede (now só anda com ticks, e mercado fechado não tem tick)
        ref = datetime.now(UTC) if isinstance(self.clock, LiveClock) else self.now
        for sym, inst in self.engine.account.instruments.items():
            hist = self.history.get(sym, [])
            last = self.engine.account.marks.get(sym) if sym in self.quote_book else (
                hist[-1].close if hist else self.engine.account.marks.get(sym)
            )
            prev = hist[-2].close if len(hist) > 1 else (hist[-1].open if hist else last)
            out.append(
                {
                    "symbol": str(sym),
                    "currency": inst.currency,
                    "last": str(last),
                    "prev_close": str(prev),
                    "volume": str(hist[-1].volume) if hist else "0",
                    "ts": hist[-1].ts.isoformat() if hist else None,
                    "bid": str(self.quote_book[sym]["bid"]) if sym in self.quote_book else None,
                    "ask": str(self.quote_book[sym]["ask"]) if sym in self.quote_book else None,
                    "market": market_status(sym, ref),
                }
            )
        return out

    def snapshot(self) -> dict[str, Any]:
        acc = self.engine.account
        m = acc.margin_status()
        positions = [
            {
                "symbol": str(s),
                "qty": str(p.qty),
                "avg_price": str(p.avg_price),
                "mark": str(acc.mark(s)),
                "unrealized": str(acc.unrealized(s)),
            }
            for s, p in acc.portfolio.positions.items()
            if p.qty != 0
        ]
        return {
            "id": self.id,
            "meta": self.meta,
            "live": self.live,
            "quotes": self.quotes(),
            "fills": [fill_to_dict(f) for f in self.engine.fills[-200:]],
            "clock": self.clock_state(),
            "base_currency": acc.portfolio.base_currency,
            "cash": {c: str(v) for c, v in acc.portfolio.cash.items()},
            "equity": str(m.equity),
            "gross_exposure": str(m.gross_exposure),
            "net_exposure": str(acc.net_exposure()),
            "margin": {
                "initial_required": str(m.initial_required),
                "maintenance_required": str(m.maintenance_required),
                "margin_call": m.margin_call,
            },
            "realized": {str(s): str(v) for s, v in acc.realized.items()},
            "fees": {c: str(v) for c, v in acc.fees.items()},
            "borrow_fees": {c: str(v) for c, v in acc.borrow_fees.items()},
            "positions": positions,
            "orders": [state_to_dict(st) for st in self.engine.orders.values()],
            "algos": [a.to_dict() for a in self.algos.values()],
            "corporate_actions": self.corporate_actions,
        }
