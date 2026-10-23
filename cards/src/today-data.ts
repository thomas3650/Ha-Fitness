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

/** The part of Home Assistant's websocket connection the subscription uses. */
export interface Connection {
  subscribeMessage<T>(callback: (message: T) => void, message: { type: string }): Promise<() => unknown>;
}

/**
 * The card's subscription to `ha_fitness/today/subscribe` (spec §4.5). It hands each message to
 * `onData`: the today data, or `null` while the add-on can't be reached. A subscription that fails
 * (the integration isn't loaded, say) counts as unreachable too.
 */
export class TodaySubscription {
  private connection?: Connection;
  private unsubscribe?: Promise<(() => unknown) | undefined>;

  constructor(private readonly onData: (today: Today | null) => void) {}

  /** Subscribe on this connection. Home Assistant keeps one connection, so the same one is a no-op. */
  connect(connection: Connection | undefined): void {
    if (!connection || connection === this.connection) return;
    this.disconnect();
    this.connection = connection;
    this.unsubscribe = connection
      .subscribeMessage<Today | null>((today) => this.onData(today), { type: "ha_fitness/today/subscribe" })
      .catch(() => {
        if (this.connection === connection) this.onData(null);
        return undefined;
      });
  }

  /** Stop the subscription, if there is one. */
  disconnect(): void {
    const unsubscribe = this.unsubscribe;
    this.connection = undefined;
    this.unsubscribe = undefined;
    // The connection may already be gone, and then unsubscribing fails; there is nothing left to stop.
    void unsubscribe
      ?.then(async (stop) => {
        await stop?.();
      })
      .catch(() => undefined);
  }
}
