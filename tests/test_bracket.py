"""Bracket (entrada + stop + alvo em OCO) e saídas da posição. Valores calculados à mão."""

from decimal import Decimal as D

import pytest

from _util import SYM, T0, bar, make_engine
from market_holder.domain.models import OrderStatus, OrderType, Side
from market_holder.session import Session

MKT, LMT = OrderType.MARKET, OrderType.LIMIT


def make(bars):
    return Session(make_engine(), bars, T0)


def realized(s):
    return sum(s.engine.account.realized.values())


def test_bracket_target_hit_closes_with_profit_and_cancels_stop():
    s = make([bar(0, 100, 101, 99, 100), bar(1, 100, 111, 99, 105)])
    s.place_bracket(SYM, Side.BUY, D(10), MKT, D(95), D(110))
    s.step()  # barra 0: entrada a 100; saídas armadas
    exits = [st for st in s.engine.orders.values() if st.order.oco]
    assert {st.order.type for st in exits} == {OrderType.STOP, OrderType.LIMIT}
    assert all(st.order.qty == 10 and st.order.side is Side.SELL for st in exits)
    s.step()  # barra 1: máxima 111 toca o alvo de 110
    assert realized(s) == D(100)  # (110 - 100) * 10
    st = {st.order.type: st.status for st in exits}
    assert st[OrderType.LIMIT] is OrderStatus.FILLED and st[OrderType.STOP] is OrderStatus.CANCELED
    assert s.engine.account.portfolio.positions[SYM].qty == 0


def test_bracket_stop_hit_closes_with_loss():
    s = make([bar(0, 100, 101, 99, 100), bar(1, 100, 105, 94, 96)])
    s.place_bracket(SYM, Side.BUY, D(10), MKT, D(95), D(110))
    s.step()
    s.step()
    assert realized(s) == D(-50)  # (95 - 100) * 10


def test_short_bracket_mirrors_sides():
    s = make([bar(0, 100, 101, 99, 100), bar(1, 100, 106, 89, 95)])
    s.place_bracket(SYM, Side.SELL, D(10), MKT, D(105), D(90))  # venda: alvo 90, stop 105
    s.step()
    s.step()  # mínima 89 toca o alvo de 90 (compra para fechar), máxima 106 toca o stop de 105
    assert realized(s) == D(-50)  # os dois cabem na barra: o stop vence, (100 - 105) * 10


def test_invalid_bracket_prices_are_rejected():
    s = make([bar(0, 100, 101, 99, 100)])
    with pytest.raises(ValueError, match="bracket inválido"):
        s.place_bracket(SYM, Side.BUY, D(1), MKT, D(105), D(110))  # stop acima da entrada
    with pytest.raises(ValueError, match="bracket inválido"):
        s.place_bracket(SYM, Side.SELL, D(1), MKT, D(95), D(90))  # stop abaixo da entrada


def test_canceled_entry_arms_no_exits():
    s = make([bar(0, 100, 101, 99, 100)])
    st = s.place_bracket(SYM, Side.BUY, D(10), LMT, D(85), D(110), entry_limit=D(90))
    s.cancel(st.order.id)
    s.step()
    assert len(s.engine.orders) == 1 and not s._brackets


def test_place_exits_for_open_position_share_one_oco_group():
    s = make([bar(0, 100, 101, 99, 100), bar(1, 100, 101, 99, 100), bar(2, 100, 112, 99, 105)])
    s.place(SYM, Side.BUY, MKT, D(10))
    s.step()  # posição de 10 a 100
    a = s.place_exits(SYM, D(95), None)
    b = s.place_exits(SYM, None, D(110))  # reaproveita o grupo do stop
    assert a[0].order.oco == b[0].order.oco is not None
    s.step()  # barra 1 não toca nada
    s.step()  # barra 2: alvo
    assert realized(s) == D(100)
    assert a[0].status is OrderStatus.CANCELED


def test_place_exits_validations():
    s = make([bar(0, 100, 101, 99, 100)])
    with pytest.raises(ValueError, match="sem posição"):
        s.place_exits(SYM, D(95), None)
    s.place(SYM, Side.BUY, MKT, D(1))
    s.step()
    with pytest.raises(ValueError, match="lado errado"):
        s.place_exits(SYM, D(105), None)  # stop de posição comprada acima do preço
    with pytest.raises(ValueError, match="informe"):
        s.place_exits(SYM, None, None)
