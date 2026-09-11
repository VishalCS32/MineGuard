/**
 * Type contracts for Node 1 Telemetry API and MineGuard backend.
 *
 * Grounded strictly in the live backend payloads returned by:
 * - https://mineguard-api.tenant.eu.org/api/v1/nodes/NODE-001/latest
 * - http://localhost:8000/api/nodes/NODE-001/latest
 * - http://localhost:8000/api/snapshot
 * - http://localhost:8000/api/nodes/NODE-001/history
 */

export interface RemoteTelemetryFrame {
  node_id: string;
  timestamp: string; // ISO 8601 UTC string (e.g. 2026-09-10T19:27:20.806Z)
  gyro: {
    x: number; // deg/s
    y: number; // deg/s
    z: number; // deg/s
  };
  accel: {
    x: number; // m/s^2
    y: number; // m/s^2
    z: number; // m/s^2 (~9.8 m/s^2 nominal)
  };
  orientation: {
    roll: number;  // degrees
    pitch: number; // degrees
  };
  vibration: {
    x: number;   // g
    y: number;   // g
    z: number;   // g
    rms: number; // g
  };
  gps: {
    latitude: number;   // decimal degrees
    longitude: number;  // decimal degrees
    altitude: number;   // meters
    satellites: number; // count
    hdop: number;       // horizontal dilution of precision
  };
  ml: {
    condition: 'normal' | 'warning' | 'critical';
    anomaly: boolean;
    anomaly_score: number; // 0.000 to 1.000
  };
}

export interface BackendHealthResponse {
  status: string;
  service?: string;
  node_id?: string;
  nodes?: number | string[];
  tick_seconds?: number;
  dialect?: string;
  time?: string | number;
}

export interface BackendSnapshotResponse {
  t: number;
  nodes: RemoteTelemetryFrame[];
}

export interface AnomalyInjectResponse {
  node_id: string;
  anomaly_ticks: number;
}

export interface ApiConfig {
  baseUrl: string;
  wsUrl: string;
  defaultNodeId: string;
  timeoutMs: number;
  maxRetries: number;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly endpoint?: string,
    public readonly originalError?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}
