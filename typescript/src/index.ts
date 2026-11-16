import { DynastyAPI } from "./generated/v1.js";
import { PartnerAPI } from "./generated/partner.js";
import type { ClientOptions } from "./runtime.js";

export * from "./runtime.js";
export * from "./generated/v1.js";
export * from "./generated/partner.js";

export interface DynastyClientOptions extends ClientOptions {
  /**
   * The dynasty to read. Required with a partner key (`cfbp_…`); a dynasty
   * key (`cfbk_…`) names its own dynasty and ignores this.
   */
  dynastyId?: number;
}

/**
 * Reads one dynasty's cached data from `/v1`.
 *
 * ```ts
 * const client = new DynastyClient({ apiKey: process.env.DYNASTY_API_KEY! });
 * const { data: games } = await client.listSchedule({ week: 3 });
 * ```
 */
export class DynastyClient extends DynastyAPI {
  constructor(options: DynastyClientOptions) {
    super(options, "/v1", 30_000);
    this.dynastyId = options.dynastyId;
  }

  /**
   * A client for another dynasty that shares this one's key, settings and
   * ETag cache. Use it with a partner key to read each dynasty you have
   * access to.
   */
  withDynasty(dynastyId: number): DynastyClient {
    const c = Object.create(Object.getPrototypeOf(this)) as DynastyClient;
    Object.assign(c, this);
    c.dynastyId = dynastyId;
    return c;
  }
}

/**
 * Calls the partner API (`/partner/v1`) with a partner key (`cfbp_…`).
 * Requests that reach EA can take up to 150 s, so the default timeout is
 * 180 s.
 */
export class PartnerClient extends PartnerAPI {
  private readonly options: ClientOptions;

  constructor(options: ClientOptions) {
    super(options, "/partner/v1", 180_000);
    this.options = options;
  }

  /** A `/v1` client that reads `dynastyId` with this partner key. */
  dynasty(dynastyId: number): DynastyClient {
    return new DynastyClient({ ...this.options, timeoutMs: this.options.timeoutMs ?? 30_000, dynastyId });
  }
}
