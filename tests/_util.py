"""Helpers de teste do motor."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from market_holder.domain.models import Bar, Freq, Instrument, Order, OrderType, Side
from market_holder.domain.symbol import Symbol
from market_holder.engine.account import Account, MarginPolicy
from market_holder.engine.engine import Engine
from market_holder.engine.execution import ExecutionModel, FeeSchedule

T0 = datetime(2026, 1, 5, 13, 0, tzinfo=UTC)
SYM = Symbol.parse("EQ:B3:PETR4")


def bar(i, o, h, lo, c, v=0, sym=SYM):
    return Bar(sym, T0 + timedelta(minutes=i), Freq.M1, D(str(o)), D(str(h)), D(str(lo)),
               D(str(c)), D(str(v)))


def order(oid, side, kind, qty, ts=T0, **kw):
    for key in ("limit_price", "stop_price"):
        if key in kw:
            kw[key] = D(str(kw[key]))
    return Order(oid, SYM, side, kind, D(str(qty)), ts, **kw)


def make_engine(cash=100000, mark=100, inst=None, model=None, fees=None, policy=None):
    inst = inst or Instrument(SYM, "BRL")
    account = Account("BRL", {"BRL": D(str(cash))}, {inst.symbol: inst}, policy)
    if mark is not None:
        account.marks[inst.symbol] = D(str(mark))
    return Engine(account, model or ExecutionModel(), fees or FeeSchedule())


BUY, SELL = Side.BUY, Side.SELL
MKT, LMT, STP, STL = OrderType.MARKET, OrderType.LIMIT, OrderType.STOP, OrderType.STOP_LIMIT
__all__ = ["BUY", "SELL", "MKT", "LMT", "STP", "STL", "T0", "SYM", "bar", "order",
           "make_engine", "MarginPolicy", "ExecutionModel", "FeeSchedule", "Instrument"]
