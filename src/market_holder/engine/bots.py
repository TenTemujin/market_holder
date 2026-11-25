"""Estratégias automatizadas (Robôs / Bots), Estatísticas de Performance (Sharpe, Sortino, Drawdown)
e Cenários Históricos de Crise com feed de eventos macro no replay.

Módulo puro do motor: opera sobre barras, histórico e posições sem depender de web ou provedores.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from market_holder.domain.models import Bar, Side
from market_holder.domain.symbol import Symbol
from market_holder.engine.quant import rsi

BotStrategyKind = Literal["SMA_CROSS", "RSI_REV", "TURTLE_20", "VWAP_TREND"]


@dataclass(slots=True)
class BotConfig:
    id: str
    name: str
    strategy: BotStrategyKind
    symbol: Symbol
    qty: Decimal
    active: bool = True
    params: dict[str, float] = field(default_factory=dict)
    signals_count: int = 0
    last_signal: str = "IDLE"
    last_signal_ts: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "strategy": self.strategy,
            "symbol": str(self.symbol),
            "qty": str(self.qty),
            "active": self.active,
            "params": self.params,
            "signals_count": self.signals_count,
            "last_signal": self.last_signal,
            "last_signal_ts": self.last_signal_ts,
        }


def evaluate_bot_signal(
    bot: BotConfig,
    bars: list[Bar],
    current_pos_qty: Decimal,
) -> tuple[Side, Decimal, str] | None:
    """Avalia a última barra fechada e devolve (Side, qty, reason) ou None se sem sinal."""
    if not bot.active or len(bars) < 3:
        return None
    closes = [float(b.close) for b in bars]
    pos = float(current_pos_qty)
    target_q = float(bot.qty)

    if bot.strategy == "SMA_CROSS":
        fast_p = int(bot.params.get("fast", 5))
        slow_p = int(bot.params.get("slow", 15))
        if len(closes) < slow_p + 1:
            return None
        fast_now = sum(closes[-fast_p:]) / fast_p
        slow_now = sum(closes[-slow_p:]) / slow_p
        fast_prev = sum(closes[-fast_p - 1 : -1]) / fast_p
        slow_prev = sum(closes[-slow_p - 1 : -1]) / slow_p
        if fast_prev <= slow_prev and fast_now > slow_now and pos <= 0:
            order_q = Decimal(str(target_q + abs(pos))) if pos < 0 else bot.qty
            return (Side.BUY, order_q, f"Golden Cross SMA({fast_p})>{slow_p}")
        if fast_prev >= slow_prev and fast_now < slow_now and pos >= 0:
            order_q = Decimal(str(target_q + abs(pos))) if pos > 0 else bot.qty
            return (Side.SELL, order_q, f"Death Cross SMA({fast_p})<{slow_p}")

    elif bot.strategy == "RSI_REV":
        period = int(bot.params.get("period", 14))
        oversold = float(bot.params.get("oversold", 32.0))
        overbought = float(bot.params.get("overbought", 68.0))
        r = rsi(closes, period)
        if r is None:
            return None
        if r <= oversold and pos <= 0:
            order_q = Decimal(str(target_q + abs(pos))) if pos < 0 else bot.qty
            return (Side.BUY, order_q, f"RSI({period})={r:.1f} <= {oversold}")
        if r >= overbought and pos >= 0:
            order_q = Decimal(str(target_q + abs(pos))) if pos > 0 else bot.qty
            return (Side.SELL, order_q, f"RSI({period})={r:.1f} >= {overbought}")

    elif bot.strategy == "TURTLE_20":
        lookback = int(bot.params.get("lookback", 10))
        if len(bars) < lookback + 1:
            return None
        window = bars[-lookback - 1 : -1]
        hi = max(float(b.high) for b in window)
        lo = min(float(b.low) for b in window)
        last = closes[-1]
        if last > hi and pos <= 0:
            order_q = Decimal(str(target_q + abs(pos))) if pos < 0 else bot.qty
            return (Side.BUY, order_q, f"Breakout > {lookback}B High ({hi:.2f})")
        if last < lo and pos >= 0:
            order_q = Decimal(str(target_q + abs(pos))) if pos > 0 else bot.qty
            return (Side.SELL, order_q, f"Breakdown < {lookback}B Low ({lo:.2f})")

    elif bot.strategy == "VWAP_TREND":
        window = bars[-20:]
        cum_pv = sum(
            ((float(b.high) + float(b.low) + float(b.close)) / 3.0) * max(1.0, float(b.volume))
            for b in window
        )
        cum_v = sum(max(1.0, float(b.volume)) for b in window)
        vwap = cum_pv / cum_v if cum_v > 0 else closes[-1]
        prev_c = closes[-2]
        cur_c = closes[-1]
        if prev_c <= vwap and cur_c > vwap * 1.001 and pos <= 0:
            order_q = Decimal(str(target_q + abs(pos))) if pos < 0 else bot.qty
            return (Side.BUY, order_q, f"Crossed above VWAP ({vwap:.2f})")
        if prev_c >= vwap and cur_c < vwap * 0.999 and pos >= 0:
            order_q = Decimal(str(target_q + abs(pos))) if pos > 0 else bot.qty
            return (Side.SELL, order_q, f"Crossed below VWAP ({vwap:.2f})")

    return None


def compute_session_stats(
    equity_curve: list[dict[str, Any]],
    benchmark_bars: list[Bar],
    trade_pnls: list[float],
    periods_per_year: float = 252.0,
) -> dict[str, Any]:
    """Calcula Sharpe, Sortino, Max Drawdown, Calmar, Win Rate e curva comparativa Base-100."""
    if not equity_curve:
        return {
            "total_return_pct": 0.0,
            "benchmark_return_pct": 0.0,
            "alpha_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "calmar": 0.0,
            "max_drawdown_pct": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "trades_closed": 0,
            "curve": [],
        }

    eqs = [float(p["equity"]) for p in equity_curve]
    init_eq = eqs[0] if eqs[0] > 0 else 100000.0
    final_eq = eqs[-1]
    tot_ret = ((final_eq - init_eq) / init_eq) * 100.0

    # Benchmark return
    if len(benchmark_bars) >= 2 and float(benchmark_bars[0].open) > 0:
        b0 = float(benchmark_bars[0].open)
        b1 = float(benchmark_bars[-1].close)
        bench_ret = ((b1 - b0) / b0) * 100.0
    else:
        b0 = 1.0
        bench_ret = 0.0

    # Returns & Drawdown
    rets: list[float] = []
    peak = init_eq
    max_dd = 0.0
    for i, e in enumerate(eqs):
        if i > 0 and eqs[i - 1] > 0:
            rets.append((e - eqs[i - 1]) / eqs[i - 1])
        if e > peak:
            peak = e
        dd = ((peak - e) / peak) if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    max_dd_pct = max_dd * 100.0

    if len(rets) >= 2:
        mean_r = sum(rets) / len(rets)
        var = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
        std_r = math.sqrt(var)
        sharpe = (mean_r / std_r) * math.sqrt(periods_per_year) if std_r > 1e-12 else 0.0

        down_rets = [r for r in rets if r < 0]
        if down_rets:
            down_var = sum(r * r for r in down_rets) / len(rets)
            down_std = math.sqrt(down_var)
            sortino = (mean_r / down_std) * math.sqrt(periods_per_year) if down_std > 1e-12 else 0.0
        else:
            sortino = sharpe * 1.5 if sharpe > 0 else 0.0
    else:
        sharpe = 0.0
        sortino = 0.0

    calmar = (tot_ret / max_dd_pct) if max_dd_pct > 1e-6 else 0.0

    wins = [x for x in trade_pnls if x > 0]
    losses = [x for x in trade_pnls if x <= 0]
    win_rate = (len(wins) / len(trade_pnls) * 100.0) if trade_pnls else 0.0
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else (99.0 if wins else 0.0)

    # Downsample curve to max 120 points for lightweight SVG plotting
    step = max(1, len(equity_curve) // 120)
    sampled = equity_curve[::step]
    if sampled[-1] is not equity_curve[-1]:
        sampled.append(equity_curve[-1])

    curve_pts: list[dict[str, Any]] = []
    for idx, pt in enumerate(sampled):
        eq_norm = (float(pt["equity"]) / init_eq) * 100.0
        if benchmark_bars:
            b_idx = min(
                len(benchmark_bars) - 1,
                int((idx / max(1, len(sampled) - 1)) * (len(benchmark_bars) - 1)),
            )
            b_norm = (float(benchmark_bars[b_idx].close) / b0) * 100.0
        else:
            b_norm = 100.0
        curve_pts.append(
            {
                "ts": pt["ts"],
                "equity": round(float(pt["equity"]), 2),
                "eq_base100": round(eq_norm, 2),
                "bench_base100": round(b_norm, 2),
            }
        )

    return {
        "total_return_pct": round(tot_ret, 2),
        "benchmark_return_pct": round(bench_ret, 2),
        "alpha_pct": round(tot_ret - bench_ret, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "calmar": round(calmar, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "trades_closed": len(trade_pnls),
        "curve": curve_pts,
    }


# Cenários históricos prontos (Fase 6 do PLANO.md) com eventos macro datados
HISTORICAL_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "COVID_2020",
        "title": "2020 COVID-19 Global Liquidity Crash",
        "description": (
            "Circuit breakers on NYSE & B3, emergency Fed cuts to 0%, "
            "WTI crude oil collapse, and V-shaped liquidity rebound."
        ),
        "freq": "1d",
        "start": "2020-02-18",
        "end": "2020-04-15",
        "symbols": (
            "INDEX:US:GSPC:USD EQ:US:AAPL:USD EQ:B3:PETR4:BRL "
            "CMDTY:CME:GC:USD CRYPTO:BINANCE:BTCUSDT:USDT"
        ),
        "events": [
            {
                "date": "2020-02-24",
                "headline": "WHO warns of global pandemic risk; S&P 500 gaps down 3.3%",
            },
            {
                "date": "2020-03-03",
                "headline": "FOMC announces emergency 50 bps rate cut between scheduled meetings",
            },
            {
                "date": "2020-03-09",
                "headline": "Black Monday I: Saudi-Russia oil war; NYSE Level-1 Circuit Breaker",
            },
            {
                "date": "2020-03-12",
                "headline": "Black Thursday: Fed injects $1.5T repo; BTC -40%, B3 circuit breaker",
            },
            {
                "date": "2020-03-16",
                "headline": "Fed cuts rates to 0.00-0.25% & $700B QE; VIX hits record close 82.69",
            },
            {
                "date": "2020-03-23",
                "headline": "Fed announces unlimited QE and corporate bond facilities — bottom",
            },
        ],
    },
    {
        "id": "GFC_2008",
        "title": "2008 Lehman Brothers & Subprime Crisis",
        "description": (
            "Lehman bankruptcy, AIG bailout, TARP vote rejection in Congress, "
            "and historic banking volatility."
        ),
        "freq": "1d",
        "start": "2008-09-02",
        "end": "2008-10-31",
        "symbols": "INDEX:US:GSPC:USD EQ:US:JPM:USD EQ:US:GS:USD EQ:US:BAC:USD CMDTY:CME:GC:USD",
        "events": [
            {
                "date": "2008-09-07",
                "headline": "US Treasury places Fannie Mae and Freddie Mac into conservatorship",
            },
            {
                "date": "2008-09-15",
                "headline": "Lehman Brothers files for Chapter 11 ($613B debt); Merrill to BofA",
            },
            {
                "date": "2008-09-16",
                "headline": "Reserve Primary Fund breaks the buck; Fed rescues AIG with $85B line",
            },
            {
                "date": "2008-09-19",
                "headline": "SEC imposes temporary ban on short-selling across 799 financial names",
            },
            {
                "date": "2008-09-29",
                "headline": "US House rejects $700B TARP bailout bill; S&P 500 plunges 8.8%",
            },
            {
                "date": "2008-10-03",
                "headline": "Emergency Economic Stabilization Act (TARP) signed into law",
            },
            {
                "date": "2008-10-13",
                "headline": "G7 & US Treasury announce direct equity injections into major banks",
            },
        ],
    },
    {
        "id": "INFLATION_2022",
        "title": "2022 Fed 75bps Tightening Shock & Crypto/Tech Rout",
        "description": (
            "US CPI hits 40-year peak (9.1%), aggressive 75 bps FOMC hikes, "
            "2s10s curve inversion, and tech/crypto deleveraging."
        ),
        "freq": "1d",
        "start": "2022-05-02",
        "end": "2022-07-01",
        "symbols": (
            "INDEX:US:IXIC:USD EQ:US:NVDA:USD EQ:US:META:USD "
            "CRYPTO:BINANCE:BTCUSDT:USDT CRYPTO:BINANCE:ETHUSDT:USDT"
        ),
        "events": [
            {
                "date": "2022-05-04",
                "headline": "FOMC hikes rates by 50 bps and announces Quantitative Tightening (QT)",
            },
            {
                "date": "2022-05-09",
                "headline": "UST/Luna algorithmic stablecoin de-pegs, triggering crypto contagion",
            },
            {
                "date": "2022-05-11",
                "headline": "US April CPI prints 8.3% YoY (above 8.1% consensus); Nasdaq tumbles",
            },
            {
                "date": "2022-06-10",
                "headline": "US May CPI surprises at 8.6% YoY; 2Y Treasury yield surges 25 bps",
            },
            {
                "date": "2022-06-13",
                "headline": "Crypto lender Celsius freezes withdrawals; BTC breaks below $23,000",
            },
            {
                "date": "2022-06-15",
                "headline": "FOMC delivers first 75 bps rate hike since 1994 to combat inflation",
            },
        ],
    },
    {
        "id": "BRAZIL_2017",
        "title": "2017 Brazil 'Joesley Day' Circuit Breaker",
        "description": (
            "Sudden political shock in Brazil: Ibovespa triggers 10% circuit breaker, "
            "USD/BRL spikes 8%, and B3 blue-chips gap down."
        ),
        "freq": "1d",
        "start": "2017-05-02",
        "end": "2017-06-15",
        "symbols": (
            "EQ:B3:PETR4:BRL EQ:B3:VALE3:BRL EQ:B3:ITUB4:BRL "
            "EQ:B3:BBDC4:BRL FX:YAHOO:USDBRL:BRL"
        ),
        "events": [
            {
                "date": "2017-05-17",
                "headline": "Evening leak of recordings shakes Brasília after B3 market close",
            },
            {
                "date": "2017-05-18",
                "headline": "Joesley Day: B3 circuit breaker at -10%; PETR4/ITUB4 plunge, BRL -8%",
            },
            {
                "date": "2017-05-19",
                "headline": "BCB intervenes with FX swap auctions to stabilize BRL liquidity",
            },
            {
                "date": "2017-05-31",
                "headline": "COPOM cuts Selic rate by 100 bps to 10.25% amid political volatility",
            },
        ],
    },
]


def due_macro_events(
    scenario_id: str | None,
    current_ts: datetime,
    delivered_dates: set[str],
) -> list[dict[str, str]]:
    """Devolve eventos históricos do cenário cuja data foi alcançada ou cruzada pelo relógio."""
    if not scenario_id:
        return []
    scen = next((s for s in HISTORICAL_SCENARIOS if s["id"] == scenario_id), None)
    if not scen:
        return []
    cur_date = current_ts.strftime("%Y-%m-%d")
    out: list[dict[str, str]] = []
    for ev in scen["events"]:
        d = ev["date"]
        if d <= cur_date and d not in delivered_dates:
            delivered_dates.add(d)
            out.append({"date": d, "headline": ev["headline"], "scenario": scen["id"]})
    return out
