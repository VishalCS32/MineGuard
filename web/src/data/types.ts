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
  /** Degrees per hour. The precursor signal: ground that accelerates is failing. */
  tiltRateDegPerH: number;
  vibrationMg: number;
  /** LIS3DH die temperature. Carried so tilt can be drift-corrected, not weather. */
  tempC: number;
  /** Integrated from the tilt array; only meaningful when anchored. */
  subsidenceMm: number;
  subsidenceValid: boolean;
  /** Reconstructed from the tilt gradient across neighbours -- not a sensor. */
  strainMmPerM: number;
  strainValid: boolean;
  gnssSats: number;
  riskScore: number;
  risk: RiskLevel;
  damage: DamageClass;
  hops: number;
  rssi: number;
  batteryPct: number;
  nodeDetail?: import('./telemetry/types').NodeDetailViewModel;
  rawTelemetry?: import('./telemetry/types').RawNodeTelemetry;
  rawFrame?: {
    gyro: { x: number; y: number; z: number };
    accel: { x: number; y: number; z: number };
    orientation: { roll: number; pitch: number };
    vibration: { x: number; y: number; z: number; rms: number };
    gps: { latitude: number; longitude: number; altitude: number; satellites: number; hdop: number };
    ml: { condition: 'normal' | 'warning' | 'critical'; anomaly: boolean; anomaly_score: number };
    timestamp?: string;
  };
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
  tempC: number;
  anomalyScore?: number;
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
  maxStrainMmPerM: number;
  strainThresholdMmPerM: number;
  maxSubsidenceMm: number;
  maxTiltRateDegPerH: number;
  tiltRateThresholdDegPerH: number;
  /** False when the array is too sparse to differentiate -- strain reads unknown. */
  strainResolved: boolean;
  packetDeliveryPct: number;
  uptimePct: number;
  healthy: boolean;
}

export interface Snapshot {
  t: number;
  /** Simulated day -- what the 3-D terrain samples the subsidence surface at. */
  day: number;
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
