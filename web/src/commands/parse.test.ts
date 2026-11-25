import { describe, expect, it } from "vitest";
import { parseCommand, resolveSymbol } from "./parse";

describe("resolveSymbol", () => {
  it.each([
    ["aapl", "EQ:US:AAPL"],
    ["PETR4.B3", "EQ:B3:PETR4"],
    ["btcusdt.binance", "CRYPTO:BINANCE:BTCUSDT"],
    ["DGS10.FRED", "RATE:FRED:DGS10"],
    ["fx:bcb:usdbrl", "FX:BCB:USDBRL"],
    ["CMDTY:CME:GC", "CMDTY:CME:GC"],
  ])("%s -> %s", (input, expected) => expect(resolveSymbol(input)).toBe(expected));

  it.each(["", "XX:B3:PETR4", "EQ::PETR4", "EQ:B3:A:B", "PETR4.MARS", "A B", "A.B.C"])(
    "rejeita %j",
    (input) => expect(resolveSymbol(input)).toBeUndefined(),
  );
});

describe("parseCommand", () => {
  it("ativo antes ou depois da função", () => {
    const expected = { kind: "panel", fn: "GP", symbol: "EQ:US:AAPL" };
    expect(parseCommand("AAPL GP")).toEqual(expected);
    expect(parseCommand("gp aapl")).toEqual(expected);
  });

  it("ativo sozinho abre o gráfico", () => {
    expect(parseCommand("petr4.b3")).toEqual({ kind: "panel", fn: "GP", symbol: "EQ:B3:PETR4" });
  });

  it("funções sem ativo abrem direto; ORD aceita ativo opcional", () => {
    expect(parseCommand("mon")).toEqual({ kind: "panel", fn: "MON" });
    expect(parseCommand("PORT")).toEqual({ kind: "panel", fn: "PORT" });
    expect(parseCommand("ORD")).toEqual({ kind: "panel", fn: "ORD" });
    expect(parseCommand("BTCUSDT.BINANCE ORD")).toEqual({
      kind: "panel", fn: "ORD", symbol: "CRYPTO:BINANCE:BTCUSDT",
    });
  });

  it("a function that needs a security gives an error with an example", () => {
    const r = parseCommand("GP");
    expect(r.kind).toBe("error");
    expect(r.kind === "error" && r.message).toContain("AAPL US Equity GP");
  });

  it("comandos de layout", () => {
    expect(parseCommand("save meu layout")).toEqual({ kind: "shell", cmd: "SAVE", arg: "meu layout" });
    expect(parseCommand("LAYOUTS")).toEqual({ kind: "shell", cmd: "LAYOUTS", arg: undefined });
    expect(parseCommand("load")).toEqual({ kind: "shell", cmd: "LOAD", arg: undefined });
  });

  it.each(["", "   ", "AAPL XYZ", "A B GP", "EQ::X GP"])("erro em %j", (input) => {
    expect(parseCommand(input).kind).toBe("error");
  });
});

describe("sintaxe de terminal: TICKER BOLSA SETOR FUNÇÃO", () => {
  const sym = (t: string) => (parseCommand(t) as { symbol?: string }).symbol;
  it("aceita código de bolsa e setor", () => {
    expect(sym("AAPL US Equity GP")).toBe("EQ:US:AAPL");
    expect(sym("PETR4 BZ Equity GP")).toBe("EQ:B3:PETR4");
    expect(sym("VOD LN Equity DES")).toBe("EQ:LSE:VOD");
    expect(sym("BTCUSDT Crypto GP")).toBe("CRYPTO:BINANCE:BTCUSDT");
    expect(sym("USDBRL Curncy GP")).toBe("FX:BCB:USDBRL");
    expect(sym("AAPL Equity GP")).toBe("EQ:US:AAPL");
  });
  it("função pode vir antes do ativo", () => {
    expect(sym("GP PETR4 BZ Equity")).toBe("EQ:B3:PETR4");
  });
  it("rejeita bolsa desconhecida e lixo", () => {
    expect(parseCommand("PETR4 ZZ Equity GP").kind).toBe("error");
    expect(parseCommand("A B C D GP").kind).toBe("error");
  });
});
