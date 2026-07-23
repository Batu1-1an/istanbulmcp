const UPSTREAMS = {
  "/iski/faults": "https://harita.iski.gov.tr/data/mahallelerKesinti.geojson",
  "/iski/dams": "https://harita.iski.gov.tr/data/baraj.json",
} as const;

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const UPSTREAM_TIMEOUT_MS = 4_000;
const EDEVLET_FAULTS_URL =
  "https://www.turkiye.gov.tr/istanbul-su-ve-kanalizasyon-idaresi-ariza-bakim-bilgisi-sorgulama";
const EDEVLET_DAMS_URL = "https://www.turkiye.gov.tr/istanbul-su-ve-kanalizasyon-idaresi-baraj-doluluk-oranlari";

type RelayPath = keyof typeof UPSTREAMS;

export type RelayEnv = {
  CACHE: KVNamespace;
  RELAY_TOKEN: string;
};

export type RelayFetch = typeof fetch;
export type RelayCache = Pick<Cache, "match" | "put">;
export type RelayKv = {
  get(key: string): Promise<string | null>;
  put(key: string, value: string, options?: { expirationTtl: number }): Promise<void>;
};

const CACHE_FRESH_SECONDS = 300;
const CACHE_RETENTION_SECONDS = 86_400;

function cacheKey(pathname: RelayPath): Request {
  return new Request(`https://iski-relay-cache.internal/v4${pathname}`);
}

export function createKvCache(kv: RelayKv): RelayCache {
  return {
    async match(request) {
      const url = request instanceof Request ? request.url : request instanceof URL ? request.href : String(request);
      const value = await kv.get(new URL(url).pathname);
      if (!value) return undefined;
      const cached = JSON.parse(value) as {
        body: string;
        cachedAt: string;
        contentType: string;
        status: number;
      };
      return new Response(cached.body, {
        status: cached.status,
        headers: {
          "Cache-Control": `max-age=${CACHE_RETENTION_SECONDS}`,
          "Content-Type": cached.contentType,
          "X-Relay-Cached-At": cached.cachedAt,
        },
      });
    },
    async put(request, response) {
      const url = request instanceof Request ? request.url : request instanceof URL ? request.href : String(request);
      await kv.put(
        new URL(url).pathname,
        JSON.stringify({
          body: await response.clone().text(),
          cachedAt: response.headers.get("X-Relay-Cached-At") ?? new Date().toISOString(),
          contentType: response.headers.get("Content-Type") ?? "application/json; charset=utf-8",
          status: response.status,
        }),
        { expirationTtl: CACHE_RETENTION_SECONDS },
      );
    },
  };
}

function noStoreResponse(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.set("Cache-Control", "no-store");
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

async function cacheResponse(cache: RelayCache, pathname: RelayPath, response: Response): Promise<void> {
  const cached = response.clone();
  const headers = new Headers(cached.headers);
  headers.set("Cache-Control", `max-age=${CACHE_RETENTION_SECONDS}`);
  headers.set("X-Relay-Cached-At", new Date().toISOString());
  await cache.put(
    cacheKey(pathname),
    new Response(cached.body, { status: cached.status, statusText: cached.statusText, headers }),
  );
}

function cacheIsFresh(response: Response): boolean {
  const cachedAt = response.headers.get("X-Relay-Cached-At");
  if (!cachedAt) return true;
  const cachedAtMs = Date.parse(cachedAt);
  return Number.isFinite(cachedAtMs) && Date.now() - cachedAtMs <= CACHE_FRESH_SECONDS * 1000;
}

function jsonError(error: string, status: number, headers?: HeadersInit): Response {
  return Response.json(
    { error },
    {
      status,
      headers: {
        "Cache-Control": "no-store",
        ...headers,
      },
    },
  );
}

async function tokensMatch(provided: string, expected: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return crypto.subtle.timingSafeEqual(providedHash, expectedHash);
}

function isRelayPath(pathname: string): pathname is RelayPath {
  return Object.hasOwn(UPSTREAMS, pathname);
}

function isTimeout(error: unknown): boolean {
  return error instanceof DOMException && (error.name === "TimeoutError" || error.name === "AbortError");
}

class RelayUpstreamError extends Error {
  constructor(
    message: string,
    readonly status: 502 | 504,
  ) {
    super(message);
    this.name = "RelayUpstreamError";
  }
}

async function readBoundedBody(response: Response): Promise<ArrayBuffer> {
  const declaredLength = Number(response.headers.get("Content-Length") ?? 0);
  if (declaredLength > MAX_RESPONSE_BYTES) {
    throw new RelayUpstreamError("Upstream response is too large", 502);
  }
  if (!response.body) return new ArrayBuffer(0);
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_RESPONSE_BYTES) {
      await reader.cancel();
      throw new RelayUpstreamError("Upstream response is too large", 502);
    }
    chunks.push(value);
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body.buffer;
}

async function fetchJson(pathname: RelayPath, upstreamUrl: string, fetcher: RelayFetch): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await fetcher(upstreamUrl, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (error) {
    if (isTimeout(error)) {
      throw new RelayUpstreamError("Upstream request timed out", 504);
    }
    throw new RelayUpstreamError("Upstream request failed", 502);
  }
  if (!upstream.ok) {
    throw new RelayUpstreamError("Upstream request failed", 502);
  }

  const body = await readBoundedBody(upstream);
  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder().decode(body));
  } catch {
    throw new RelayUpstreamError("Upstream returned invalid JSON", 502);
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new RelayUpstreamError("Upstream returned invalid JSON", 502);
  }
  if (pathname === "/iski/faults") {
    const faults = payload as { type?: unknown; features?: unknown };
    if (
      faults.type !== "FeatureCollection" ||
      !Array.isArray(faults.features) ||
      faults.features.some((feature) => {
        if (!feature || typeof feature !== "object" || Array.isArray(feature)) return true;
        const { properties, geometry } = feature as { properties?: unknown; geometry?: unknown };
        return (
          !properties ||
          typeof properties !== "object" ||
          Array.isArray(properties) ||
          (geometry !== null && geometry !== undefined && (typeof geometry !== "object" || Array.isArray(geometry)))
        );
      })
    ) {
      throw new RelayUpstreamError("Upstream returned an invalid faults payload", 502);
    }
  } else {
    const rows = (payload as { data?: unknown }).data;
    if (
      !Array.isArray(rows) ||
      rows.some((row) => !row || typeof row !== "object" || Array.isArray(row))
    ) {
      throw new RelayUpstreamError("Upstream returned an invalid dams payload", 502);
    }
  }
  return Response.json({ ...payload, relay_source: "iski" }, {
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function decodeHtml(value: string): string {
  const entities: Record<string, string> = {
    amp: "&",
    apos: "'",
    gt: ">",
    lt: "<",
    nbsp: " ",
    quot: '"',
  };
  return value
    .replace(/<[^>]+>/g, " ")
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (_match, entity: string) => {
      if (entity.startsWith("#x")) return String.fromCodePoint(Number.parseInt(entity.slice(2), 16));
      if (entity.startsWith("#")) return String.fromCodePoint(Number.parseInt(entity.slice(1), 10));
      return entities[entity.toLowerCase()] ?? "";
    })
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeDate(value: string): string {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})(?:\s+(\d{2}:\d{2}:\d{2}))?$/.exec(value.trim());
  if (!match) return value;
  return `${match[3]}-${match[2]}-${match[1]}${match[4] ? ` ${match[4]}` : ""}`;
}

export function parseEdevletFaults(html: string): object {
  const table = /<table[^>]*class=["'][^"']*resultTable[^"']*["'][^>]*>([\s\S]*?)<\/table>/i.exec(html);
  if (!table) {
    throw new RelayUpstreamError("Official fallback table is unavailable", 502);
  }

  const features: object[] = [];
  for (const rowMatch of table[1].matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells = [...rowMatch[1].matchAll(/<td[^>]*>([\s\S]*?)<\/td>/gi)].map((match) => decodeHtml(match[1]));
    if (cells.length !== 5) continue;
    const district = cells[0].split(/\s+-\s+/, 1)[0].trim();
    const description = cells[4] && cells[4] !== "-" ? cells[4] : cells[0];
    const neighborhoods = [...new Set(cells[1].split(",").map((value) => value.trim()).filter(Boolean))];
    for (const neighborhood of neighborhoods) {
      features.push({
        type: "Feature",
        properties: {
          ARIZA_NO: "",
          ILCE_KODU: null,
          ILCE_ADI: district,
          MAHALLE_KODU: null,
          MAHALLE_ADI: neighborhood,
          ARIZA_NEVI_ACIKLAMASI: description,
          BASLAMA_TARIHI: normalizeDate(cells[2]),
          TAHMINI_BITIS_TARIHI: normalizeDate(cells[3]),
        },
        geometry: null,
      });
    }
  }
  if (features.length === 0) {
    throw new RelayUpstreamError("Official fallback table contains no outage rows", 502);
  }
  return { type: "FeatureCollection", relay_source: "edevlet", features };
}

export function parseEdevletDams(html: string): object {
  const table = /<table[^>]*class=["'][^"']*resultTable[^"']*["'][^>]*>([\s\S]*?)<\/table>/i.exec(html);
  if (!table) throw new RelayUpstreamError("Official fallback table is unavailable", 502);

  const data: object[] = [];
  for (const rowMatch of table[1].matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells = [...rowMatch[1].matchAll(/<td[^>]*>([\s\S]*?)<\/td>/gi)].map((match) => decodeHtml(match[1]));
    if (cells.length !== 4) continue;
    const capacity = Number(cells[1].replace(",", "."));
    const occupancy = Number(cells[2].replace(",", "."));
    if (!cells[0] || !Number.isFinite(capacity) || !Number.isFinite(occupancy)) continue;
    data.push({
      kaynakAdi: cells[0],
      baslikAdi: cells[0],
      biriktirmeHacmi: capacity / 1_000_000,
      dolulukOrani: occupancy,
    });
  }
  if (data.length === 0) throw new RelayUpstreamError("Official fallback table contains no dam rows", 502);
  return { relay_source: "edevlet", data };
}

async function fetchEdevletFaults(fetcher: RelayFetch): Promise<Response> {
  let response: Response;
  try {
    response = await fetcher(EDEVLET_FAULTS_URL, {
      headers: { Accept: "text/html" },
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (error) {
    if (isTimeout(error)) throw new RelayUpstreamError("Upstream request timed out", 504);
    throw new RelayUpstreamError("Upstream request failed", 502);
  }
  if (!response.ok) throw new RelayUpstreamError("Upstream request failed", 502);
  const html = new TextDecoder().decode(await readBoundedBody(response));
  return Response.json(parseEdevletFaults(html), {
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

async function fetchEdevletDams(fetcher: RelayFetch): Promise<Response> {
  let response: Response;
  try {
    response = await fetcher(EDEVLET_DAMS_URL, {
      headers: { Accept: "text/html" },
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (error) {
    if (isTimeout(error)) throw new RelayUpstreamError("Upstream request timed out", 504);
    throw new RelayUpstreamError("Upstream request failed", 502);
  }
  if (!response.ok) throw new RelayUpstreamError("Upstream request failed", 502);
  const html = new TextDecoder().decode(await readBoundedBody(response));
  return Response.json(parseEdevletDams(html), {
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

async function loadRelayResponse(pathname: RelayPath, fetcher: RelayFetch): Promise<Response> {
  const edevletSource = pathname === "/iski/faults" ? "edevlet_faults" : "edevlet_dams";
  const iskiSource = pathname === "/iski/faults" ? "iski_faults" : "iski_dams";
  if (pathname === "/iski/dams") {
    try {
      return await fetchJson(pathname, UPSTREAMS[pathname], fetcher);
    } catch (error) {
      const errorType = error instanceof Error ? error.name : typeof error;
      console.error(JSON.stringify({ event: "relay_upstream_exception", source: iskiSource, error_type: errorType }));
    }
    try {
      return await fetchEdevletDams(fetcher);
    } catch (error) {
      const errorType = error instanceof Error ? error.name : typeof error;
      console.error(JSON.stringify({ event: "relay_upstream_exception", source: edevletSource, error_type: errorType }));
      if (error instanceof RelayUpstreamError) return jsonError(error.message, error.status);
      return jsonError("Upstream request failed", 502);
    }
  }

  try {
    return await fetchEdevletFaults(fetcher);
  } catch (error) {
    const errorType = error instanceof Error ? error.name : typeof error;
    console.error(JSON.stringify({ event: "relay_upstream_exception", source: edevletSource, error_type: errorType }));
  }

  try {
    return await fetchJson(pathname, UPSTREAMS[pathname], fetcher);
  } catch (error) {
    const errorType = error instanceof Error ? error.name : typeof error;
    console.error(JSON.stringify({ event: "relay_upstream_exception", source: iskiSource, error_type: errorType }));
    if (error instanceof RelayUpstreamError) return jsonError(error.message, error.status);
    return jsonError("Upstream request failed", 502);
  }
}

async function refreshRelayPath(pathname: RelayPath, fetcher: RelayFetch, cache: RelayCache): Promise<void> {
  const response = await loadRelayResponse(pathname, fetcher);
  if (response.ok) await cacheResponse(cache, pathname, response);
}

export async function handleRequest(
  request: Request,
  env: RelayEnv,
  fetcher: RelayFetch = fetch,
  cache?: RelayCache,
  waitUntil?: (promise: Promise<unknown>) => void,
): Promise<Response> {
  const { pathname } = new URL(request.url);

  if (request.method !== "GET") {
    return jsonError("Method not allowed", 405, { Allow: "GET" });
  }
  if (pathname === "/healthz") {
    return Response.json({ ok: true, service: "istanbul-iski-relay" });
  }
  if (!isRelayPath(pathname)) {
    return jsonError("Not found", 404);
  }
  if (!env.RELAY_TOKEN) {
    console.error(JSON.stringify({ event: "relay_configuration_error", binding: "RELAY_TOKEN" }));
    return jsonError("Relay is not configured", 500);
  }

  const authorization = request.headers.get("Authorization") ?? "";
  const expected = `Bearer ${env.RELAY_TOKEN}`;
  if (!(await tokensMatch(authorization, expected))) {
    return jsonError("Unauthorized", 401);
  }

  if (cache) {
    try {
      const cached = await cache.match(cacheKey(pathname));
      if (cached) {
        const fresh = cacheIsFresh(cached);
        if (!fresh && waitUntil) {
          waitUntil(refreshRelayPath(pathname, fetcher, cache));
        }
        const cachedAt = cached.headers.get("X-Relay-Cached-At");
        const payload = (await cached.clone().json()) as Record<string, unknown>;
        return noStoreResponse(
          Response.json({
            ...payload,
            relay_cache_status: fresh ? "fresh" : "stale",
            relay_cached_at: cachedAt,
          }),
        );
      }
    } catch (error) {
      console.error(
        JSON.stringify({
          event: "relay_cache_read_failed",
          error_type: error instanceof Error ? error.name : typeof error,
        }),
      );
    }
  }

  const response = await loadRelayResponse(pathname, fetcher);
  if (cache && response.ok) {
    try {
      await cacheResponse(cache, pathname, response);
    } catch (error) {
      console.error(
        JSON.stringify({
          event: "relay_cache_write_failed",
          error_type: error instanceof Error ? error.name : typeof error,
        }),
      );
    }
  }
  return response;
}

export async function refreshRelayCache(
  env: RelayEnv,
  fetcher: RelayFetch,
  cache: RelayCache,
): Promise<void> {
  await Promise.all(
    (Object.keys(UPSTREAMS) as RelayPath[]).map((pathname) => refreshRelayPath(pathname, fetcher, cache)),
  );
}

export default {
  fetch(request: Request, env: RelayEnv, ctx?: ExecutionContext): Promise<Response> {
    return handleRequest(
      request,
      env,
      fetch,
      createKvCache(env.CACHE),
      ctx ? (promise) => ctx.waitUntil(promise) : undefined,
    );
  },
} satisfies ExportedHandler<RelayEnv>;
