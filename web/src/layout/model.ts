import { Actions, DockLocation, Model, type IJsonModel, type TabNode } from "flexlayout-react";
import type { FnCode } from "../commands/parse";

export const tabId = (fn: FnCode, symbol?: string) => `${fn}@${symbol ?? ""}`;
const tabName = (fn: FnCode, symbol?: string) => (symbol ? `${fn} ${symbol.split(":")[2]}` : fn);

const tabJson = (fn: FnCode, symbol?: string) => ({
  type: "tab" as const,
  id: tabId(fn, symbol),
  name: tabName(fn, symbol),
  component: fn,
  config: { fn, symbol },
});

export const DEFAULT_LAYOUT: IJsonModel = {
  global: {},
  layout: {
    type: "row",
    children: [
      { type: "tabset", weight: 55, children: [tabJson("MON"), tabJson("REPLAY")] },
      { type: "tabset", weight: 45, children: [tabJson("PORT")] },
    ],
  },
};

export const WORKSPACE_PRESETS: Record<string, (defaultSym?: string) => IJsonModel> = {
  SCALP: (sym = "CRYPTO:BINANCE:BTCUSDT") => ({
    global: {},
    layout: {
      type: "row",
      children: [
        { type: "tabset", weight: 55, children: [tabJson("GP", sym), tabJson("MON")] },
        {
          type: "row",
          weight: 45,
          children: [
            { type: "tabset", weight: 50, children: [tabJson("BOOK", sym), tabJson("ORD", sym)] },
            { type: "tabset", weight: 50, children: [tabJson("PORT"), tabJson("ALRT")] },
          ],
        },
      ],
    },
  }),
  MACRO: (sym = "INDEX:US:GSPC") => ({
    global: {},
    layout: {
      type: "row",
      children: [
        { type: "tabset", weight: 50, children: [tabJson("CURVE"), tabJson("ECO"), tabJson("FX")] },
        { type: "tabset", weight: 50, children: [tabJson("GP", sym), tabJson("MON"), tabJson("PORT")] },
      ],
    },
  }),
  QUANT: (sym = "EQ:US:AAPL") => ({
    global: {},
    layout: {
      type: "row",
      children: [
        { type: "tabset", weight: 52, children: [tabJson("EQS"), tabJson("CORR"), tabJson("MC")] },
        { type: "tabset", weight: 48, children: [tabJson("GP", sym), tabJson("PORT"), tabJson("JRNL")] },
      ],
    },
  }),
  OPTIONS: (sym = "EQ:US:AAPL") => ({
    global: {},
    layout: {
      type: "row",
      children: [
        { type: "tabset", weight: 58, children: [tabJson("OMON", sym), tabJson("GP", sym)] },
        { type: "tabset", weight: 42, children: [tabJson("ORD", sym), tabJson("PORT")] },
      ],
    },
  }),
};

export function allTabs(model: Model): TabNode[] {
  const tabs: TabNode[] = [];
  model.visitNodes((node) => {
    if (node.getType() === "tab") tabs.push(node as TabNode);
  });
  return tabs;
}

export function activeTab(model: Model): TabNode | undefined {
  return model.getActiveTabset()?.getSelectedNode() as TabNode | undefined;
}

export function focusTab(model: Model, id: string): void {
  const tab = model.getNodeById(id);
  if (!tab) return;
  model.doAction(Actions.selectTab(id));
  const parent = tab.getParent();
  if (parent) model.doAction(Actions.setActiveTabset(parent.getId()));
}

/** Abre o painel (ou foca o que já existe). Devolve o modelo a usar: o mesmo, ou um novo se o layout estava vazio. */
export function openPanel(model: Model, fn: FnCode, symbol?: string): Model {
  const id = tabId(fn, symbol);
  if (model.getNodeById(id)) {
    focusTab(model, id);
    return model;
  }
  const target = model.getActiveTabset() ?? model.getFirstTabSet();
  if (!target) {
    return Model.fromJson({
      global: {},
      layout: { type: "row", children: [{ type: "tabset", children: [tabJson(fn, symbol)] }] },
    });
  }
  model.doAction(Actions.addNode(tabJson(fn, symbol), target.getId(), DockLocation.CENTER, -1));
  focusTab(model, id);
  return model;
}

export function closeActive(model: Model): boolean {
  const tab = activeTab(model);
  if (!tab) return false;
  model.doAction(Actions.deleteTab(tab.getId()));
  return true;
}

/** Aba vizinha (delta = +1 ou -1) na ordem do layout, com volta ao início/fim. */
export function cycleTab(model: Model, delta: 1 | -1): void {
  const tabs = allTabs(model);
  if (tabs.length === 0) return;
  const current = activeTab(model);
  const i = current ? tabs.findIndex((t) => t.getId() === current.getId()) : -1;
  focusTab(model, tabs[(i + delta + tabs.length) % tabs.length].getId());
}
