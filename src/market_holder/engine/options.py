"""Precificação de opções europeias via Black-Scholes, gregas e geração de cadeia sintética.

Módulo puro do motor: sem dependência de web ou provedores externos.
Convenções:
- spot (S), strike (K), taxa livre de risco anual (r), volatilidade anualizada (sigma),
  tempo até o vencimento em anos (T = days / 365).
- Theta é reportado por dia corrido (dV/dt / 365).
- Vega é reportado por 1 ponto percentual de vol (dV/dsigma / 100).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

OptionRight = Literal["CALL", "PUT"]
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    return _INV_SQRT_2PI * math.exp(-0.5 * x * x)


@dataclass(frozen=True, slots=True)
class OptionQuote:
    right: OptionRight
    strike: float
    expiry_days: int
    spot: float
    iv: float
    rate: float
    price: float
    bid: float
    ask: float
    intrinsic: float
    extrinsic: float
    delta: float
    gamma: float
    theta: float  # por dia
    vega: float  # por 1% de vol
    rho: float  # por 1% de taxa
    itm: bool


def black_scholes(
    spot: float,
    strike: float,
    expiry_days: int,
    rate: float,
    iv: float,
    right: OptionRight = "CALL",
) -> OptionQuote:
    if spot <= 0 or strike <= 0:
        raise ValueError("spot e strike devem ser positivos")
    if iv <= 0:
        raise ValueError("volatilidade implícita deve ser positiva")

    t = max(expiry_days, 0) / 365.0
    intrinsic = max(0.0, spot - strike) if right == "CALL" else max(0.0, strike - spot)
    itm = (spot > strike) if right == "CALL" else (spot < strike)

    if t <= 1e-9:
        if right == "CALL":
            delta = 1.0 if spot > strike else 0.0
        else:
            delta = -1.0 if spot < strike else 0.0
        half = max(0.01, intrinsic * 0.005)
        return OptionQuote(
            right=right,
            strike=round(strike, 4),
            expiry_days=expiry_days,
            spot=round(spot, 4),
            iv=round(iv, 6),
            rate=round(rate, 6),
            price=round(intrinsic, 4),
            bid=round(max(0.0, intrinsic - half), 4),
            ask=round(intrinsic + half, 4),
            intrinsic=round(intrinsic, 4),
            extrinsic=0.0,
            delta=round(delta, 4),
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            rho=0.0,
            itm=itm,
        )

    sqrt_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * t) / (iv * sqrt_t)
    d2 = d1 - iv * sqrt_t
    df = math.exp(-rate * t)
    pdf_d1 = norm_pdf(d1)

    if right == "CALL":
        nd1 = norm_cdf(d1)
        nd2 = norm_cdf(d2)
        price = spot * nd1 - strike * df * nd2
        delta = nd1
        theta_annual = -(spot * pdf_d1 * iv) / (2.0 * sqrt_t) - rate * strike * df * nd2
        rho = strike * t * df * nd2 / 100.0
    else:
        n_minus_d1 = norm_cdf(-d1)
        n_minus_d2 = norm_cdf(-d2)
        price = strike * df * n_minus_d2 - spot * n_minus_d1
        delta = nd1 - 1.0 if (nd1 := norm_cdf(d1)) is not None else 0.0
        theta_annual = -(spot * pdf_d1 * iv) / (2.0 * sqrt_t) + rate * strike * df * n_minus_d2
        rho = -strike * t * df * n_minus_d2 / 100.0

    gamma = pdf_d1 / (spot * iv * sqrt_t)
    vega = (spot * pdf_d1 * sqrt_t) / 100.0
    theta_daily = theta_annual / 365.0
    extrinsic = max(0.0, price - intrinsic)
    half_spread = max(0.01, price * 0.01)

    return OptionQuote(
        right=right,
        strike=round(strike, 4),
        expiry_days=expiry_days,
        spot=round(spot, 4),
        iv=round(iv, 6),
        rate=round(rate, 6),
        price=round(price, 4),
        bid=round(max(0.01, price - half_spread), 4),
        ask=round(price + half_spread, 4),
        intrinsic=round(intrinsic, 4),
        extrinsic=round(extrinsic, 4),
        delta=round(delta, 4),
        gamma=round(gamma, 6),
        theta=round(theta_daily, 4),
        vega=round(vega, 4),
        rho=round(rho, 4),
        itm=itm,
    )


def implied_volatility(
    target_price: float,
    spot: float,
    strike: float,
    expiry_days: int,
    rate: float,
    right: OptionRight = "CALL",
) -> float:
    """Inverte Black-Scholes via bisseção + Newton-Raphson para achar a IV dado o prêmio."""
    if expiry_days <= 0 or target_price <= 0:
        return 0.0
    lo, hi = 1e-4, 5.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        q = black_scholes(spot, strike, expiry_days, rate, mid, right)
        if abs(q.price - target_price) < 1e-5:
            return round(mid, 6)
        if q.price < target_price:
            lo = mid
        else:
            hi = mid
    return round(0.5 * (lo + hi), 6)


def realized_volatility(closes: list[float], periods_per_year: float = 252.0) -> float:
    """Volatilidade histórica anualizada a partir de retornos logarítmicos."""
    if len(closes) < 3:
        return 0.30
    rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i] > 0 and closes[i - 1] > 0
    ]
    if len(rets) < 2:
        return 0.30
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    vol = math.sqrt(var * periods_per_year)
    return max(0.08, min(vol, 2.50))


def _strike_step(spot: float) -> float:
    if spot >= 10000:
        return 500.0
    if spot >= 1000:
        return 25.0
    if spot >= 200:
        return 5.0
    if spot >= 50:
        return 2.5
    if spot >= 10:
        return 1.0
    return max(0.05, round(spot * 0.025, 2))


def option_chain(
    spot: float,
    expiry_days: int = 30,
    rate: float = 0.045,
    base_iv: float = 0.28,
    strikes_each_side: int = 6,
) -> list[dict[str, object]]:
    """Gera grade de strikes em torno do spot com sorriso de volatilidade (skew realista)."""
    step = _strike_step(spot)
    atm = round(spot / step) * step
    rows: list[dict[str, object]] = []
    for i in range(-strikes_each_side, strikes_each_side + 1):
        k = max(step, round(atm + i * step, 4))
        moneyness = math.log(k / spot)
        # Skew: puts OTM (k < spot) carregam prêmio de risco maior + curvatura (smile)
        skew_iv = max(0.05, base_iv - 0.12 * moneyness + 0.35 * (moneyness**2))
        call = black_scholes(spot, k, expiry_days, rate, skew_iv, "CALL")
        put = black_scholes(spot, k, expiry_days, rate, skew_iv, "PUT")
        rows.append(
            {
                "strike": k,
                "iv": round(skew_iv, 4),
                "call": {
                    "price": call.price,
                    "bid": call.bid,
                    "ask": call.ask,
                    "delta": call.delta,
                    "gamma": call.gamma,
                    "theta": call.theta,
                    "vega": call.vega,
                    "intrinsic": call.intrinsic,
                    "extrinsic": call.extrinsic,
                    "itm": call.itm,
                },
                "put": {
                    "price": put.price,
                    "bid": put.bid,
                    "ask": put.ask,
                    "delta": put.delta,
                    "gamma": put.gamma,
                    "theta": put.theta,
                    "vega": put.vega,
                    "intrinsic": put.intrinsic,
                    "extrinsic": put.extrinsic,
                    "itm": put.itm,
                },
            }
        )
    return rows
