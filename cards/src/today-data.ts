/** One open training day, as the add-on's `GET /api/v1/today` returns it (spec §3.5). */
export interface OpenDay {
  id: number;
  program_id: number;
  program_name: string;
  /** The day's date, `YYYY-MM-DD`. */
  date: string;
  state: "due" | "late";
  station_count: number;
  rounds: number;
  total_minutes: number;
}

/** What the add-on's `GET /api/v1/today` returns (spec §3.5). */
export interface Today {
  date: string;
  open: OpenDay[];
  next: { date: string; programs: string[] } | null;
}

/** The part of home-assistant-js-websocket's `Connection` the subscription uses. */
export interface Connection {
  subscribeMessage<T>(
    callback: (message: T) => void,
    message: { type: string },
    options?: { resubscribe?: boolean },
  ): Promise<() => unknown>;
  /** `ready` fires after the connection has reconnected. */
  addEventListener?(type: "ready", callback: () => void): void;
  removeEventListener?(type: "ready", callback: () => void): void;
}

type Subscription = Promise<(() => unknown) | undefined>;

/** The waits before the retries of a refused subscription; the last one repeats. */
const RETRY_MS = [5_000, 10_000, 30_000];

/**
 * The card's subscription to `ha_fitness/today/subscribe` (spec §4.5). It hands each message to
 * `onData`: the today data, or `null` while the add-on can't be reached.
 *
 * - A refused subscription (the integration isn't loaded, say) counts as unreachable, and is
 *   retried after 5, 10 and 30 s, then every 30 s.
 * - After a reconnect (the connection's `ready` event) it subscribes again, so a restart of Home
 *   Assistant can't leave the card on stale data.
 * - Only the newest subscription's messages count.
 */
export class TodaySubscription {
  private connection?: Connection;
  private current?: Subscription;
  private retries = 0;
  private retryTimer?: ReturnType<typeof setTimeout>;
  private readonly onReady = (): void => {
    this.drop();
    this.subscribe();
  };

  constructor(private readonly onData: (today: Today | null) => void) {}

  /** Subscribe on this connection. Home Assistant keeps one connection, so the same one is a no-op. */
  connect(connection: Connection | undefined): void {
    if (!connection || connection === this.connection) return;
    this.disconnect();
    this.connection = connection;
    connection.addEventListener?.("ready", this.onReady);
    this.subscribe();
  }

  /** Stop the subscription, its retries and the reconnect listener. */
  disconnect(): void {
    this.connection?.removeEventListener?.("ready", this.onReady);
    this.connection = undefined;
    this.drop();
  }

  private subscribe(): void {
    const connection = this.connection;
    if (!connection) return;
    const subscription: Subscription = connection
      .subscribeMessage<Today | null>(
        (today) => {
          if (this.current === subscription) this.onData(today);
        },
        { type: "ha_fitness/today/subscribe" },
        // The `ready` handler subscribes again itself; the library's own resubscribe would leave an
        // extra server subscription behind after each reconnect.
        { resubscribe: false },
      )
      .catch(() => {
        if (this.current === subscription) {
          this.onData(null);
          this.retryLater();
        }
        return undefined;
      });
    this.current = subscription;
  }

  private retryLater(): void {
    const delay = RETRY_MS[Math.min(this.retries, RETRY_MS.length - 1)];
    this.retries += 1;
    this.retryTimer = setTimeout(() => this.subscribe(), delay);
  }

  /** Stop the current subscription and any retry; the next refusal starts the waits over. */
  private drop(): void {
    clearTimeout(this.retryTimer);
    this.retryTimer = undefined;
    this.retries = 0;
    const subscription = this.current;
    this.current = undefined;
    // The connection may already be gone, and then unsubscribing fails; there is nothing left to stop.
    void subscription
      ?.then(async (stop) => {
        await stop?.();
      })
      .catch(() => undefined);
  }
}
