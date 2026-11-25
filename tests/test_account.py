from decimal import Decimal as D

import pytest

from _util import BUY, SELL, SYM, T0
from market_holder.domain.models import Fill, Instrument
from market_holder.domain.symbol import Symbol
from market_holder.engine.account import Account, MarginPolicy, MissingRateError
from market_holder.engine.execution import FeeSchedule


def make(cash=100000, inst=None, policy=None):
    inst = inst or Instrument(SYM, "BRL")
    return Account("BRL", {"BRL": D(cash)}, {inst.symbol: inst}, policy)


def fill(side, qty, price, fee=0, sym=SYM):
    return Fill("x", sym, side, D(qty), D(str(price)), T0, D(str(fee)))


def test_cash_realized_and_equity_identity():
    a = make()
    a.apply_fill(fill(BUY, 100, 30, fee="3"))
    assert a.portfolio.cash["BRL"] == D(96997)  # 100000 - 3000 - 3
    a.marks[SYM] = D(31)
    assert a.unrealized(SYM) == D(100)
    assert a.equity() == D(100097)  # 96997 + 3100
    realized = a.apply_fill(fill(SELL, 100, 32, fee="3.2"))
    assert realized == D(200)
    assert a.portfolio.cash["BRL"] == D("100193.8")  # 96997 + 3200 - 3.2
    a.marks[SYM] = D(32)
    # equity = capital inicial + realizado - taxas
    assert a.equity() == D(100000) + D(200) - D(3) - D("3.2")
    assert a.fees["BRL"] == D("6.2")


def test_short_position_cash_and_unrealized():
    a = make()
    a.apply_fill(fill(SELL, 100, 50))
    assert a.portfolio.cash["BRL"] == D(105000)
    a.marks[SYM] = D(48)
    assert a.unrealized(SYM) == D(200)  # -100 * (48 - 50)
    assert a.equity() == D(105000) - D(4800)
    assert a.net_exposure() == D(-4800)
    assert a.gross_exposure() == D(4800)


def test_multicurrency_equity_and_missing_rate():
    usd = Symbol.parse("EQ:NASDAQ:AAPL")
    inst = {SYM: Instrument(SYM, "BRL"), usd: Instrument(usd, "USD")}
    a = Account("BRL", {"BRL": D(100000), "USD": D(1000)}, inst)
    with pytest.raises(MissingRateError):
        a.equity()
    a.set_fx("USD", D(5))
    assert a.equity() == D(105000)  # 100000 + 1000 * 5
    a.apply_fill(fill(BUY, 10, 150, sym=usd))
    a.marks[usd] = D(160)
    assert a.portfolio.cash["USD"] == D(-500)
    assert a.unrealized(usd) == D(100)  # em USD
    assert a.equity() == D(100000) + (D(-500) + D(1600)) * D(5)


def test_contract_multiplier_scales_pnl_and_cash():
    fut = Symbol.parse("FUT:B3:WINZ26")
    a = make(inst=Instrument(fut, "BRL", multiplier=D(10)))
    a.apply_fill(fill(BUY, 2, 100, sym=fut))
    assert a.portfolio.cash["BRL"] == D(100000) - D(2000)
    a.marks[fut] = D(101)
    assert a.unrealized(fut) == D(20)  # 2 * 1 * 10
    assert a.apply_fill(fill(SELL, 2, 102, sym=fut)) == D(40)  # 2 * 2 * 10


def test_margin_status_and_call_threshold():
    a = make()
    a.apply_fill(fill(BUY, 1000, 150))  # caixa -50000, exposição 150000
    a.marks[SYM] = D(150)
    s = a.margin_status()
    assert (s.equity, s.gross_exposure) == (D(100000), D(150000))
    assert (s.initial_required, s.maintenance_required) == (D(75000), D(37500))
    assert not s.margin_call
    a.marks[SYM] = D(67)  # equity 17000 > manutenção 16750
    assert not a.margin_status().margin_call
    a.marks[SYM] = D(66)  # equity 16000 < manutenção 16500
    assert a.margin_status().margin_call


def test_check_order_initial_margin_and_reducing_orders():
    a = make()
    assert a.check_order(SYM, BUY, D(1000), D(150)) is None  # 150000 <= 100000 / 0.5
    assert a.check_order(SYM, BUY, D(1500), D(150)) == "insufficient margin"
    a.apply_fill(fill(BUY, 1000, 150))
    a.marks[SYM] = D(60)  # equity muito abaixo do exigido para a exposição atual
    assert a.check_order(SYM, SELL, D(500), D(60)) is None  # reduzir sempre passa
    assert a.check_order(SYM, BUY, D(1), D(60)) == "insufficient margin"


def test_short_selling_can_be_disabled():
    a = make(policy=MarginPolicy(allow_short=False))
    assert a.check_order(SYM, SELL, D(1), D(10)) == "short selling not allowed"
    a.apply_fill(fill(BUY, 10, 10))
    assert a.check_order(SYM, SELL, D(10), D(10)) is None
    assert a.check_order(SYM, SELL, D(11), D(10)) == "short selling not allowed"


def test_fee_schedule_first_fill_only():
    f = FeeSchedule(bps=D(10), per_order=D(1), minimum=D(5))
    assert f.fee(D(3000), first_fill=True) == D(5)  # 3 + 1 = 4 -> mínimo 5
    assert f.fee(D(3000), first_fill=False) == D(3)
    assert f.fee(D(100000), first_fill=True) == D(101)  # 100 + 1
