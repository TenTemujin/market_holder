import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("api()", () => {
  it("retries a GET through a brief outage and then succeeds", async () => {
    vi.useFakeTimers();
    const f = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(new Response("Bad Gateway", { status: 502 }))
      .mockResolvedValueOnce(json(200, { ok: true }));
    vi.stubGlobal("fetch", f);
    const p = api("GET", "/api/health");
    await vi.advanceTimersByTimeAsync(5000);
    await expect(p).resolves.toEqual({ ok: true });
    expect(f).toHaveBeenCalledTimes(3);
  });

  it("gives a clear message instead of 'Failed to fetch' when the API stays down", async () => {
    vi.useFakeTimers();
    const f = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", f);
    const p = api("GET", "/api/health");
    const assertion = expect(p).rejects.toThrow(/Cannot reach the API/);
    await vi.advanceTimersByTimeAsync(5000);
    await assertion;
    expect(f).toHaveBeenCalledTimes(3);
  });

  it("never retries a POST (it could place an order twice)", async () => {
    const f = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", f);
    await expect(api("POST", "/api/orders", {})).rejects.toThrow(/Cannot reach the API/);
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("treats a proxy 502 as 'API offline'", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Bad Gateway", { status: 502 })));
    await expect(api("POST", "/api/session", {})).rejects.toThrow(/Cannot reach the API/);
  });

  it("detects HTML served in place of the API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<!doctype html>", { status: 200 })));
    await expect(api("GET", "/api/health")).rejects.toThrow(/not the API/);
  });

  it("keeps the API's own error detail for real errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(422, { detail: "sem dados" })));
    await expect(api("POST", "/api/session", {})).rejects.toThrow("422: sem dados");
  });
});
