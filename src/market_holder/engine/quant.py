"""Ferramentas quantitativas e de risco: Screener (EQS), Correlação & Beta (CORR) e Monte Carlo.

Módulo puro do motor: opera apenas sobre históricos de barras e execuções (Fills).
"""

from __future__ import annotations

import math
import random
from typing import Any

from market_holder.domain.models import Bar, Fill, Side
from market_holder.domain.symbol import Symbol


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Relative Strength Index (Wilder)."""
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def screener_metrics(
    history: dict[Symbol, list[Bar]], marks: dict[Symbol, Any]
) -> list[dict[str, Any]]:
    """Calcula indicadores dinâmicos para o Equity Screener (EQS) sem lookahead."""
    rows: list[dict[str, Any]] = []
    for sym, bars in history.items():
        if not bars:
            last = float(marks.get(sym, 0))
            if last <= 0:
                continue
            rows.append(
                {
                    "symbol": str(sym),
                    "last": last,
                    "chg_pct": 0.0,
                    "rvol": 1.0,
                    "rsi14": None,
                    "high_20": last,
                    "low_20": last,
                    "breakout": "INSIDE",
                    "vol_annual": 0.0,
                    "bars": 0,
                }
            )
            continue
        closes = [float(b.close) for b in bars]
        vols = [float(b.volume) for b in bars]
        last = float(marks.get(sym, closes[-1]))
        prev = closes[-2] if len(closes) > 1 else float(bars[-1].open)
        chg_pct = ((last - prev) / prev * 100.0) if prev > 0 else 0.0

        # Relative Volume contra média das últimas 20 barras
        tail_vols = vols[-20:]
        avg_vol = sum(tail_vols) / len(tail_vols) if tail_vols else 0.0
        rvol = (vols[-1] / avg_vol) if avg_vol > 0 else 1.0

        # Rompimento de máxima/mínima de 20 barras
        window = bars[-20:]
        prev_window = bars[-21:-1] if len(bars) > 1 else window
        high_20 = max(float(b.high) for b in prev_window)
        low_20 = min(float(b.low) for b in prev_window)
        if len(bars) > 1 and last >= high_20:
            breakout = "HIGH_BREAK"
        elif len(bars) > 1 and last <= low_20:
            breakout = "LOW_BREAK"
        else:
            breakout = "INSIDE"

        # Volatilidade realizada simples
        rets = [
            math.log(closes[i] / closes[i - 1])
            for i in range(max(1, len(closes) - 30), len(closes))
            if closes[i] > 0 and closes[i - 1] > 0
        ]
        if len(rets) >= 2:
            m = sum(rets) / len(rets)
            v = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
            vol_ann = math.sqrt(v * 252.0) * 100.0
        else:
            vol_ann = 0.0

        rows.append(
            {
                "symbol": str(sym),
                "last": round(last, 6),
                "chg_pct": round(chg_pct, 2),
                "rvol": round(rvol, 2),
                "rsi14": rsi(closes, 14),
                "high_20": round(max(float(b.high) for b in window), 6),
                "low_20": round(min(float(b.low) for b in window), 6),
                "breakout": breakout,
                "vol_annual": round(vol_ann, 2),
                "bars": len(bars),
            }
        )
    rows.sort(key=lambda r: abs(r["chg_pct"]), reverse=True)
    return rows


def _returns(bars: list[Bar]) -> list[float]:
    closes = [float(b.close) for b in bars]
    out: list[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            out.append((closes[i] - closes[i - 1]) / closes[i - 1])
    return out


def pearson_corr(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    x = xs[-n:]
    y = ys[-n:]
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=False))
    den_x = sum((a - mx) ** 2 for a in x)
    den_y = sum((b - my) ** 2 for b in y)
    den = math.sqrt(den_x * den_y)
    if den <= 1e-12:
        return 0.0
    return max(-1.0, min(1.0, num / den))


def calc_beta(asset_rets: list[float], bench_rets: list[float]) -> float:
    n = min(len(asset_rets), len(bench_rets))
    if n < 2:
        return 1.0
    a = asset_rets[-n:]
    b = bench_rets[-n:]
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=False)) / (n - 1)
    var_b = sum((y - mb) ** 2 for y in b) / (n - 1)
    return round(cov / var_b, 3) if var_b > 1e-12 else 1.0


def correlation_matrix(
    history: dict[Symbol, list[Bar]], benchmark: Symbol | None = None
) -> dict[str, Any]:
    """Matriz de correlação cruzada e Beta contra o benchmark (1º símbolo ou índice)."""
    symbols = list(history.keys())
    rets = {s: _returns(history[s]) for s in symbols}
    bench = benchmark if (benchmark in rets) else (symbols[0] if symbols else None)
    bench_rets = rets.get(bench, []) if bench else []

    matrix: list[list[float]] = []
    betas: dict[str, float] = {}
    for s1 in symbols:
        row: list[float] = []
        for s2 in symbols:
            if s1 == s2:
                row.append(1.0)
            else:
                row.append(round(pearson_corr(rets[s1], rets[s2]), 3))
        matrix.append(row)
        betas[str(s1)] = 1.0 if s1 == bench else calc_beta(rets[s1], bench_rets)

    return {
        "symbols": [str(s) for s in symbols],
        "benchmark": str(bench) if bench else None,
        "matrix": matrix,
        "betas": betas,
    }


def extract_round_trip_pnls(fills: list[Fill]) -> list[float]:
    """Extrai o P&L líquido de cada redução/fechamento de posição do histórico de Fills."""
    pos_qty: dict[Symbol, float] = {}
    pos_avg: dict[Symbol, float] = {}
    trades: list[float] = []
    for f in fills:
        qty = float(f.qty)
        px = float(f.price)
        fee = float(f.fee)
        sign = 1.0 if f.side is Side.BUY else -1.0
        cur_q = pos_qty.get(f.symbol, 0.0)
        cur_avg = pos_avg.get(f.symbol, 0.0)
        signed = sign * qty
        if abs(cur_q) < 1e-9 or (cur_q > 0) == (signed > 0):
            total = cur_q + signed
            pos_avg[f.symbol] = (cur_avg * abs(cur_q) + px * qty) / abs(total)
            pos_qty[f.symbol] = total
        else:
            closing = min(abs(cur_q), qty)
            pnl = closing * (px - cur_avg) * (1.0 if cur_q > 0 else -1.0) - fee
            trades.append(round(pnl, 4))
            rem = cur_q + signed
            if abs(rem) < 1e-9:
                pos_avg[f.symbol] = 0.0
                pos_qty[f.symbol] = 0.0
            elif (rem > 0) != (cur_q > 0):
                pos_avg[f.symbol] = px
                pos_qty[f.symbol] = rem
            else:
                pos_qty[f.symbol] = rem
    return trades


def monte_carlo_simulation(
    trade_pnls: list[float],
    initial_equity: float = 100000.0,
    paths: int = 500,
    horizon_trades: int = 50,
    ruin_drawdown_pct: float = 0.50,
    seed: int = 42,
) -> dict[str, Any]:
    """Simula cenários via bootstrap dos trades realizados (ou sintéticos se < 2 trades)."""
    rng = random.Random(seed)
    sample = list(trade_pnls)
    synthetic = False
    if len(sample) < 2:
        # Sem trades fechados suficientes: usa distribuição de referência (+/- 1% do capital)
        synthetic = True
        step = initial_equity * 0.008
        sample = [step * 1.15, -step, step * 0.9, -step * 0.85, step * 1.4, -step * 1.1]

    wins = [x for x in sample if x > 0]
    losses = [x for x in sample if x <= 0]
    win_rate = len(wins) / len(sample) if sample else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else 0.0

    final_equities: list[float] = []
    max_drawdowns: list[float] = []
    ruin_count = 0
    fan_paths: list[list[float]] = []

    for p in range(paths):
        eq = initial_equity
        peak = initial_equity
        max_dd = 0.0
        ruined = False
        curve = [round(eq, 2)]
        for _ in range(horizon_trades):
            pnl = rng.choice(sample)
            eq = max(0.0, eq + pnl)
            if eq > peak:
                peak = eq
            dd = ((peak - eq) / peak) if peak > 0 else 1.0
            if dd > max_dd:
                max_dd = dd
            if dd >= ruin_drawdown_pct or eq <= 0:
                ruined = True
            curve.append(round(eq, 2))
        if ruined:
            ruin_count += 1
        final_equities.append(eq)
        max_drawdowns.append(max_dd * 100.0)
        if p < 25:
            fan_paths.append(curve)

    final_equities.sort()
    max_drawdowns.sort()

    def pct(arr: list[float], q: float) -> float:
        if not arr:
            return 0.0
        idx = min(len(arr) - 1, max(0, int(q * (len(arr) - 1))))
        return round(arr[idx], 2)

    return {
        "synthetic": synthetic,
        "sample_size": len(trade_pnls),
        "paths": paths,
        "horizon_trades": horizon_trades,
        "initial_equity": round(initial_equity, 2),
        "win_rate": round(win_rate * 100.0, 2),
        "profit_factor": round(profit_factor, 2),
        "expectancy": round(sum(sample) / len(sample), 2),
        "prob_ruin_pct": round((ruin_count / paths) * 100.0, 2),
        "equity_p5": pct(final_equities, 0.05),
        "equity_p50": pct(final_equities, 0.50),
        "equity_p95": pct(final_equities, 0.95),
        "max_dd_p50_pct": pct(max_drawdowns, 0.50),
        "max_dd_p95_pct": pct(max_drawdowns, 0.95),
        "fan_paths": fan_paths,
    }
