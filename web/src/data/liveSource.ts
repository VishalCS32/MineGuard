/**
 * Live backend feed: REST for history, WebSocket for the running view.
 *
 * The server is the authority. It decodes the gateway's frames, scores risk,
 * raises alerts and assembles the snapshot, so this class does no interpretation
 * at all -- it transports. That is deliberate: the web dashboard and the Android
 * app must never be able to disagree about whether a panel is in trouble.
 *
 * Reconnection is automatic with backoff, and every reconnect is answered with a
 * full snapshot rather than a delta, so a client that missed an hour of updates
 * is immediately correct instead of applying changes to stale state. Mine sites
 * lose connectivity; the dashboard has to survive it without lying.
 */
import type { Snapshot, TrendPoint } from './types';
import type { DataSource, SourceStatus } from './source';

const HISTORY_TTL_MS = 4000;
const MAX_BACKOFF_MS = 15_000;

export class LiveSource implements DataSource {
  readonly kind = 'live' as const;

  private socket: WebSocket | null = null;
  private readonly listeners = new Set<(s: Snapshot) => void>();
  private readonly statusListeners = new Set<(s: SourceStatus) => void>();
  private readonly historyCache = new Map<number, { at: number; points: TrendPoint[] }>();
  private readonly inFlight = new Set<number>();
  private last: Snapshot | null = null;
  private retry = 0;
  private timer: number | null = null;
  private stopped = false;

  constructor(private readonly baseUrl = '') {}

  private get wsUrl(): string {
    if (this.baseUrl) {
      return `${this.baseUrl.replace(/^http/, 'ws')}/ws/live`;
    }
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${location.host}/ws/live`;
  }

  // --------------------------------------------------------------- lifecycle
  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer !== null) window.clearTimeout(this.timer);
    this.timer = null;
    this.socket?.close();
    this.socket = null;
  }

  private connect(): void {
    if (this.stopped || this.socket) return;
    let socket: WebSocket;
    try {
      socket = new WebSocket(this.wsUrl);
    } catch {
      this.scheduleReconnect('could not open socket');
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      this.retry = 0;
      this.emitStatus({ kind: 'live', connected: true });
    };

    socket.onmessage = (ev) => {
      let payload: unknown;
      try {
        payload = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      // Keep-alives exist so idle proxies do not drop a quiet socket.
      if (payload && typeof payload === 'object' && (payload as { type?: string }).type === 'ping') {
        return;
      }
      const snapshot = payload as Snapshot;
      if (!Array.isArray(snapshot?.nodes)) return;
      this.last = snapshot;
      this.listeners.forEach((fn) => fn(snapshot));
    };

    socket.onclose = () => {
      this.socket = null;
      this.scheduleReconnect('backend unreachable');
    };
    socket.onerror = () => socket.close();
  }

  private scheduleReconnect(detail: string): void {
    this.emitStatus({ kind: 'live', connected: false, detail });
    if (this.stopped) return;
    // Exponential backoff, capped: a mine site can be offline for a long time
    // and hammering a dead endpoint helps nobody.
    const delay = Math.min(MAX_BACKOFF_MS, 500 * 2 ** this.retry++);
    this.timer = window.setTimeout(() => this.connect(), delay);
  }

  // ------------------------------------------------------------ subscription
  subscribe(fn: (s: Snapshot) => void): () => void {
    this.listeners.add(fn);
    if (this.last) fn(this.last);
    return () => this.listeners.delete(fn);
  }

  onStatus(fn: (s: SourceStatus) => void): () => void {
    this.statusListeners.add(fn);
    fn({ kind: 'live', connected: this.socket?.readyState === WebSocket.OPEN });
    return () => this.statusListeners.delete(fn);
  }

  private emitStatus(status: SourceStatus): void {
    this.statusListeners.forEach((fn) => fn(status));
  }

  // ---------------------------------------------------------------- history
  /**
   * Cached per node. Returns what is known now and refreshes in the background,
   * so switching nodes never blanks the chart waiting on a round trip.
   */
  history(addr: number): TrendPoint[] {
    const entry = this.historyCache.get(addr);
    const stale = !entry || Date.now() - entry.at > HISTORY_TTL_MS;
    if (stale && !this.inFlight.has(addr)) void this.fetchHistory(addr);
    return entry?.points ?? [];
  }

  private async fetchHistory(addr: number): Promise<void> {
    this.inFlight.add(addr);
    try {
      const res = await fetch(`${this.baseUrl}/api/nodes/${addr}/history?range=7D`);
      if (!res.ok) return;
      const points = (await res.json()) as TrendPoint[];
      this.historyCache.set(addr, { at: Date.now(), points });
    } catch {
      // Offline: keep serving the last good history rather than emptying it.
    } finally {
      this.inFlight.delete(addr);
    }
  }
}
