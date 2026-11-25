import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from market_holder.domain.models import Freq
from market_holder.domain.symbol import Symbol
from market_holder.providers import bcb, binance, fred, tesouro, yahoo
from market_holder.providers.base import Provider


class FakeFetcher:
    def __init__(self, *bodies):
        self.bodies, self.urls = list(bodies), []

    def fetch(self, url):
        self.urls.append(url)
        body = self.bodies.pop(0)
        return body if isinstance(body, bytes) else json.dumps(body).encode()


def run(coro):
    return asyncio.run(coro)


def utc(y, m, d, h=0):
    return datetime(y, m, d, h, tzinfo=UTC)


# --- contrato ---


@pytest.mark.parametrize(
    "prov",
    [
        binance.BinanceProvider(FakeFetcher()),
        bcb.BcbProvider(FakeFetcher()),
        fred.FredProvider(FakeFetcher()),
        yahoo.YahooProvider(FakeFetcher()),
        tesouro.TesouroProvider(FakeFetcher()),
    ],
)
def test_all_providers_satisfy_protocol(prov):
    assert isinstance(prov, Provider)
    assert prov.capabilities.freqs and prov.capabilities.asset_classes


def test_provider_rejects_foreign_symbol():
    with pytest.raises(ValueError):
        run(binance.BinanceProvider(FakeFetcher()).history(
            Symbol.parse("EQ:B3:PETR4"), utc(2024, 1, 1), utc(2024, 1, 2), Freq.D1))


# --- Binance (linhas reais de 2024-01-01 e 2024-01-02) ---

ROW1 = [1704067200000, "42283.58000000", "44184.10000000", "42180.77000000", "44179.55000000",
        "27174.29903000"]
ROW2 = [1704153600000, "44179.55000000", "45879.63000000", "44148.34000000", "44946.91000000",
        "65146.40661000"]
BTC = Symbol.parse("CRYPTO:BINANCE:BTCUSDT")


def test_binance_parse_and_pagination(monkeypatch):
    monkeypatch.setattr(binance, "LIMIT", 1)
    f = FakeFetcher([ROW1], [ROW2], [])
    bars = run(binance.BinanceProvider(f).history(BTC, utc(2024, 1, 1), utc(2024, 1, 3), Freq.D1))
    assert [(b.ts.day, b.open, b.close) for b in bars] == [
        (1, D("42283.58"), D("44179.55")), (2, D("44179.55"), D("44946.91"))]
    assert bars[0].volume == D("27174.29903")
    assert "startTime=1704067200000" in f.urls[0] and "interval=1d" in f.urls[0]
    assert f"startTime={ROW1[0] + 1}" in f.urls[1]  # continua após a última barra
    assert f"endTime={1704240000000 - 1}" in f.urls[0]  # fim exclusivo


def test_binance_search_parses_filters():
    info = {"symbols": [
        {"symbol": "BTCUSDT", "status": "TRADING", "baseAsset": "BTC", "quoteAsset": "USDT",
         "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
                     {"filterType": "LOT_SIZE", "stepSize": "0.00001000"}]},
        {"symbol": "BTCOLD", "status": "BREAK", "baseAsset": "BTC", "quoteAsset": "OLD",
         "filters": []}]}
    (inst,) = run(binance.BinanceProvider(FakeFetcher(info)).search("btc"))
    assert (str(inst.symbol), inst.currency) == ("CRYPTO:BINANCE:BTCUSDT", "USDT")
    assert (inst.tick_size, inst.lot_size) == (D("0.01"), D("0.00001"))


# --- BCB ---

SELIC = Symbol.parse("RATE:BCB:SELIC")


def test_bcb_sgs_parse_chunking_and_filter():
    rows = [
        {"data": "02/01/2024", "valor": "0.043739"},
        {"data": "03/01/2024", "valor": "0.043739"},
    ]
    f = FakeFetcher(rows, [])
    bars = run(bcb.BcbProvider(f).history(SELIC, utc(2024, 1, 2), utc(2024, 1, 3), Freq.D1))
    assert [(b.ts.day, b.close) for b in bars] == [(2, D("0.043739"))]  # 03/01 fora de [start,end)
    f2 = FakeFetcher([], [])
    run(bcb.BcbProvider(f2).history(SELIC, utc(2018, 1, 1), utc(2024, 1, 1), Freq.D1))
    assert len(f2.urls) == 2  # 6 anos: duas consultas de até 5 anos
    assert "dataInicial=01/01/2018" in f2.urls[0] and "dataFinal=31/12/2023" in f2.urls[1]


def test_bcb_ptax_ohlc_from_bulletins():
    payload = {"value": [  # 1ª linha real; as demais sintéticas, só para testar o agrupamento
        {"cotacaoVenda": 4.8916, "dataHoraCotacao": "2024-01-02 13:05:50.319"},
        {"cotacaoVenda": 4.9000, "dataHoraCotacao": "2024-01-02 10:07:11.000"},
        {"cotacaoVenda": 4.8700, "dataHoraCotacao": "2024-01-02 11:06:00.000"},
        {"cotacaoVenda": 4.9212, "dataHoraCotacao": "2024-01-03 13:14:00.000"}]}
    f = FakeFetcher(json.dumps(payload).encode())
    usd = Symbol.parse("FX:BCB:USDBRL")
    b1, b2 = run(bcb.BcbProvider(f).history(usd, utc(2024, 1, 1), utc(2024, 1, 4), Freq.D1))
    assert (b1.open, b1.high, b1.low, b1.close) == (D("4.9"), D("4.9"), D("4.87"), D("4.8916"))
    assert b2.close == D("4.9212")
    assert "@dataInicial='01-01-2024'" in f.urls[0]
    assert "@dataFinalCotacao='01-03-2024'" in f.urls[0]


# --- FRED ---


def test_fred_parse_skips_missing_and_url_is_inclusive_of_last_day():
    csv_text = (b"observation_date,DGS10\n2024-01-02,3.95\n2024-01-03,.\n2024-01-04,3.99\n")
    f = FakeFetcher(csv_text)
    sym = Symbol.parse("RATE:FRED:DGS10")
    bars = run(fred.FredProvider(f).history(sym, utc(2024, 1, 2), utc(2024, 1, 5), Freq.D1))
    assert [(b.ts.day, b.close) for b in bars] == [(2, D("3.95")), (4, D("3.99"))]
    assert "cosd=2024-01-02" in f.urls[0] and "coed=2024-01-04" in f.urls[0]


# --- Yahoo ---


@pytest.mark.parametrize(("sym", "expected"), [
    ("EQ:US:AAPL", "AAPL"), ("EQ:B3:PETR4", "PETR4.SA"),
    ("CMDTY:CME:GC", "GC=F"), ("FX:YAHOO:EURUSD", "EURUSD=X"),
    ("INDEX:US:GSPC", "^GSPC"), ("INDEX:US:IXIC", "^IXIC")])
def test_yahoo_symbol_mapping(sym, expected):
    assert yahoo.to_yahoo(Symbol.parse(sym)) == expected


def test_yahoo_unmapped_market_raises():
    with pytest.raises(ValueError):
        yahoo.to_yahoo(Symbol.parse("EQ:MARS:XYZ"))


def test_yahoo_parse_drops_empty_bars_and_fixes_rounding():
    payload = {"chart": {"error": None, "result": [{
        "timestamp": [1704205800, 1704292200, 1704378600],
        "indicators": {"quote": [{
            "open": [187.1499938964844, None, 182.15],
            "high": [188.44, None, 183.09],
            "low": [183.89, None, 180.88],
            "close": [185.6400146484375, None, 181.91],
            "volume": [82488700, None, 58414500]}]}}]}}
    f = FakeFetcher(json.dumps(payload).encode())
    aapl = Symbol.parse("EQ:US:AAPL")
    bars = run(yahoo.YahooProvider(f).history(aapl, utc(2024, 1, 2), utc(2024, 1, 5), Freq.D1))
    assert [(b.ts.day, b.open, b.close, b.volume) for b in bars] == [
        (2, D("187.15"), D("185.64"), D(82488700)), (4, D("182.15"), D("181.91"), D(58414500))]
    assert "/AAPL?period1=" in f.urls[0] and "interval=1d" in f.urls[0]


def test_yahoo_error_payload_raises():
    payload = {"chart": {"result": None, "error": {"code": "Not Found"}}}
    with pytest.raises(ValueError, match="Not Found"):
        yahoo.parse_chart(Symbol.parse("EQ:US:ZZZZ"), Freq.D1, payload)


# --- Tesouro (linhas reais do CSV oficial) ---

TESOURO_CSV = (
    "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;"
    "PU Venda Manha;PU Base Manha\n"
    "Tesouro Selic;01/03/2027;02/01/2024;0,12;0,13;14227,38;14216,58;14216,58\n"
    "Tesouro Selic;01/03/2027;03/01/2024;0,12;0,13;14233,76;14222,96;14222,96\n"
    "Tesouro Selic;01/03/2027;04/01/2024;0,12;0,13;;;\n"
    "Tesouro IPCA+ com Juros Semestrais;15/05/2035;02/01/2024;5,5;5,6;4000,10;3990,20;3990,20\n"
).encode("latin-1")


def test_tesouro_parse_tickers_values_and_skip_empty():
    data = tesouro.parse_csv(TESOURO_CSV.decode("latin-1"))
    assert sorted(data) == ["IPCA_PLUS_COM_JUROS_SEMESTRAIS-20350515", "SELIC-20270301"]
    assert data["SELIC-20270301"][utc(2024, 1, 2)] == D("14216.58")
    assert utc(2024, 1, 4) not in data["SELIC-20270301"]  # PU de venda vazio


def test_tesouro_history_search_and_single_download():
    f = FakeFetcher(TESOURO_CSV)
    p = tesouro.TesouroProvider(f)
    sym = Symbol.parse("RATE:TESOURO:SELIC-20270301")
    bars = run(p.history(sym, utc(2024, 1, 2), utc(2024, 1, 4), Freq.D1))
    assert [(b.ts.day, b.close) for b in bars] == [(2, D("14216.58")), (3, D("14222.96"))]
    found = run(p.search("ipca"))
    assert [str(i.symbol) for i in found] == [
        "RATE:TESOURO:IPCA_PLUS_COM_JUROS_SEMESTRAIS-20350515"
    ]
    assert len(f.urls) == 1  # CSV baixado uma vez e reaproveitado


@pytest.mark.parametrize(("ysym", "qtype", "expected", "ccy"), [
    ("AAPL", "EQUITY", "EQ:US:AAPL", "USD"), ("PETR4.SA", "EQUITY", "EQ:B3:PETR4", "BRL"),
    ("SAP.DE", "EQUITY", "EQ:XETRA:SAP", "EUR"), ("SHEL.L", "EQUITY", "EQ:LSE:SHEL", "GBX"),
    ("7203.T", "EQUITY", "EQ:TSE:7203", "JPY"), ("SPY", "ETF", "EQ:US:SPY", "USD"),
    ("^FTSE", "INDEX", "INDEX:YAHOO:FTSE", "USD"),
    ("EURUSD=X", "CURRENCY", "FX:YAHOO:EURUSD", "USD"),
    ("CL=F", "FUTURE", "CMDTY:CME:CL", "USD")])
def test_yahoo_search_result_mapping(ysym, qtype, expected, ccy):
    inst = yahoo.from_yahoo(ysym, qtype)
    assert (str(inst.symbol), inst.currency) == (expected, ccy)
    assert yahoo.to_yahoo(inst.symbol) == ysym  # ida e volta


@pytest.mark.parametrize(("ysym", "qtype"), [
    ("BRK.B", "EQUITY"), ("BTC-USD", "CRYPTOCURRENCY"), ("XYZ.ZZ", "EQUITY"), ("AAPL", "OPTION")])
def test_yahoo_search_skips_unmapped(ysym, qtype):
    assert yahoo.from_yahoo(ysym, qtype) is None
