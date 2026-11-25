import { describe, expect, it } from "vitest";
import { num, px, sign, utc } from "./fmt";
import { fmtChg } from "./panels/util";

describe("fmt", () => {
  it("num formata com separador e casas fixas", () => {
    expect(num("1234.5", 2)).toBe("1,234.50");
    expect(num(null)).toBe("–");
    expect(num("abc")).toBe("abc");
  });
  it("px usa mais casas para preços baixos", () => {
    expect(px("65018.01000000")).toBe("65,018.01");
    expect(px("2.5")).toBe("2.5000");
    expect(px("0.00123")).toBe("0.001230");
  });
  it("sign e utc", () => {
    expect(sign(-1)).toBe("down");
    expect(sign("2")).toBe("up");
    expect(sign(0)).toBe("");
    expect(utc("2026-11-17T14:00:00+00:00")).toBe("2026-11-17 14:00");
    expect(utc(null)).toBe("–");
  });
  it("fmtChg calcula variação e percentual; prev 0 não divide", () => {
    expect(fmtChg("110", "100")).toEqual({ chg: 10, pct: 10 });
    expect(fmtChg("5", "0")).toEqual({ chg: 5, pct: 0 });
  });
});
