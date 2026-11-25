"""Conta: caixa multi-moeda, posições, P&L realizado e não realizado, exposição e margem.

Convenções:
- Custo médio por posição (FIFO fica para depois).
- Equity = caixa + valor de mercado das posições, tudo convertido para a moeda base.
- Margem no estilo Reg T: inicial 50% e manutenção 25% sobre a exposição bruta.
- Ordens pendentes não entram no cálculo de margem (simplificação).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from market_holder.domain.models import ZERO, Fill, Instrument, Portfolio, Position, Side
from market_holder.domain.symbol import Symbol


class MissingRateError(KeyError):
    """Falta taxa de câmbio para converter uma moeda para a base."""


@dataclass(frozen=True, slots=True)
class MarginPolicy:
    initial_rate: Decimal = Decimal("0.5")
    maintenance_rate: Decimal = Decimal("0.25")
    allow_short: bool = True
    auto_liquidate: bool = False  # liquidação forçada quando equity < maintenance_required


@dataclass(frozen=True, slots=True)
class MarginStatus:
    equity: Decimal
    gross_exposure: Decimal
    initial_required: Decimal
    maintenance_required: Decimal
    margin_call: bool


class Account:
    def __init__(
        self,
        base_currency: str,
        cash: dict[str, Decimal],
        instruments: dict[Symbol, Instrument],
        policy: MarginPolicy | None = None,
    ) -> None:
        self.portfolio = Portfolio(base_currency, dict(cash))
        self.instruments = dict(instruments)
        self.policy = policy or MarginPolicy()
        self.marks: dict[Symbol, Decimal] = {}
        self.fx: dict[str, Decimal] = {base_currency: Decimal(1)}
        self.realized: dict[Symbol, Decimal] = {}  # bruto de taxas, na moeda do instrumento
        self.fees: dict[str, Decimal] = {}
        self.borrow_fees: dict[str, Decimal] = {}  # acumulado de aluguel de ações por moeda

    # --- mercado ---

    def set_fx(self, currency: str, rate_to_base: Decimal) -> None:
        if rate_to_base <= 0:
            raise ValueError("taxa de câmbio deve ser positiva")
        self.fx[currency] = rate_to_base

    def rate(self, currency: str) -> Decimal:
        try:
            return self.fx[currency]
        except KeyError:
            raise MissingRateError(currency) from None

    def mark(self, symbol: Symbol) -> Decimal:
        """Último preço; sem preço usa o custo médio (P&L não realizado zero)."""
        if symbol in self.marks:
            return self.marks[symbol]
        return self.portfolio.positions[symbol].avg_price

    # --- execuções ---

    def apply_fill(self, fill: Fill) -> Decimal:
        """Aplica a execução e devolve o P&L realizado dela (moeda do instrumento, sem taxa)."""
        inst = self.instruments[fill.symbol]
        pos = self.portfolio.positions.setdefault(fill.symbol, Position(fill.symbol))
        realized = pos.apply(fill.side, fill.qty, fill.price) * inst.multiplier
        notional = fill.qty * fill.price * inst.multiplier
        ccy = inst.currency
        cash = self.portfolio.cash
        cash[ccy] = cash.get(ccy, ZERO) - fill.side.sign * notional - fill.fee
        self.realized[fill.symbol] = self.realized.get(fill.symbol, ZERO) + realized
        self.fees[ccy] = self.fees.get(ccy, ZERO) + fill.fee
        return realized

    # --- métricas ---

    def unrealized(self, symbol: Symbol) -> Decimal:
        pos = self.portfolio.positions.get(symbol)
        if pos is None or pos.qty == 0:
            return ZERO
        mult = self.instruments[symbol].multiplier
        return pos.qty * (self.mark(symbol) - pos.avg_price) * mult

    def _position_value_base(self, symbol: Symbol, qty: Decimal, price: Decimal) -> Decimal:
        inst = self.instruments[symbol]
        return qty * price * inst.multiplier * self.rate(inst.currency)

    def equity(self) -> Decimal:
        total = sum((amt * self.rate(ccy) for ccy, amt in self.portfolio.cash.items()), ZERO)
        for symbol, pos in self.portfolio.positions.items():
            if pos.qty != 0:
                total += self._position_value_base(symbol, pos.qty, self.mark(symbol))
        return total

    def net_exposure(self) -> Decimal:
        return sum(
            (
                self._position_value_base(s, p.qty, self.mark(s))
                for s, p in self.portfolio.positions.items()
                if p.qty != 0
            ),
            ZERO,
        )

    def gross_exposure(self) -> Decimal:
        return sum(
            (
                abs(self._position_value_base(s, p.qty, self.mark(s)))
                for s, p in self.portfolio.positions.items()
                if p.qty != 0
            ),
            ZERO,
        )

    def margin_status(self) -> MarginStatus:
        equity, gross = self.equity(), self.gross_exposure()
        maintenance = gross * self.policy.maintenance_rate
        return MarginStatus(
            equity=equity,
            gross_exposure=gross,
            initial_required=gross * self.policy.initial_rate,
            maintenance_required=maintenance,
            margin_call=gross > 0 and equity < maintenance,
        )

    # --- pré-negociação ---

    def charge_borrow_fee(self, days: int = 1) -> dict[Symbol, Decimal]:
        """Debita taxa diária de aluguel sobre posições vendidas (rate / 252 * days)."""
        charged: dict[Symbol, Decimal] = {}
        if days <= 0:
            return charged
        for symbol, pos in self.portfolio.positions.items():
            if pos.qty >= 0:
                continue
            inst = self.instruments[symbol]
            if inst.borrow_rate_annual <= 0:
                continue
            notional = abs(pos.qty) * self.mark(symbol) * inst.multiplier
            fee = (notional * inst.borrow_rate_annual * Decimal(days)) / Decimal(252)
            if fee > 0:
                ccy = inst.currency
                self.portfolio.cash[ccy] = self.portfolio.cash.get(ccy, ZERO) - fee
                self.fees[ccy] = self.fees.get(ccy, ZERO) + fee
                self.borrow_fees[ccy] = self.borrow_fees.get(ccy, ZERO) + fee
                charged[symbol] = fee
        return charged

    def apply_split(self, symbol: Symbol, ratio: Decimal) -> None:
        """Desdobramento (ratio > 1) ou grupamento (0 < ratio < 1): preserva valor financeiro."""
        if ratio <= 0:
            raise ValueError("ratio deve ser positivo")
        pos = self.portfolio.positions.get(symbol)
        if pos and pos.qty != 0:
            pos.qty = pos.qty * ratio
            pos.avg_price = pos.avg_price / ratio
        if symbol in self.marks:
            self.marks[symbol] = self.marks[symbol] / ratio

    def apply_dividend(self, symbol: Symbol, amount_per_share: Decimal) -> Decimal:
        """Crédito (comprado) ou débito (vendido) de dividendo em caixa na moeda do ativo."""
        if amount_per_share <= 0:
            raise ValueError("dividendo deve ser positivo")
        pos = self.portfolio.positions.get(symbol)
        if not pos or pos.qty == 0:
            return ZERO
        inst = self.instruments[symbol]
        payment = pos.qty * amount_per_share * inst.multiplier
        ccy = inst.currency
        self.portfolio.cash[ccy] = self.portfolio.cash.get(ccy, ZERO) + payment
        self.realized[symbol] = self.realized.get(symbol, ZERO) + payment
        return payment

    def check_order(
        self, symbol: Symbol, side: Side, qty: Decimal, ref_price: Decimal
    ) -> str | None:
        """Motivo da rejeição, ou None se a ordem passa. Ordem que reduz exposição sempre passa."""
        inst = self.instruments[symbol]
        pos = self.portfolio.positions.get(symbol)
        current = pos.qty if pos else ZERO
        after = current + side.sign * qty
        if after < 0 and not self.policy.allow_short:
            return "short selling not allowed"
        if after < 0 and after < current and inst.locate_limit is not None:
            if abs(after) > inst.locate_limit:
                return f"insufficient locate (max {inst.locate_limit})"
        mark = self.mark(symbol) if (pos and pos.qty != 0) else ref_price
        old_value = abs(self._position_value_base(symbol, current, mark))
        new_value = abs(self._position_value_base(symbol, after, ref_price))
        if new_value <= old_value:
            return None
        gross_after = self.gross_exposure() - old_value + new_value
        if self.equity() < gross_after * self.policy.initial_rate:
            return "insufficient margin"
        return None
