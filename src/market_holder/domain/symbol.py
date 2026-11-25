"""Simbologia própria: CLASSE:MERCADO:SIMBOLO (ex.: EQ:B3:PETR4)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AssetClass(StrEnum):
    EQ = "EQ"  # ações e ETFs
    CRYPTO = "CRYPTO"
    FX = "FX"
    RATE = "RATE"  # juros e séries macro
    CMDTY = "CMDTY"  # commodities
    FUND = "FUND"
    INDEX = "INDEX"  # índices (S&P 500, Nasdaq...)
    OPT = "OPT"  # opções (simuladas)
    FUT = "FUT"  # futuros (simulados)


@dataclass(frozen=True, slots=True)
class Symbol:
    asset_class: AssetClass
    market: str
    ticker: str

    def __post_init__(self) -> None:
        for name in ("market", "ticker"):
            value = getattr(self, name)
            if not value or ":" in value or value != value.strip():
                raise ValueError(f"{name} inválido: {value!r}")

    @classmethod
    def parse(cls, text: str) -> Symbol:
        parts = text.strip().split(":")
        if len(parts) != 3:
            raise ValueError(f"esperado CLASSE:MERCADO:SIMBOLO, recebido {text!r}")
        try:
            asset_class = AssetClass(parts[0].upper())
        except ValueError:
            raise ValueError(f"classe de ativo desconhecida: {parts[0]!r}") from None
        return cls(asset_class, parts[1].upper(), parts[2].upper())

    def __str__(self) -> str:
        return f"{self.asset_class}:{self.market}:{self.ticker}"
