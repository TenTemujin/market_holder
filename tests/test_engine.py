from datetime import timedelta
from decimal import Decimal as D

import pytest

from _util import BUY, LMT, MKT, SELL, STL, STP, SYM, T0, bar, make_engine, order
from market_holder.domain.models import (
    Bar,
    Freq,
    Instrument,
    OrderStatus,
    Tick,
    TimeInForce,
)
from market_holder.domain.symbol import Symbol
from market_holder.engine.account import MarginPolicy
from market_holder.engine.execution import ExecutionModel, FeeSchedule

S = OrderStatus


# --- MARKET e slippage ---


def test_market_buy_fills_at_open_plus_half_spread():
    e = make_engine(model=ExecutionModel(half_spread_bps=D(10)))
    st = e.submit(order("1", BUY, MKT, 100))
    (f,) = e.on_bar(bar(0, 100, 101, 99, 100))
    assert f.price == D("100.10")  # 100 * 1.001
    assert (st.status, st.filled_qty, st.avg_price) == (S.FILLED, D(100), D("100.10"))
    assert e.account.portfolio.cash["BRL"] == D(100000) - D(100) * D("100.10")
    assert e.account.portfolio.positions[SYM].qty == D(100)


def test_market_sell_fills_below_open_and_goes_short():
    e = make_engine(model=ExecutionModel(half_spread_bps=D(10)))
    e.submit(order("1", SELL, MKT, 100))
    (f,) = e.on_bar(bar(0, 100, 101, 99, 100))
    assert f.price == D("99.90")
    assert e.account.portfolio.positions[SYM].qty == D(-100)


def test_slippage_is_clamped_to_candle_range():
    e = make_engine(model=ExecutionModel(half_spread_bps=D(500)))  # 5%
    e.submit(order("1", BUY, MKT, 10))
    (f,) = e.on_bar(bar(0, 100, 101, 99, 100))
    assert f.price == D(101)  # 105 limitado à máxima


def test_market_impact_scales_with_participation():
    e = make_engine(model=ExecutionModel(impact_bps=D(100)))  # 1% a 100% de participação
    e.submit(order("1", BUY, MKT, 100))
    (f,) = e.on_bar(bar(0, 100, 102, 99, 100, v=1000))  # 10% -> 10 bps
    assert f.price == D("100.10")


# --- LIMIT ---


def test_limit_buy_fills_at_limit_when_touched_intrabar():
    e = make_engine()
    e.submit(order("1", BUY, LMT, 10, limit_price=99))
    (f,) = e.on_bar(bar(0, 100, 101, 98.5, 100))
    assert f.price == D(99)


def test_limit_buy_gap_gives_price_improvement():
    e = make_engine()
    e.submit(order("1", BUY, LMT, 10, limit_price=99))
    (f,) = e.on_bar(bar(0, 98, 101, 97, 100))
    assert f.price == D(98)


def test_limit_buy_not_reached_stays_working_then_fills_later():
    e = make_engine()
    st = e.submit(order("1", BUY, LMT, 10, limit_price=99, tif=TimeInForce.GTC))
    assert e.on_bar(bar(0, 100, 101, 99.5, 100)) == []
    assert st.status is S.NEW
    (f,) = e.on_bar(bar(1, 99.2, 100, 98.9, 99))
    assert f.price == D(99)  # abertura 99.2 pior que o limite
    assert st.status is S.FILLED


def test_limit_sell_mirror():
    e = make_engine()
    e.submit(order("1", SELL, LMT, 10, limit_price=101))
    (f,) = e.on_bar(bar(0, 100, 101.5, 99, 100))
    assert f.price == D(101)
    e.submit(order("2", SELL, LMT, 10, limit_price=101))
    (g,) = e.on_bar(bar(1, 102, 103, 101, 102))
    assert g.price == D(102)  # gap a favor


# --- STOP ---


def test_stop_buy_triggers_at_stop_price():
    e = make_engine()
    e.submit(order("1", BUY, STP, 10, stop_price=102))
    assert e.on_bar(bar(0, 100, 101.9, 99, 101)) == []
    (f,) = e.on_bar(bar(1, 101, 103, 100, 102))
    assert f.price == D(102)


def test_stop_buy_gap_fills_at_open_worse_than_stop():
    e = make_engine()
    e.submit(order("1", BUY, STP, 10, stop_price=102))
    (f,) = e.on_bar(bar(0, 104, 105, 103, 104))
    assert f.price == D(104)


def test_stop_sell_triggers_and_gaps():
    e = make_engine()
    e.submit(order("1", SELL, STP, 10, stop_price=98))
    (f,) = e.on_bar(bar(0, 100, 101, 97, 99))
    assert f.price == D(98)
    e.submit(order("2", SELL, STP, 10, stop_price=98))
    (g,) = e.on_bar(bar(1, 96, 97, 95, 96))
    assert g.price == D(96)


def test_triggered_stop_with_partial_fill_continues_as_market():
    e = make_engine(model=ExecutionModel(max_participation=D("0.1")))
    st = e.submit(order("1", BUY, STP, 150, stop_price=102))
    (f1,) = e.on_bar(bar(0, 100, 103, 99, 102, v=1000))  # cota 100
    assert (f1.qty, f1.price, st.status) == (D(100), D(102), S.PARTIALLY_FILLED)
    (f2,) = e.on_bar(bar(1, 101, 101.5, 100, 101, v=1000))  # sem tocar o stop, mas já disparado
    assert (f2.qty, f2.price, st.status) == (D(50), D(101), S.FILLED)


# --- STOP_LIMIT ---


def test_stop_limit_buy_fills_at_trigger_when_within_limit():
    e = make_engine()
    e.submit(order("1", BUY, STL, 10, stop_price=102, limit_price=103))
    (f,) = e.on_bar(bar(0, 100, 105, 99, 104))
    assert f.price == D(102)


def test_stop_limit_buy_gap_beyond_limit_rests_until_next_candle():
    e = make_engine()
    st = e.submit(order("1", BUY, STL, 10, stop_price=102, limit_price=103, tif=TimeInForce.GTC))
    assert e.on_bar(bar(0, 104, 106, 104, 105)) == []  # disparou em 104 > limite 103
    assert st.triggered and st.status is S.NEW
    (f,) = e.on_bar(bar(1, 103.5, 104, 102.8, 103))
    assert f.price == D(103)  # agora é LIMIT: abertura 103.5 pior que 103


# --- participação, TIF ---


def test_participation_cap_gives_partial_fills():
    e = make_engine(mark=10, model=ExecutionModel(max_participation=D("0.1")))
    st = e.submit(order("1", BUY, MKT, 250, tif=TimeInForce.GTC))
    qtys = []
    for i in range(3):
        qtys += [f.qty for f in e.on_bar(bar(i, 10, 11, 9, 10, v=1000))]
        if i == 0:
            assert st.status is S.PARTIALLY_FILLED
    assert qtys == [D(100), D(100), D(50)]
    assert (st.status, st.filled_qty, st.avg_price) == (S.FILLED, D(250), D(10))


def test_participation_budget_is_shared_between_orders_fifo():
    e = make_engine(mark=10, model=ExecutionModel(max_participation=D("0.1")))
    a = e.submit(order("a", BUY, MKT, 80))
    b = e.submit(order("b", BUY, MKT, 80))
    e.on_bar(bar(0, 10, 11, 9, 10, v=1000))
    assert (a.filled_qty, b.filled_qty) == (D(80), D(20))


def test_ioc_partial_fill_cancels_remainder():
    e = make_engine(mark=10, model=ExecutionModel(max_participation=D("0.1")))
    st = e.submit(order("1", BUY, MKT, 250, tif=TimeInForce.IOC))
    (f,) = e.on_bar(bar(0, 10, 11, 9, 10, v=1000))
    assert f.qty == D(100)
    assert (st.status, st.filled_qty) == (S.CANCELED, D(100))


def test_fok_cancels_when_it_cannot_fill_entirely():
    e = make_engine(mark=10, model=ExecutionModel(max_participation=D("0.1")))
    st = e.submit(order("1", BUY, MKT, 250, tif=TimeInForce.FOK))
    assert e.on_bar(bar(0, 10, 11, 9, 10, v=1000)) == []
    assert (st.status, st.filled_qty) == (S.CANCELED, D(0))
    ok = e.submit(order("2", BUY, MKT, 100, tif=TimeInForce.FOK, ts=T0 + timedelta(minutes=1)))
    e.on_bar(bar(1, 10, 11, 9, 10, v=1000))
    assert ok.status is S.FILLED


def test_ioc_limit_not_marketable_is_canceled():
    e = make_engine()
    st = e.submit(order("1", BUY, LMT, 10, limit_price=95, tif=TimeInForce.IOC))
    e.on_bar(bar(0, 100, 101, 99, 100))
    assert st.status is S.CANCELED


def test_day_order_expires_next_session_gtc_survives():
    e = make_engine()
    day = e.submit(order("d", BUY, LMT, 10, limit_price=90, tif=TimeInForce.DAY))
    gtc = e.submit(order("g", BUY, LMT, 10, limit_price=90, tif=TimeInForce.GTC))
    e.on_bar(bar(0, 100, 101, 99, 100))
    assert (day.status, gtc.status) == (S.NEW, S.NEW)
    next_day = Bar(SYM, T0 + timedelta(days=1), Freq.M1, D(100), D(101), D(99), D(100))
    e.on_bar(next_day)
    assert (day.status, gtc.status) == (S.EXPIRED, S.NEW)


def test_order_is_not_eligible_before_its_timestamp():
    e = make_engine()
    st = e.submit(order("1", BUY, MKT, 10, ts=T0 + timedelta(minutes=5)))
    assert e.on_bar(bar(0, 100, 101, 99, 100)) == []
    assert st.status is S.NEW
    (f,) = e.on_bar(bar(5, 102, 103, 101, 102))
    assert f.price == D(102)


# --- ciclo de vida e rejeições ---


def test_cancel_working_order_and_filled_order():
    e = make_engine()
    e.submit(order("w", BUY, LMT, 10, limit_price=90, tif=TimeInForce.GTC))
    e.submit(order("m", BUY, MKT, 10))
    e.on_bar(bar(0, 100, 101, 99, 100))
    assert e.cancel("w") is True and e.orders["w"].status is S.CANCELED
    assert e.cancel("m") is False
    assert e.on_bar(bar(1, 89, 100, 88, 90)) == []  # cancelada não executa


def test_duplicate_order_id_raises():
    e = make_engine()
    e.submit(order("1", BUY, MKT, 1))
    with pytest.raises(ValueError):
        e.submit(order("1", BUY, MKT, 1))


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        (dict(kind=MKT, qty=150), "lot size"),
        (dict(kind=LMT, qty=100, limit_price="99.005"), "tick size"),
        (dict(kind=STP, qty=100, stop_price=99, tif=TimeInForce.IOC), "IOC/FOK"),
        (dict(kind=LMT, qty=100000, limit_price=150), "margin"),
    ],
)
def test_pre_trade_rejections(kwargs, reason):
    e = make_engine(inst=Instrument(SYM, "BRL", lot_size=D(100)))
    kind, qty = kwargs.pop("kind"), kwargs.pop("qty")
    st = e.submit(order("1", BUY, kind, qty, **kwargs))
    assert st.status is S.REJECTED and reason in st.reject_reason
    assert e.on_bar(bar(0, 100, 101, 99, 100)) == []


def test_reject_unknown_instrument_and_no_reference_price():
    e = make_engine(mark=None)
    assert "no reference price" in e.submit(order("1", BUY, MKT, 1)).reject_reason
    other = Symbol.parse("EQ:B3:VALE3")
    from market_holder.domain.models import Order

    st = e.submit(Order("2", other, BUY, MKT, D(1), T0))
    assert st.reject_reason == "unknown instrument"


def test_margin_accepts_within_limit_and_rejects_beyond():
    e = make_engine()
    assert e.submit(order("1", BUY, LMT, 1000, limit_price=150)).status is S.NEW
    assert e.submit(order("2", BUY, LMT, 1500, limit_price=150)).status is S.REJECTED


def test_short_disallowed_by_policy():
    e = make_engine(policy=MarginPolicy(allow_short=False))
    st = e.submit(order("1", SELL, MKT, 1))
    assert "short" in st.reject_reason


# --- ticks e taxas ---


def test_tick_execution_market_and_limit_price_improvement():
    e = make_engine()
    e.submit(order("m", BUY, MKT, 10))
    e.submit(order("l", BUY, LMT, 10, limit_price=99, tif=TimeInForce.GTC))
    (f,) = e.on_tick(Tick(SYM, T0, D("100.5")))
    assert (f.order_id, f.price) == ("m", D("100.5"))
    (g,) = e.on_tick(Tick(SYM, T0 + timedelta(seconds=1), D("98.9")))
    assert (g.order_id, g.price) == ("l", D("98.9"))


def test_fees_charged_on_fills_with_first_fill_rule():
    e = make_engine(
        mark=30,
        model=ExecutionModel(max_participation=D("0.1")),
        fees=FeeSchedule(bps=D(10), per_order=D(1), minimum=D(5)),
    )
    e.submit(order("1", BUY, MKT, 200, tif=TimeInForce.GTC))
    (f1,) = e.on_bar(bar(0, 30, 31, 29, 30, v=1000))  # 100 @ 30 = 3000 -> 3 + 1 = 4 -> mín 5
    (f2,) = e.on_bar(bar(1, 30, 31, 29, 30, v=1000))  # 3000 -> 3
    assert (f1.fee, f2.fee) == (D(5), D(3))
    assert e.account.fees["BRL"] == D(8)
