"""OCO: quando uma ordem do grupo executa, as outras saem. Valores calculados à mão."""

from decimal import Decimal as D

from _util import LMT, SELL, STP, bar, make_engine, order
from market_holder.domain.models import OrderStatus


def _pair(engine):
    engine.submit(order("S", SELL, STP, 10, stop_price=95, oco="X"))
    engine.submit(order("T", SELL, LMT, 10, limit_price=110, oco="X"))


def test_stop_hit_cancels_target():
    e = make_engine()
    _pair(e)
    fills = e.on_bar(bar(1, 100, 105, 94, 96))  # mínima 94 toca o stop de 95
    assert [(f.order_id, f.price) for f in fills] == [("S", D("95"))]
    assert e.orders["T"].status is OrderStatus.CANCELED


def test_target_hit_cancels_stop():
    e = make_engine()
    _pair(e)
    fills = e.on_bar(bar(1, 100, 111, 99, 105))  # máxima 111 toca o alvo de 110
    assert [(f.order_id, f.price) for f in fills] == [("T", D("110"))]
    assert e.orders["S"].status is OrderStatus.CANCELED


def test_both_touched_in_one_bar_stop_wins():
    e = make_engine()
    _pair(e)
    fills = e.on_bar(bar(1, 100, 111, 94, 100))  # toca os dois: pior caso, o stop
    assert [f.order_id for f in fills] == ["S"]
    assert e.orders["T"].status is OrderStatus.CANCELED


def test_neither_touched_keeps_both_working():
    e = make_engine()
    _pair(e)
    assert e.on_bar(bar(1, 100, 105, 99, 101)) == []
    assert e.orders["S"].status.active and e.orders["T"].status.active


def test_orders_without_group_are_independent():
    e = make_engine()
    e.submit(order("A", SELL, LMT, 5, limit_price=105))
    e.submit(order("B", SELL, LMT, 5, limit_price=106))
    assert {f.order_id for f in e.on_bar(bar(1, 100, 111, 99, 100))} == {"A", "B"}
