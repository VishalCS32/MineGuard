/** Domain types shared by every panel. The live backend feed will satisfy the
 *  same shapes, so swapping the mock source for the WebSocket changes one file. */
import type { DamageClass } from '@/sim/physics';

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';
export type Severity = 'medium' | 'high' | 'critical';

export interface NodeReading {
  addr: number;
  /** Two-digit display id, as painted on the physical enclosure. */
  id: string;
  label: string;
  lat: number;
  lon: number;
  x: number;
  y: number;
  isEdge: boolean;
  online: boolean;
  zone: string;
  tiltPitchDeg: number;
  tiltRollDeg: number;
  tiltDeg: number;
  vibrationMg: number;
  crackMm: number;
  subsidenceMm: number;
  strainMmPerM: number;
  riskScore: number;
  risk: RiskLevel;
  damage: DamageClass;
  hops: number;
  rssi: number;
  batteryPct: number;
}

export interface MeshLink {
  a: number;
  b: number;
  rssi: number;
  /** True while this link is on the active route home -- animated on the map. */
  onRoute: boolean;
}

export interface AlertItem {
  id: string;
  severity: Severity;
  title: string;
  nodeId: string;
  zone: string;
  ts: number;
  metrics: { label: string; value: string }[];
}

export interface TrendPoint {
  t: number;
  pitch: number;
  roll: number;
  vib: number;
  crack: number;
}

export interface PredictionPoint {
  t: number;
  /** Null once the series crosses into the forecast horizon. */
  actual: number | null;
  predicted: number;
}

export interface Kpis {
  totalNodes: number;
  activeNodes: number;
  inactiveNodes: number;
  totalAlerts: number;
  criticalAlerts: number;
  highAlerts: number;
  maxTiltDeg: number;
  tiltThresholdDeg: number;
  maxCrackMm: number;
  crackThresholdMm: number;
  packetDeliveryPct: number;
  uptimePct: number;
  healthy: boolean;
}

export interface Snapshot {
  t: number;
  faceX: number;
  nodes: NodeReading[];
  links: MeshLink[];
  alerts: AlertItem[];
  prediction: PredictionPoint[];
  kpis: Kpis;
  gatewayVolts: number;
  gatewayBatteryPct: number;
  storagePct: number;
}
