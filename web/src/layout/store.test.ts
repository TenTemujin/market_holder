import type { IJsonModel } from "flexlayout-react";
import { describe, expect, it } from "vitest";
import { CURRENT, LayoutStore } from "./store";

class MemoryStorage {
  private m = new Map<string, string>();
  get length() { return this.m.size; }
  key(i: number) { return [...this.m.keys()][i] ?? null; }
  getItem(k: string) { return this.m.get(k) ?? null; }
  setItem(k: string, v: string) { this.m.set(k, v); }
  removeItem(k: string) { this.m.delete(k); }
}

const json = (name: string): IJsonModel => ({
  global: {},
  layout: { type: "row", children: [{ type: "tabset", children: [{ type: "tab", name, component: name }] }] },
});

describe("LayoutStore", () => {
  it("salva, carrega e lista, sem listar o autosave", () => {
    const s = new LayoutStore(new MemoryStorage());
    s.save("beta", json("B"));
    s.save("alfa", json("A"));
    s.save(CURRENT, json("C"));
    expect(s.list()).toEqual(["alfa", "beta"]);
    expect(s.load("alfa")).toEqual(json("A"));
    expect(s.load(CURRENT)).toEqual(json("C"));
    expect(s.load("nada")).toBeUndefined();
  });

  it("recarregar devolve exatamente o que foi salvo (ida e volta)", () => {
    const storage = new MemoryStorage();
    new LayoutStore(storage).save("x", json("GP"));
    expect(new LayoutStore(storage).load("x")).toEqual(json("GP"));
  });

  it("rejeita nome inválido e ignora layout corrompido", () => {
    const storage = new MemoryStorage();
    const s = new LayoutStore(storage);
    expect(() => s.save("nome com espaço", json("A"))).toThrow();
    storage.setItem("mh.layout.ruim", "{não é json");
    expect(s.load("ruim")).toBeUndefined();
    storage.setItem("mh.layout.vazio", "{}");
    expect(s.load("vazio")).toBeUndefined();
  });

  it("remove", () => {
    const s = new LayoutStore(new MemoryStorage());
    s.save("a", json("A"));
    s.remove("a");
    expect(s.list()).toEqual([]);
  });
});
