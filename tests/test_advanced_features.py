"""Testes calculados à mão para os novos módulos do motor:
- Short selling com locate_limit, borrow_rate_annual e cobrança na virada de sessão
- Liquidação forçada automática em Margin Call (auto_liquidate)
- Eventos corporativos (Split, Grupamento e Dividendo em caixa)
- Ordem Iceberg (display_qty) e Algoritmos TWAP / VWAP na Session
- Precificação Black-Scholes, paridade Put-Call, Gregas e Volatilidade Implícita
- Screener (EQS), Correlação & Beta (CORR) e Simulador de Monte Carlo (MC)
"""

from datetime import timedelta
from decimal import Decimal as D

from _util import BUY, LMT, MKT, SELL, SYM, T0, bar, make_engine, order
from market_holder.domain.models import Bar, Freq, Instrument, Order, OrderStatus, TimeInForce
from market_holder.domain.symbol import Symbol
from market_holder.engine.account import Account, MarginPolicy
from market_holder.engine.options import (
    black_scholes,
    implied_volatility,
    option_chain,
    realized_volatility,
)
from market_holder.engine.quant import (
    correlation_matrix,
    extract_round_trip_pnls,
    monte_carlo_simulation,
     rsi,
    screener_metrics,
)
from market_holder.session import Session


def test_locate_limit_rejects_excess_short_but_allows_within_cap():
    inst = Instrument(SYM, "BRL", locate_limit=D(100))
    e = make_engine(inst=inst)
    assert e.submit(order("1", SELL, MKT, 100)).status is OrderStatus.NEW
    e.on_bar(bar(0, 50, 51, 49, 50))
    assert e.account.portfolio.positions[SYM].qty == D(-100)
    # Tentar vender mais 10 ultrapassa locate_limit=100
    rej = e.submit(order("2", SELL, MKT, 10, ts=T0 + timedelta(minutes=1)))
    assert rej.status is OrderStatus.REJECTED
    assert "locate" in rej.reject_reason
    # Recomprar para cobrir short sempre passa
    cov = e.submit(order("3", BUY, MKT, 40, ts=T0 + timedelta(minutes=1)))
    assert cov.status is OrderStatus.NEW


def test_borrow_fee_charged_automatically_on_session_rollover():
    # Taxa anual de 25.2% -> 0.1% (0.001) por dia útil (252 dias)
    inst = Instrument(SYM, "BRL", borrow_rate_annual=D("0.252"))
    e = make_engine(inst=inst, cash=100000)
    e.submit(order("1", SELL, MKT, 100))
    e.on_bar(bar(0, 100, 101, 99, 100))  # vendido em 100 @ 100 = notional 10000
    assert e.account.portfolio.cash["BRL"] == D(110000)
    # Mesma sessão (mesmo dia UTC): zero aluguel cobrado
    e.on_bar(bar(1, 100, 101, 99, 100))
    assert e.account.borrow_fees.get("BRL", D(0)) == D(0)
    # Virada de dia UTC -> cobra 1 dia de aluguel sobre mark=100: 10000 * 0.252 / 252 = 10 BRL
    next_day = Bar(SYM, T0 + timedelta(days=1), Freq.M1, D(100), D(101), D(99), D(100))
    e.on_bar(next_day)
    assert e.account.borrow_fees["BRL"] == D("10")
    assert e.account.portfolio.cash["BRL"] == D(109990)


def test_auto_liquidation_on_margin_call():
    policy = MarginPolicy(
        initial_rate=D("0.5"), maintenance_rate=D("0.25"), auto_liquidate=True
    )
    e = make_engine(cash=100000, policy=policy)
    e.submit(order("1", BUY, MKT, 1000))
    e.on_bar(bar(0, 150, 151, 149, 150))  # comprou 1000 @ 150 -> caixa -50000
    assert e.account.portfolio.positions[SYM].qty == D(1000)
    # Queda para 66 -> equity = -50000 + 66000 = 16000 < manutenção (66000 * 0.25 = 16500)
    fills = e.on_bar(bar(1, 70, 70, 65, 66))
    assert len(fills) == 1
    assert fills[0].order_id == "LIQ1"
    assert fills[0].side == SELL
    assert fills[0].qty == D(1000)
    assert fills[0].price == D(66)
    assert e.account.portfolio.positions[SYM].qty == D(0)
    assert not e.account.margin_status().margin_call


def test_corporate_actions_split_and_dividend():
    a = Account("BRL", {"BRL": D(10000)}, {SYM: Instrument(SYM, "BRL")})
    from market_holder.domain.models import Fill

    a.apply_fill(Fill("1", SYM, BUY, D(100), D(40), T0))
    a.marks[SYM] = D(40)
    eq_before = a.equity()
    # Split 2:1 -> 200 ações a preço médio 20 e mark 20, equity inalterado
    a.apply_split(SYM, D(2))
    pos = a.portfolio.positions[SYM]
    assert (pos.qty, pos.avg_price, a.marks[SYM]) == (D(200), D(20), D(20))
    assert a.equity() == eq_before
    # Dividendo de 1.50 por ação -> 200 * 1.50 = 300 em caixa
    paid = a.apply_dividend(SYM, D("1.50"))
    assert paid == D(300)
    assert a.portfolio.cash["BRL"] == D(6000) + D(300)


def test_iceberg_order_executes_only_display_qty_per_bar():
    e = make_engine()
    ice = Order(
        "ice1",
        SYM,
        BUY,
        LMT,
        D(300),
        T0,
        limit_price=D(100),
        tif=TimeInForce.GTC,
        display_qty=D(100),
    )
    st = e.submit(ice)
    (f1,) = e.on_bar(bar(0, 100, 101, 99, 100, v=5000))
    assert (f1.qty, st.filled_qty, st.status) == (D(100), D(100), OrderStatus.PARTIALLY_FILLED)
    (f2,) = e.on_bar(bar(1, 100, 101, 99, 100, v=5000))
    assert (f2.qty, st.filled_qty, st.status) == (D(100), D(200), OrderStatus.PARTIALLY_FILLED)
    (f3,) = e.on_bar(bar(2, 100, 101, 99, 100, v=5000))
    assert (f3.qty, st.filled_qty, st.status) == (D(100), D(300), OrderStatus.FILLED)


def test_twap_algo_slices_and_headless_fast_forward():
    e = make_engine()
    bars = [bar(i, 100, 101, 99, 100, v=1000) for i in range(6)]
    s = Session(e, bars, T0)
    task = s.place_algo(SYM, BUY, "TWAP", D(300), slices=3)
    assert task.filled_slices == 1
    assert task.executed_qty == D(100)
    fills = s.fast_forward(steps=10)
    assert len(fills) == 3
    assert e.account.portfolio.positions[SYM].qty == D(300)
    assert not task.active


def test_black_scholes_put_call_parity_and_iv_inversion():
    import math

    spot, strike, days, r, iv = 100.0, 100.0, 365, 0.05, 0.20
    call = black_scholes(spot, strike, days, r, iv, "CALL")
    put = black_scholes(spot, strike, days, r, iv, "PUT")
    # Valor de referência clássico para S=100, K=100, T=1, r=5%, sigma=20%:
    # d1 = (0.05 + 0.02)/0.20 = 0.35, d2 = 0.15 -> Call ~= 10.4506, Put ~= 5.5735
    assert abs(call.price - 10.4506) < 0.01
    assert abs(put.price - 5.5735) < 0.01
    # Paridade Put-Call: C - P = S - K * e^(-rT)
    lhs = call.price - put.price
    rhs = spot - strike * math.exp(-r * 1.0)
    assert abs(lhs - rhs) < 0.01
    # Inversão de IV
    recovered_iv = implied_volatility(call.price, spot, strike, days, r, "CALL")
    assert abs(recovered_iv - iv) < 1e-3
    chain = option_chain(100.0, 30, 0.05, 0.25, strikes_each_side=3)
    assert len(chain) == 7
    assert chain[3]["strike"] == 100.0


def test_quant_screener_correlation_and_monte_carlo():
    s2 = Symbol.parse("EQ:B3:VALE3")
    b1 = [bar(i, 100 + i, 102 + i, 99 + i, 101 + i, v=1000 + i * 100) for i in range(20)]
    b2 = [
        Bar(
            s2,
            T0 + timedelta(minutes=i),
            Freq.M1,
            D(50 + i),
            D(52 + i),
            D(49 + i),
            D(51 + i),
            D(500),
        )
        for i in range(20)
    ]
    hist = {SYM: b1, s2: b2}
    marks = {SYM: D(120), s2: D(70)}

    rows = screener_metrics(hist, marks)
    assert len(rows) == 2
    assert rows[0]["rsi14"] == 100.0  # série monotônica crescente

    corr = correlation_matrix(hist, SYM)
    assert corr["symbols"] == [str(SYM), str(s2)]
    assert corr["matrix"][0][0] == 1.0
    assert corr["matrix"][0][1] > 0.95

    from market_holder.domain.models import Fill

    fills = [
        Fill("1", SYM, BUY, D(10), D(100), T0),
        Fill("2", SYM, SELL, D(10), D(110), T0 + timedelta(minutes=1)),
        Fill("3", SYM, BUY, D(10), D(110), T0 + timedelta(minutes=2)),
        Fill("4", SYM, SELL, D(10), D(105), T0 + timedelta(minutes=3)),
    ]
    pnls = extract_round_trip_pnls(fills)
    assert pnls == [100.0, -50.0]
    mc = monte_carlo_simulation(pnls, initial_equity=10000.0, paths=100, horizon_trades=20)
    assert not mc["synthetic"]
    assert mc["win_rate"] == 50.0
    assert len(mc["fan_paths"]) == 25
    assert realized_volatility([100.0, 101.0, 99.5, 102.0]) > 0
    assert rsi([float(100 + i) for i in range(20)], 14) == 100.0
