// Persistência de layouts nomeados no localStorage (Storage injetável, para testar sem navegador).

import type { IJsonModel } from "flexlayout-react";

export const CURRENT = "__current__"; // autosave do layout em uso
const PREFIX = "mh.layout.";
const NAME = /^[A-Za-z0-9_-]{1,32}$/;

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem" | "key" | "length">;

export class LayoutStore {
  constructor(private readonly storage: StorageLike) {}

  static validName(name: string): boolean {
    return NAME.test(name);
  }

  save(name: string, json: IJsonModel): void {
    if (name !== CURRENT && !NAME.test(name)) throw new Error(`nome de layout inválido: ${name}`);
    this.storage.setItem(PREFIX + name, JSON.stringify(json));
  }

  load(name: string): IJsonModel | undefined {
    const raw = this.storage.getItem(PREFIX + name);
    if (raw === null) return undefined;
    try {
      const json = JSON.parse(raw) as IJsonModel;
      return json && typeof json === "object" && json.layout ? json : undefined;
    } catch {
      return undefined; // layout corrompido: o chamador cai no padrão
    }
  }

  list(): string[] {
    const names: string[] = [];
    for (let i = 0; i < this.storage.length; i++) {
      const key = this.storage.key(i);
      if (key?.startsWith(PREFIX) && key.slice(PREFIX.length) !== CURRENT) {
        names.push(key.slice(PREFIX.length));
      }
    }
    return names.sort();
  }

  remove(name: string): void {
    this.storage.removeItem(PREFIX + name);
  }
}
