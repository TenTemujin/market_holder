"""Conferência ao vivo (pytest --live). Valores esperados vêm do payload bruto das fontes,
capturado em 2026-11-24 (docs/planning/findings.md, F2). Valida URL, paginação, datas e
conversão de unidades de ponta a ponta; a correção da própria fonte vem do cruzamento
PTAX (BCB) x DEXBZUS (FRED)."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from market_holder.domain.models import Freq
from market_holder.domain.symbol import Symbol
from market_holder.providers.bcb import BcbProvider
from market_holder.providers.binance import BinanceProvider
from market_holder.providers.fred import FredProvider
from market_holder.providers.tesouro import TesouroProvider
from market_holder.providers.yahoo import YahooProvider

pytestmark = pytest.mark.live
J = lambda d: datetime(2024, 1, d, tzinfo=UTC)  # noqa: E731


def hist(provider, sym, start, end, freq=Freq.D1):
    return asyncio.run(provider.history(Symbol.parse(sym), start, end, freq))


def test_binance_btcusdt_daily():
    bars = hist(BinanceProvider(), "CRYPTO:BINANCE:BTCUSDT", J(1), J(4))
    assert [(b.open, b.close) for b in bars] == [
        (D("42283.58"), D("44179.55")), (D("44179.55"), D("44946.91")),
        (D("44946.91"), D("42845.23"))]


def test_bcb_selic_meta_and_ipca():
    (meta,) = hist(BcbProvider(), "RATE:BCB:SELIC_META", J(2), J(3))
    assert meta.close == D("11.75")
    ipca = hist(BcbProvider(), "RATE:BCB:IPCA", J(1), datetime(2024, 4, 1, tzinfo=UTC))
    assert [b.close for b in ipca] == [D("0.42"), D("0.83"), D("0.16")]


def test_bcb_ptax_close_and_crosscheck_with_fred():
    ptax = hist(BcbProvider(), "FX:BCB:USDBRL", J(2), J(5))
    assert [b.close for b in ptax] == [D("4.8916"), D("4.9212"), D("4.9188")]
    fed = hist(FredProvider(), "FX:FRED:DEXBZUS", J(2), J(5))
    assert [b.close for b in fed] == [D("4.8943"), D("4.9239"), D("4.9143")]
    for a, b in zip(ptax, fed, strict=True):  # fontes independentes: diferença < 0,2%
        assert abs(a.close - b.close) / b.close < D("0.002")


def test_tesouro_selic_2027_pu():
    bars = hist(TesouroProvider(), "RATE:TESOURO:SELIC-20270301", J(2), J(5))
    assert [b.close for b in bars] == [D("14216.58"), D("14222.96"), D("14229.92")]


def test_yahoo_aapl_open():
    bars = hist(YahooProvider(), "EQ:US:AAPL", J(2), J(5))
    assert [b.open for b in bars] == [D("187.15"), D("184.22"), D("182.15")]


def test_replay_of_a_real_btcusdt_day_is_deterministic():
    """Critério de aceite da Fase 3: 1 dia de BTCUSDT em barras de 1 min, duas rodadas."""
    from test_session import run_script

    bars = hist(BinanceProvider(), "CRYPTO:BINANCE:BTCUSDT", J(2), J(3), Freq.M1)
    assert len(bars) == 1440
    f1, snap1 = run_script(bars)
    f2, snap2 = run_script(bars)
    assert f1 and f1 == f2 and snap1 == snap2
