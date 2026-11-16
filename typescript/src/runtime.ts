// HTTP transport shared by every client: auth, Dynasty-Id, ETag caching,
// retries, timeouts and typed errors.

export const DEFAULT_BASE_URL = "https://dynasty.prestonchoate.dev";
export const VERSION = "0.1.0";

export interface ClientOptions {
  /** A dynasty key (`cfbk_…`) or partner key (`cfbp_…`). */
  apiKey: string;
  /** Site root, without `/v1`. Default: https://dynasty.prestonchoate.dev */
  baseUrl?: string;
  /** Per-attempt timeout in milliseconds. */
  timeoutMs?: number;
  /**
   * Retries for rate limits (429, when Retry-After is short enough) and, for
   * GET requests, network errors and 502/503/504. Default 2.
   */
  maxRetries?: number;
  /** Longest Retry-After to wait out automatically, in ms. Default 60 000. */
  maxRetryWaitMs?: number;
  /**
   * Cache GET responses by ETag and revalidate with If-None-Match, so
   * unchanged data costs a 304 instead of a full body. `true` (default) keeps
   * up to 256 responses; a number sets the size; `false` turns it off.
   */
  etagCache?: boolean | number;
  /** A fetch implementation. Default: globalThis.fetch. */
  fetch?: typeof fetch;
  /** Extra headers on every request. */
  headers?: Record<string, string>;
}

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Extra headers for this request. */
  headers?: Record<string, string>;
}

interface InternalRequest extends RequestOptions {
  query?: object;
  body?: unknown;
}

/** An error response from the API. `code` is stable and machine-readable. */
export class DynastyApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** Seconds from the Retry-After header, when present. */
  readonly retryAfter?: number;
  readonly body: unknown;

  constructor(status: number, code: string, message: string, retryAfter?: number, body?: unknown) {
    super(message);
    this.name = new.target.name;
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
    this.body = body;
  }
}

export class BadRequestError extends DynastyApiError {}
export class AuthenticationError extends DynastyApiError {}
export class PermissionDeniedError extends DynastyApiError {}
export class NotFoundError extends DynastyApiError {}
export class ConflictError extends DynastyApiError {}
export class RateLimitError extends DynastyApiError {}
export class ServerError extends DynastyApiError {}

/** The request never got a response: network failure or timeout. */
export class ConnectionError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "ConnectionError";
  }
}

function errorFor(status: number, code: string, message: string, retryAfter?: number, body?: unknown): DynastyApiError {
  const cls =
    status === 400 ? BadRequestError
    : status === 401 ? AuthenticationError
    : status === 403 ? PermissionDeniedError
    : status === 404 ? NotFoundError
    : status === 409 ? ConflictError
    : status === 429 ? RateLimitError
    : status >= 500 ? ServerError
    : DynastyApiError;
  return new cls(status, code, message, retryAfter, body);
}

class EtagCache {
  private entries = new Map<string, { etag: string; body: string }>();
  constructor(private readonly size: number) {}

  get(key: string) {
    const e = this.entries.get(key);
    if (e) {
      this.entries.delete(key); // move to the newest end
      this.entries.set(key, e);
    }
    return e;
  }

  set(key: string, etag: string, body: string) {
    this.entries.delete(key);
    this.entries.set(key, { etag, body });
    while (this.entries.size > this.size) {
      this.entries.delete(this.entries.keys().next().value!);
    }
  }
}

interface Shared {
  apiKey: string;
  baseUrl: string;
  timeoutMs: number;
  maxRetries: number;
  maxRetryWaitMs: number;
  fetch: typeof fetch;
  headers: Record<string, string>;
  cache?: EtagCache;
}

const isNode = typeof process !== "undefined" && !!process.versions?.node;
const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(signal.reason);
    }, { once: true });
  });

function retryAfterSeconds(h: string | null): number | undefined {
  if (!h) return undefined;
  const n = Number(h);
  if (Number.isFinite(n)) return Math.max(0, n);
  const at = Date.parse(h);
  return Number.isNaN(at) ? undefined : Math.max(0, (at - Date.now()) / 1000);
}

/** Base class for the generated endpoint classes. */
export abstract class Transport {
  /** @internal */
  protected readonly shared: Shared;
  /** @internal */
  protected dynastyId?: number;
  /** @internal */
  protected readonly basePath: string;

  /** @internal */
  protected constructor(options: ClientOptions, basePath: string, defaultTimeoutMs: number) {
    if (!options?.apiKey) throw new TypeError("apiKey is required");
    const f = options.fetch ?? globalThis.fetch;
    if (!f) throw new TypeError("no fetch available; pass options.fetch");
    const size = options.etagCache === false ? 0 : typeof options.etagCache === "number" ? options.etagCache : 256;
    this.basePath = basePath;
    this.shared = {
      apiKey: options.apiKey,
      baseUrl: (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, ""),
      timeoutMs: options.timeoutMs ?? defaultTimeoutMs,
      maxRetries: options.maxRetries ?? 2,
      maxRetryWaitMs: options.maxRetryWaitMs ?? 60_000,
      fetch: f.bind(globalThis),
      headers: { ...options.headers },
      cache: size > 0 ? new EtagCache(size) : undefined,
    };
  }

  /** @internal */
  protected async request<T>(method: string, path: string, req: InternalRequest = {}): Promise<T> {
    const s = this.shared;
    const url = new URL(s.baseUrl + this.basePath + path);
    for (const [k, v] of Object.entries(req.query ?? {})) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${s.apiKey}`,
      ...s.headers,
      ...req.headers,
    };
    // Browsers reject custom User-Agent in CORS preflights the API doesn't allow.
    if (isNode) headers["User-Agent"] = `cfb27-dynasty-ts/${VERSION}`;
    if (this.dynastyId !== undefined) headers["Dynasty-Id"] = String(this.dynastyId);
    let body: string | undefined;
    if (req.body !== undefined) {
      body = JSON.stringify(req.body);
      headers["Content-Type"] = "application/json";
    }
    const cacheKey = method === "GET" && s.cache ? `${this.dynastyId ?? ""} ${url}` : undefined;
    const cached = cacheKey ? s.cache!.get(cacheKey) : undefined;
    if (cached) headers["If-None-Match"] = cached.etag;

    for (let attempt = 0; ; attempt++) {
      const timeout = AbortSignal.timeout(req.timeoutMs ?? s.timeoutMs);
      const signal = req.signal ? AbortSignal.any([req.signal, timeout]) : timeout;
      let res: Response;
      try {
        res = await s.fetch(url, { method, headers, body, signal });
      } catch (err) {
        if (req.signal?.aborted) throw req.signal.reason;
        if (method === "GET" && attempt < s.maxRetries) {
          await sleep(backoff(attempt), req.signal);
          continue;
        }
        const what = timeout.aborted ? "timed out" : "failed";
        throw new ConnectionError(`${method} ${url.pathname} ${what}`, { cause: err });
      }

      if (res.status === 304 && cached) return JSON.parse(cached.body) as T;
      if (res.status === 204) return undefined as T;
      const text = await res.text();
      if (res.ok) {
        const etag = res.headers.get("ETag");
        if (cacheKey && etag) s.cache!.set(cacheKey, etag, text);
        return (text ? JSON.parse(text) : undefined) as T;
      }

      const retryAfter = retryAfterSeconds(res.headers.get("Retry-After"));
      const retryable =
        (res.status === 429 && retryAfter !== undefined && retryAfter * 1000 <= s.maxRetryWaitMs) ||
        (method === "GET" && [502, 503, 504].includes(res.status));
      if (retryable && attempt < s.maxRetries) {
        await sleep(retryAfter !== undefined ? retryAfter * 1000 : backoff(attempt), req.signal);
        continue;
      }
      let parsed: unknown = text;
      let code = `http_${res.status}`;
      let message = res.statusText || `HTTP ${res.status}`;
      try {
        parsed = JSON.parse(text);
        const e = (parsed as { error?: { code?: string; message?: string } }).error;
        if (e?.code) code = e.code;
        if (e?.message) message = e.message;
      } catch {
        // not JSON (proxy error page); keep the defaults
      }
      throw errorFor(res.status, code, message, retryAfter, parsed);
    }
  }
}

function backoff(attempt: number): number {
  return 500 * 2 ** attempt * (0.5 + Math.random() / 2);
}
