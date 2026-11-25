// Aceite da Fase 4 no navegador real. Uso: sobe `npm run dev -- --port 5174` e roda
//   CHROME_PATH=<chromium> node e2e/accept.mjs
import puppeteer from "puppeteer-core";

const CHROME = process.env.CHROME_PATH;
const BASE = process.env.BASE_URL ?? "http://localhost:5174/";
if (!CHROME) throw new Error("defina CHROME_PATH (chrome.exe ou outro Chromium)");
const SHOT = process.env.SHOT ?? "shell.png";
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 800 });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => m.type() === "error" && !m.text().includes("/api/health") && !m.text().includes("Failed to load resource") && errors.push(m.text()));

const tabs = () => page.$$eval(".flexlayout__tab_button > .flexlayout__tab_button_content", (els) => els.map((e) => e.textContent.trim()));
const selected = () => page.$eval(".flexlayout__tab_button--selected .flexlayout__tab_button_content", (e) => e.textContent.trim()).catch(() => null);
const status = () => page.$eval(".status .msg", (e) => e.textContent);
const cmd = async (text) => { await page.keyboard.press("/"); await page.keyboard.type(text); await page.keyboard.press("Enter"); await page.keyboard.press("Escape"); };
const check = (name, ok, extra = "") => { console.log(`${ok ? "OK  " : "FALHA"} ${name} ${extra}`); if (!ok) process.exitCode = 1; };

await page.goto(BASE, { waitUntil: "networkidle0" });
await page.evaluate(() => localStorage.clear());
await page.reload({ waitUntil: "networkidle0" });
check("layout padrão com 3 abas", JSON.stringify(await tabs()) === JSON.stringify(["MON", "REPLAY", "PORT"]), JSON.stringify(await tabs()));

await cmd("AAPL GP"); await cmd("PETR4.B3 GP"); await cmd("BTCUSDT.BINANCE BOOK");
const six = await tabs();
check("6 painéis só com teclado", six.length === 6, JSON.stringify(six));
check("aba nova fica selecionada", (await selected()) === "BOOK BTCUSDT", String(await selected()));

await cmd("AAPL GP");
check("mesmo painel não duplica, só foca", (await tabs()).length === 6 && (await selected()) === "GP AAPL", String(await selected()));

await cmd("GP");
check("erro de comando aparece na barra de status", (await status()).includes("needs a security"), await status());

await cmd("SAVE seis");
check("SAVE confirma", (await status()).includes('"seis" saved'), await status());
await cmd("RESET");
check("RESET volta a 3 abas", (await tabs()).length === 3);
await cmd("LAYOUTS");
check("LAYOUTS lista o salvo", (await status()).includes("seis"), await status());
await cmd("LOAD seis");
check("LOAD restaura as 6 abas na mesma ordem", JSON.stringify(await tabs()) === JSON.stringify(six), JSON.stringify(await tabs()));

await page.reload({ waitUntil: "networkidle0" });
check("recarregar a página restaura o layout (autosave)", JSON.stringify(await tabs()) === JSON.stringify(six), JSON.stringify(await tabs()));

await page.keyboard.down("Alt"); await page.keyboard.press("Digit1"); await page.keyboard.up("Alt");
check("Alt+1 vai para a 1ª aba", (await selected()) === six[0], String(await selected()));
await page.keyboard.down("Alt"); await page.keyboard.press("ArrowRight"); await page.keyboard.up("Alt");
check("Alt+→ vai para a próxima", (await selected()) === six[1], String(await selected()));
await page.keyboard.down("Alt"); await page.keyboard.press("KeyW"); await page.keyboard.up("Alt");
check("Alt+W fecha a aba ativa", (await tabs()).length === 5 && !(await tabs()).includes(six[1]), JSON.stringify(await tabs()));

check("barra de status acompanha o nº de abas após fechar", (await page.$eval(".status .right", (e) => e.textContent)).includes("5 tabs"), await page.$eval(".status .right", (e) => e.textContent));
await cmd("VOD LN Equity GP");
check("sintaxe de terminal (TICKER BOLSA SETOR FUNÇÃO) abre o painel", (await selected()) === "GP VOD", String(await selected()));
await page.keyboard.press("F2");
check("F2 abre/foca MON", (await selected()) === "MON", String(await selected()));
await page.keyboard.press("F10");
check("F10 abre/foca REPLAY", (await selected()) === "REPLAY", String(await selected()));
check("barra de teclas F1..F10 visível", (await page.$$(".fkeys button")).length === 10);
check("sem erros de console", errors.length === 0, errors.join(" | "));
await page.screenshot({ path: SHOT });
await browser.close();
