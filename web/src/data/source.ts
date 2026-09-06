/** The seam between the dashboard and wherever its data comes from. */
import type { Snapshot, TrendPoint } from './types';

export type SourceKind = 'live' | 'simulated';

export interface SourceStatus {
  kind: SourceKind;
  connected: boolean;
  /** Human-readable reason, shown in the header when not connected. */
  detail?: string;
}

export interface DataSource {
  readonly kind: SourceKind;
  subscribe(fn: (s: Snapshot) => void): () => void;
  onStatus(fn: (s: SourceStatus) => void): () => void;
  history(addr: number): TrendPoint[];
  start(): void;
  stop(): void;
  /** Simulator-only: cut a node's power to demonstrate mesh re-routing. */
  toggleNode?(addr: number): void;
}
