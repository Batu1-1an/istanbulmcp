import { describe, expect, it } from "vitest";

import worker, {
  createKvCache,
  handleRequest,
  refreshRelayCache,
  type RelayCache,
  type RelayEnv,
  type RelayFetch,
  type RelayKv,
} from "../src/index";

const env = { RELAY_TOKEN: "test-relay-token" } as RelayEnv;

function request(path: string, init?: RequestInit): Request {
  return new Request(`https://relay.example${path}`, init);
}

function authorizedRequest(path: string, init?: RequestInit): Request {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${env.RELAY_TOKEN}`);
  return request(path, { ...init, headers });
}

describe("ISKI relay", () => {
  it("serves health without authentication", async () => {
    const response = await worker.fetch(request("/healthz"), env);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ ok: true, service: "istanbul-iski-relay" });
  });

  it("rejects missing authentication", async () => {
    const response = await worker.fetch(request("/iski/faults"), env);

    expect(response.status).toBe(401);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });

  it("rejects methods other than GET", async () => {
    const response = await worker.fetch(authorizedRequest("/iski/faults", { method: "POST" }), env);

    expect(response.status).toBe(405);
    expect(response.headers.get("Allow")).toBe("GET");
  });

  it("does not proxy unknown routes or query-provided targets", async () => {
    let called = false;
    const fetcher: RelayFetch = async () => {
      called = true;
      return Response.json({});
    };

    const response = await handleRequest(authorizedRequest("/proxy?url=https://example.com/private"), env, fetcher);

    expect(response.status).toBe(404);
    expect(called).toBe(false);
  });

  it("uses only the fixed official e-Devlet faults upstream", async () => {
    let upstream = "";
    let calls = 0;
    const html = `<table class="resultTable"><tbody><tr>
      <td>FATİH - BALAT</td><td>BALAT MAH</td><td>23/07/2026 13:00:08</td><td>23/07/2026 19:00:00</td><td>-</td>
    </tr></tbody></table>`;
    const fetcher: RelayFetch = async (input) => {
      calls += 1;
      upstream = String(input);
      return new Response(html);
    };

    const response = await handleRequest(authorizedRequest("/iski/faults"), env, fetcher);

    expect(upstream).toBe(
      "https://www.turkiye.gov.tr/istanbul-su-ve-kanalizasyon-idaresi-ariza-bakim-bilgisi-sorgulama",
    );
    expect(response.status).toBe(200);
    expect(calls).toBe(1);
    await expect(response.json()).resolves.toMatchObject({ relay_source: "edevlet" });
  });

  it("maps upstream errors to 502", async () => {
    const fetcher: RelayFetch = async () => new Response("blocked", { status: 403 });

    const response = await handleRequest(authorizedRequest("/iski/dams"), env, fetcher);

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({ error: "Upstream request failed" });
  });

  it("rejects invalid JSON and oversized payloads", async () => {
    const invalidJson: RelayFetch = async () => new Response("not-json");
    const oversized: RelayFetch = async () =>
      new Response("{}", { headers: { "Content-Length": String(2 * 1024 * 1024 + 1) } });

    const invalidResponse = await handleRequest(authorizedRequest("/iski/dams"), env, invalidJson);
    const oversizedResponse = await handleRequest(authorizedRequest("/iski/dams"), env, oversized);

    expect(invalidResponse.status).toBe(502);
    expect(oversizedResponse.status).toBe(502);
  });

  it("maps upstream timeouts to 504", async () => {
    const fetcher: RelayFetch = async () => {
      throw new DOMException("Timed out", "TimeoutError");
    };

    const response = await handleRequest(authorizedRequest("/iski/faults"), env, fetcher);

    expect(response.status).toBe(504);
    await expect(response.json()).resolves.toEqual({ error: "Upstream request timed out" });
  });

  it("falls back to ISKI GeoJSON when the e-Devlet outage table times out", async () => {
    let calls = 0;
    const geojson = { type: "FeatureCollection", features: [] };
    const fetcher: RelayFetch = async () => {
      calls += 1;
      if (calls === 1) {
        throw new DOMException("Timed out", "TimeoutError");
      }
      return Response.json(geojson);
    };

    const response = await handleRequest(authorizedRequest("/iski/faults"), env, fetcher);
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(calls).toBe(2);
    expect(payload).toEqual({ ...geojson, relay_source: "iski" });
  });

  it("falls back to the official e-Devlet dam table when ISKI times out", async () => {
    let calls = 0;
    const html = `
      <table class="resultTable striped"><tbody><tr>
        <td>Omerli</td><td>244540000</td><td>80.68</td><td>-</td>
      </tr></tbody></table>`;
    const fetcher: RelayFetch = async () => {
      calls += 1;
      if (calls === 1) throw new DOMException("Timed out", "TimeoutError");
      return new Response(html, { headers: { "Content-Type": "text/html" } });
    };

    const response = await handleRequest(authorizedRequest("/iski/dams"), env, fetcher);
    const payload = (await response.json()) as {
      relay_source: string;
      data: Array<Record<string, number | string>>;
    };

    expect(response.status).toBe(200);
    expect(calls).toBe(2);
    expect(payload.relay_source).toBe("edevlet");
    expect(payload.data).toEqual([
      { kaynakAdi: "Omerli", baslikAdi: "Omerli", biriktirmeHacmi: 244.54, dolulukOrani: 80.68 },
    ]);
  });

  it("serves authenticated data from the internal cache without exposing cacheable responses", async () => {
    let upstreamCalls = 0;
    let cached: Response | undefined;
    const cache: RelayCache = {
      async match() {
        return cached?.clone();
      },
      async put(_request, response) {
        cached = response.clone();
      },
    };
    const fetcher: RelayFetch = async () => {
      upstreamCalls += 1;
      return Response.json({ data: [{ kaynakAdi: "Omerli", dolulukOrani: 80.68 }] });
    };

    const first = await handleRequest(authorizedRequest("/iski/dams"), env, fetcher, cache);
    const second = await handleRequest(authorizedRequest("/iski/dams"), env, fetcher, cache);

    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    expect(upstreamCalls).toBe(1);
    expect(second.headers.get("Cache-Control")).toBe("no-store");
  });

  it("refreshes both relay cache entries for deployment warm-up", async () => {
    const stored: string[] = [];
    const cache: RelayCache = {
      async match() {
        return undefined;
      },
      async put(request) {
        const url = request instanceof Request ? request.url : request instanceof URL ? request.href : String(request);
        stored.push(new URL(url).pathname);
      },
    };
    const fetcher: RelayFetch = async (input) => {
      if (String(input).includes("baraj-doluluk")) {
        return new Response(
          '<table class="resultTable"><tbody><tr><td>Omerli</td><td>244540000</td><td>80.68</td><td>-</td></tr></tbody></table>',
        );
      }
      return new Response(
        '<table class="resultTable"><tbody><tr><td>FATİH - BALAT</td><td>BALAT MAH</td><td>23/07/2026 13:00:08</td><td>23/07/2026 19:00:00</td><td>-</td></tr></tbody></table>',
      );
    };

    await refreshRelayCache(env, fetcher, cache);

    expect(stored.sort()).toEqual(["/v4/iski/dams", "/v4/iski/faults"]);
  });

  it("returns stale cache immediately and refreshes it in the background", async () => {
    let upstreamCalls = 0;
    let pending: Promise<unknown> | undefined;
    let cached = Response.json(
      { relay_source: "edevlet", data: [{ kaynakAdi: "Old" }] },
      { headers: { "X-Relay-Cached-At": "2000-01-01T00:00:00.000Z" } },
    );
    const cache: RelayCache = {
      async match() {
        return cached.clone();
      },
      async put(_request, response) {
        cached = response.clone();
      },
    };
    const fetcher: RelayFetch = async () => {
      upstreamCalls += 1;
      return Response.json({ data: [{ kaynakAdi: "Omerli", dolulukOrani: 80.68 }] });
    };

    const response = await handleRequest(authorizedRequest("/iski/dams"), env, fetcher, cache, (promise) => {
      pending = promise;
    });

    await expect(response.json()).resolves.toMatchObject({ data: [{ kaynakAdi: "Old" }] });
    await pending;
    expect(upstreamCalls).toBe(1);
    await expect(cached.clone().json()).resolves.toMatchObject({ data: [{ kaynakAdi: "Omerli" }] });
  });

  it("never stores upstream error responses in the internal cache", async () => {
    let puts = 0;
    const cache: RelayCache = {
      async match() {
        return undefined;
      },
      async put() {
        puts += 1;
      },
    };
    const fetcher: RelayFetch = async () => new Response("blocked", { status: 503 });

    const response = await handleRequest(authorizedRequest("/iski/dams"), env, fetcher, cache);

    expect(response.status).toBe(502);
    expect(puts).toBe(0);
  });

  it("shares cached responses through the KV adapter", async () => {
    const values = new Map<string, string>();
    const kv: RelayKv = {
      async get(key) {
        return values.get(key) ?? null;
      },
      async put(key, value) {
        values.set(key, value);
      },
    };
    const cache = createKvCache(kv);
    const key = new Request("https://cache.example/v4/iski/dams");

    await cache.put(
      key,
      Response.json({ relay_source: "iski", data: [] }, { headers: { "X-Relay-Cached-At": "2026-07-23T12:00:00Z" } }),
    );
    const cached = await cache.match(key);

    expect(cached?.status).toBe(200);
    await expect(cached?.json()).resolves.toEqual({ relay_source: "iski", data: [] });
    expect(cached?.headers.get("X-Relay-Cached-At")).toBe("2026-07-23T12:00:00Z");
  });

  it("marks stale KV payloads with their capture time", async () => {
    let cached = Response.json(
      { relay_source: "iski", data: [] },
      { headers: { "X-Relay-Cached-At": "2000-01-01T00:00:00.000Z" } },
    );
    const cache: RelayCache = {
      async match() {
        return cached.clone();
      },
      async put(_request, response) {
        cached = response.clone();
      },
    };

    const response = await handleRequest(authorizedRequest("/iski/dams"), env, async () => Response.json({}), cache);
    const payload = (await response.json()) as Record<string, unknown>;

    expect(payload.relay_cache_status).toBe("stale");
    expect(payload.relay_cached_at).toBe("2000-01-01T00:00:00.000Z");
  });

  it("bypasses KV read failures and still serves upstream data", async () => {
    const cache: RelayCache = {
      async match() {
        throw new Error("KV unavailable");
      },
      async put() {},
    };
    const html = `<table class="resultTable"><tbody><tr>
      <td>FATİH - BALAT</td><td>BALAT MAH</td><td>23/07/2026 13:00:08</td><td>23/07/2026 19:00:00</td><td>-</td>
    </tr></tbody></table>`;

    const response = await handleRequest(authorizedRequest("/iski/faults"), env, async () => new Response(html), cache);

    expect(response.status).toBe(200);
  });

  it("does not discard a healthy upstream response when KV writes fail", async () => {
    const cache: RelayCache = {
      async match() {
        return undefined;
      },
      async put() {
        throw new Error("KV unavailable");
      },
    };
    const html = `<table class="resultTable"><tbody><tr>
      <td>FATİH - BALAT</td><td>BALAT MAH</td><td>23/07/2026 13:00:08</td><td>23/07/2026 19:00:00</td><td>-</td>
    </tr></tbody></table>`;

    const response = await handleRequest(authorizedRequest("/iski/faults"), env, async () => new Response(html), cache);

    expect(response.status).toBe(200);
  });

  it("rejects structurally invalid JSON without caching it", async () => {
    let puts = 0;
    let calls = 0;
    const cache: RelayCache = {
      async match() {
        return undefined;
      },
      async put() {
        puts += 1;
      },
    };
    const fetcher: RelayFetch = async () => {
      calls += 1;
      if (calls === 1) throw new DOMException("Timed out", "TimeoutError");
      return Response.json({ unexpected: true });
    };

    const response = await handleRequest(authorizedRequest("/iski/dams"), env, fetcher, cache);

    expect(response.status).toBe(502);
    expect(puts).toBe(0);
  });

  it("rejects invalid dam rows without caching them", async () => {
    let puts = 0;
    const cache: RelayCache = {
      async match() {
        return undefined;
      },
      async put() {
        puts += 1;
      },
    };
    const fetcher: RelayFetch = async () => Response.json({ data: ["invalid"] });

    const response = await handleRequest(authorizedRequest("/iski/dams"), env, fetcher, cache);

    expect(response.status).toBe(502);
    expect(puts).toBe(0);
  });

  it("stops reading chunked responses after the size limit", async () => {
    let calls = 0;
    const fetcher: RelayFetch = async () => {
      calls += 1;
      if (calls === 1) throw new DOMException("Timed out", "TimeoutError");
      const chunk = new Uint8Array(1024 * 1024);
      return new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(chunk);
            controller.enqueue(chunk);
            controller.enqueue(new Uint8Array(1));
            controller.close();
          },
        }),
      );
    };

    const response = await handleRequest(authorizedRequest("/iski/dams"), env, fetcher);

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({ error: "Upstream response is too large" });
  });
});
