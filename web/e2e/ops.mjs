// Aceite da Fase 5 no navegador real: criar sessão, abrir gráfico, enviar ordem, ver execução na carteira.
// Requer API em :8000 (com rede) e `npm run dev -- --port 5174`. Uso:
//   CHROME_PATH=<chromium> node e2e/ops.mjs [SIMBOLO_CMD] [SIMBOLO_COMPLETO:MOEDA] [freq] [inicio] [fim]
import puppeteer from "puppeteer-core";

const CHROME = process.env.CHROME_PATH;
if (!CHROME) throw new Error("defina CHROME_PATH (chrome.exe ou outro Chromium)");
const BASE = process.env.BASE_URL ?? "http://localhost:5174/";
const SHOT = process.env.SHOT ?? "ops.png";
const [cmdSym = "BTCUSDT.BINANCE", full = "CRYPTO:BINANCE:BTCUSDT:USDT", freq = "1h", start, end] = process.argv.slice(2);
const base = full.split(":").pop();
const LIVE = process.env.MODE === "live"; // MODE=live: sessão ao vivo (espera barras reais fecharem, até ~3 min)

const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"], protocolTimeout: 300000 });
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => m.type() === "error" && !m.text().includes("Failed to load resource") && errors.push(m.text()));

const check = (name, ok, extra = "") => { console.log(`${ok ? "OK  " : "FALHA"} ${name} ${extra}`); if (!ok) process.exitCode = 1; };
const cmd = async (text) => { await page.evaluate(() => document.activeElement?.blur()); await page.keyboard.press("/"); await wait(60); await page.keyboard.type(text); await page.keyboard.press("Enter"); await page.keyboard.press("Escape"); };
const click = async (label) => {
  const ok = await page.evaluate((l) => {
    const b = [...document.querySelectorAll("button")].find((x) => x.textContent.trim() === l && x.offsetParent);
    if (b) b.click();
    return !!b;
  }, label);
  if (!ok) throw new Error(`botão não achado: ${label}`);
};
const setField = async (aria, value) => {
  const sel = `[aria-label="${aria}"]`;
  await page.waitForSelector(sel, { visible: true });
  await page.focus(sel);
  await page.keyboard.down("Control"); await page.keyboard.press("KeyA"); await page.keyboard.up("Control");
  await page.keyboard.type(value);
};
const text = (sel) => page.evaluate((s) => [...document.querySelectorAll(s)].filter((e) => e.offsetParent).map((e) => e.textContent).join(" | "), sel);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const waitText = (sel, re, ms = 30000) => page.waitForFunction((s, r) => new RegExp(r).test([...document.querySelectorAll(s)].filter((e) => e.offsetParent).map((e) => e.textContent).join(" | ")), { timeout: ms }, sel, re.source);

await page.goto(BASE, { waitUntil: "networkidle0" });
await page.evaluate(() => localStorage.clear());
await page.reload({ waitUntil: "networkidle0" });

// 1. sessão
const idBefore = await page.evaluate(() => fetch("/api/session").then((r) => (r.ok ? r.json() : { id: 0 })).then((j) => j.id ?? 0));
await cmd("REPLAY");
if (LIVE) await click("LIVE");
await setField("Securities", full);
await page.select('[aria-label="Freq"]', freq);
if (!LIVE && start) await setField("Start", start);
if (!LIVE && end) await setField("End", end);
await setField("Cash", "100000");
await setField("Base currency", base);
await click(LIVE ? "Start live" : "Create session");
await wait(1500);
const createErr = await text(".err");
if (createErr) console.log("ERRO AO CRIAR SESSÃO:", createErr);
await waitText(".panel-body", /Session #\d+/);
const idAfter = await page.evaluate(() => fetch("/api/session").then((r) => r.json()).then((j) => j.id));
check("sessão nova criada com dados reais", idAfter > idBefore, `id ${idBefore} -> ${idAfter}`);

// 2. gráfico
await cmd(`${cmdSym} GP`);
await click("Step").catch(() => undefined);
if (!LIVE) {
  await cmd("REPLAY");
  for (let i = 0; i < 3; i++) { await click("Step"); await wait(250); }
}
await cmd(`${cmdSym} GP`);
await page.waitForFunction(() => Number(document.querySelector('[data-testid="chart"]')?.dataset.bars) > 0, { timeout: 15000 }).catch(async () => {
  console.log("DEBUG", JSON.stringify(await page.evaluate(() => ({ chart: !!document.querySelector('[data-testid="chart"]'), bars: document.querySelector('[data-testid="chart"]')?.dataset.bars, tabs: [...document.querySelectorAll(".flexlayout__tab_button_content")].map((e) => e.textContent), sess: document.body.innerText.slice(0, 300) }))));
  await page.screenshot({ path: SHOT });
});
const bars = await page.$eval('[data-testid="chart"]', (e) => Number(e.dataset.bars));
check("gráfico mostra barras processadas", LIVE ? bars >= 50 : bars >= 3, `barras=${bars}`);
check("canvas do gráfico existe", (await page.$$("[data-testid=chart] canvas")).length > 0);

// 3. ordem
await cmd("ORD");
await page.waitForSelector('[aria-label="Quantity"]', { visible: true });
await click("BUY");
await click("10%");
const qty = await page.$eval('[aria-label="Quantity"]', (e) => e.value);
check("atalho de % preenche a quantidade", Number(qty) > 0, `qtd=${qty}`);
await click("SEND BUY");
await waitText('[role="status"]', /Order O\d+/);
check("ordem aceita", /Order O1 NEW/.test(await text('[role="status"]')), await text('[role="status"]'));

// 4. execução (próxima barra) e carteira
if (LIVE) {
  await cmd(`${cmdSym} BOOK`);
  await waitText(".panel-body", /LIVE: real Binance order book/, 15000);
  const rows = await page.$$eval(".panel-body table.grid tbody tr", (r) => r.length);
  check("livro real da Binance com níveis e negociações", rows >= 20, `linhas=${rows}`);
} else {
  await cmd("REPLAY");
  await click("Step");
  await wait(500);
}
await cmd("PORT");
await waitText(".panel-body", /FILLED/, LIVE ? 240000 : 30000).catch(async (e) => {
  console.log("DIAG feed ao vivo:", JSON.stringify(await page.evaluate(() => fetch("/api/session").then((r) => r.json()).then((j) => ({ clock: j.clock, live: j.live, orders: j.orders.map((o) => o.status) })))));
  throw e;
});
const port = await text(".panel-body");
check("ordem FILLED na carteira", /FILLED/.test(port));
check("posição aparece na carteira", port.includes(full.split(":")[2]) && !port.includes("No positions"), port.slice(0, 160));

// 5. a API confirma a execução
const snap = await page.evaluate(() => fetch("/api/session").then((r) => r.json()));
if (LIVE) check("sessão marcada ao vivo", snap.meta.mode === "live" && snap.meta.end === null);
check("API tem 1 execução e 1 posição", snap.fills.length === 1 && snap.positions.length === 1, `fills=${snap.fills.length} pos=${snap.positions.length}`);
check("execução depois da ordem (sem lookahead)", snap.fills[0].ts > snap.orders[0].order.ts || LIVE && snap.fills[0].ts >= snap.orders[0].order.ts, `${snap.orders[0].order.ts} < ${snap.fills[0].ts}`);

await cmd(`${cmdSym} GP`);
await wait(500);
await page.screenshot({ path: SHOT });
check("sem erros de console", errors.length === 0, errors.join(" | "));
await browser.close();
