"""Horário regular de negociação por mercado: aberto/fechado agora e próxima mudança.

Só o pregão regular, em horário local da bolsa (com horário de verão via tzdata). NÃO modela
feriados, pregões encurtados, leilões nem pré/pós-mercado.
Tabela conferida contra os horários oficiais das bolsas:
- US (NYSE/Nasdaq): 09:30-16:00 America/New_York
- B3 (São Paulo): 10:00-17:55 America/Sao_Paulo (pregão contínuo; call de fechamento 17:55-18:00)
- LSE (Londres): 08:00-16:30 Europe/London
- XETRA / Euronext / SIX / MIL / BME: 09:00-17:30 CET/CEST
- TSE (Tóquio): 09:00-11:30, 12:30-15:30 Asia/Tokyo (estendido para 15:30 em nov/2024)
- HKEX (Hong Kong): 09:30-12:00, 13:00-16:00 Asia/Hong_Kong
- SSE / SZSE (Xangai/Shenzhen): 09:30-11:30, 13:00-15:00 Asia/Shanghai
- SGX (Singapura): 09:00-12:00, 13:00-17:00 Asia/Singapore
- KRX (Seul): 09:00-15:30 Asia/Seoul
- NSE / BSE (Índia): 09:15-15:30 Asia/Kolkata
- ASX (Sydney): 10:00-16:00 Australia/Sydney
- TASE (Tel Aviv): Seg-Qui 09:59-17:14, Sex 09:59-13:50 Asia/Jerusalem (regime seg-sex de jan/2026;
  aproximado aqui pelo pregão contínuo seg-sex 10:00-17:14)
Cripto negocia 24/7; câmbio de domingo 17:00 a sexta 17:00 (Nova York); futuros de commodities
(CME) de domingo a sexta 18:00 a 17:00 (Nova York), com pausa diária de 1 h.
Séries macro (FRED, BCB, Tesouro) são diárias: não têm "aberto/fechado" (devolve None).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from market_holder.domain.symbol import AssetClass, Symbol

Session = tuple[time, time]


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _s(*spans: str) -> tuple[Session, ...]:
    return tuple((_t(a), _t(b)) for a, b in (x.split("-") for x in spans))


# mercado interno -> (fuso IANA, sessões locais seg-sex)
EXCHANGE_HOURS: dict[str, tuple[str, tuple[Session, ...]]] = {
    "US": ("America/New_York", _s("09:30-16:00")),
    "B3": ("America/Sao_Paulo", _s("10:00-17:55")),
    "LSE": ("Europe/London", _s("08:00-16:30")),
    "XETRA": ("Europe/Berlin", _s("09:00-17:30")),
    "TSE": ("Asia/Tokyo", _s("09:00-11:30", "12:30-15:30")),
    "HKEX": ("Asia/Hong_Kong", _s("09:30-12:00", "13:00-16:00")),
    "EURONEXT": ("Europe/Paris", _s("09:00-17:30")),
    "AMS": ("Europe/Amsterdam", _s("09:00-17:30")),
    "MIL": ("Europe/Rome", _s("09:00-17:30")),
    "BME": ("Europe/Madrid", _s("09:00-17:30")),
    "BRU": ("Europe/Brussels", _s("09:00-17:30")),
    "LIS": ("Europe/Lisbon", _s("08:00-16:30")),
    "HEL": ("Europe/Helsinki", _s("10:00-18:30")),
    "VIE": ("Europe/Vienna", _s("09:00-17:30")),
    "SIX": ("Europe/Zurich", _s("09:00-17:30")),
    "TSX": ("America/Toronto", _s("09:30-16:00")),
    "TSXV": ("America/Toronto", _s("09:30-16:00")),
    "ASX": ("Australia/Sydney", _s("10:00-16:00")),
    "NZX": ("Pacific/Auckland", _s("10:00-16:45")),
    "NSE": ("Asia/Kolkata", _s("09:15-15:30")),
    "BSE": ("Asia/Kolkata", _s("09:15-15:30")),
    "KRX": ("Asia/Seoul", _s("09:00-15:30")),
    "KOSDAQ": ("Asia/Seoul", _s("09:00-15:30")),
    "SSE": ("Asia/Shanghai", _s("09:30-11:30", "13:00-15:00")),
    "SZSE": ("Asia/Shanghai", _s("09:30-11:30", "13:00-15:00")),
    "SGX": ("Asia/Singapore", _s("09:00-12:00", "13:00-17:00")),
    "TWSE": ("Asia/Taipei", _s("09:00-13:30")),
    "TASE": ("Asia/Jerusalem", _s("10:00-17:14")),
    "STO": ("Europe/Stockholm", _s("09:00-17:30")),
    "OSL": ("Europe/Oslo", _s("09:00-16:20")),
    "CPH": ("Europe/Copenhagen", _s("09:00-17:00")),
    "WSE": ("Europe/Warsaw", _s("09:00-17:00")),
    "IST": ("Europe/Istanbul", _s("10:00-18:00")),
    "MEX": ("America/Mexico_City", _s("08:30-15:00")),
    "BCBA": ("America/Argentina/Buenos_Aires", _s("11:00-17:00")),
    "JSE": ("Africa/Johannesburg", _s("09:00-17:00")),
    "SET": ("Asia/Bangkok", _s("10:00-12:30", "14:30-16:30")),
    "IDX": ("Asia/Jakarta", _s("09:00-11:30", "13:30-15:50")),
    "KLSE": ("Asia/Kuala_Lumpur", _s("09:00-12:30", "14:30-17:00")),
}
_NY = ZoneInfo("America/New_York")
_HORIZON_DAYS = 10


Window = tuple[datetime, datetime]


def _local_windows(tz: str, sessions: tuple[Session, ...], day0: datetime) -> Iterator[Window]:
    z = ZoneInfo(tz)
    base = day0.astimezone(z).date() - timedelta(days=1)
    for i in range(_HORIZON_DAYS):
        d = base + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        for a, b in sessions:
            yield (
                datetime.combine(d, a, z).astimezone(UTC),
                datetime.combine(d, b, z).astimezone(UTC),
            )


def _ny_windows(day0: datetime, kind: str) -> Iterator[Window]:
    base = day0.astimezone(_NY).date() - timedelta(days=7)
    for i in range(_HORIZON_DAYS + 7):
        d = base + timedelta(days=i)
        wd = d.weekday()  # seg=0 ... dom=6
        if kind == "fx" and wd == 6:  # dom 17:00 -> sex 17:00
            yield (
                datetime.combine(d, time(17), _NY).astimezone(UTC),
                datetime.combine(d + timedelta(days=5), time(17), _NY).astimezone(UTC),
            )
        elif kind == "cmdty" and wd in (6, 0, 1, 2, 3):  # dom a qui 18:00 -> dia seguinte 17:00
            yield (
                datetime.combine(d, time(18), _NY).astimezone(UTC),
                datetime.combine(d + timedelta(days=1), time(17), _NY).astimezone(UTC),
            )


def _windows(symbol: Symbol, now: datetime) -> tuple[str, Iterator[Window]] | None:
    ac = symbol.asset_class
    if ac is AssetClass.CRYPTO:
        return "24/7", iter(())
    if ac is AssetClass.FX:
        return "Sun 17:00 - Fri 17:00 America/New_York", _ny_windows(now, "fx")
    if ac is AssetClass.CMDTY:
        return "Sun-Fri 18:00 - 17:00 America/New_York (1 h break)", _ny_windows(now, "cmdty")
    if ac in (AssetClass.EQ, AssetClass.FUND, AssetClass.INDEX) and symbol.market in EXCHANGE_HOURS:
        tz, sessions = EXCHANGE_HOURS[symbol.market]
        label = ", ".join(f"{a:%H:%M}-{b:%H:%M}" for a, b in sessions)
        return f"Mon-Fri {label} {tz}", _local_windows(tz, sessions, now)
    return None


def market_status(symbol: Symbol, now: datetime) -> dict[str, object] | None:
    """{"open", "next_change", "hours"} ou None se o ativo não tem horário (séries diárias)."""
    if now.tzinfo is None:
        raise ValueError("now precisa de fuso")
    now = now.astimezone(UTC)
    found = _windows(symbol, now)
    if found is None:
        return None
    hours, wins = found
    if hours == "24/7":
        return {"open": True, "next_change": None, "hours": hours}
    is_open, nxt = False, None
    for start, end in sorted(wins):
        if start <= now < end:
            is_open, nxt = True, end
            break
        if start > now:
            nxt = start
            break
    return {"open": is_open, "next_change": nxt.isoformat() if nxt else None, "hours": hours}


def session_date_for(symbol: Symbol, ts: datetime) -> object:
    """Data local do pregão do ativo (para expirar ordens DAY no fuso da bolsa, não em UTC)."""
    if symbol.market in EXCHANGE_HOURS:
        tz_name, _ = EXCHANGE_HOURS[symbol.market]
        return ts.astimezone(ZoneInfo(tz_name)).date()
    if symbol.asset_class in (AssetClass.FX, AssetClass.CMDTY):
        return ts.astimezone(_NY).date()
    return ts.astimezone(UTC).date()
