/**
 * Extensible Telemetry Types & Stable Frontend View Model
 *
 * Designed to decouple raw incoming telemetry (which will evolve over time,
 * can be flat or nested, simulator or backend) from the stable presentation layer.
 */

export type TelemetrySource = 'simulator' | 'live';

export type SemanticSeverity = 'normal' | 'watch' | 'warning' | 'critical' | 'unknown';

export type BatteryHealth = 'good' | 'low' | 'critical' | 'unknown';

export type RadioQuality = 'excellent' | 'good' | 'fair' | 'poor' | 'unknown';

export type GnssLockState = 'locked' | 'searching' | 'unavailable' | 'unknown';

/**
 * Flexible, version-resilient incoming telemetry contract.
 * Tolerates missing, renamed, nested, or future optional fields.
 */
export interface RawNodeTelemetry {
  nodeId?: string;
  node_id?: string;
  id?: string;
  timestamp?: string | number;
  time?: string | number;
  ts?: number;
  source?: 'simulator' | 'live' | 'backend';

  orientation?: {
    pitchDeg?: number;
    rollDeg?: number;
    pitch?: number;
    roll?: number;
  };
  pitchDeg?: number;
  rollDeg?: number;
  pitch?: number;
  roll?: number;

  vibration?: {
    rmsMg?: number;
    rms_mg?: number;
    rms?: number;
    peakFrequencyHz?: number;
    peak_frequency_hz?: number;
    peakHz?: number;
    x?: number;
    y?: number;
    z?: number;
  };
  vibrationMg?: number;

  environment?: {
    temperatureC?: number;
    temp_c?: number;
    tempC?: number;
    batteryMv?: number;
    battery_mv?: number;
    batteryVolts?: number;
    batteryPct?: number;
    rssiDbm?: number;
    rssi_dbm?: number;
    rssi?: number;
    snrDb?: number;
    snr_db?: number;
    snr?: number;
    gnssStatus?: string;
    gnss_status?: string;
    gnssSats?: number;
  };
  tempC?: number;
  batteryPct?: number;
  rssi?: number;

  gps?: {
    lat?: number;
    lon?: number;
    latitude?: number;
    longitude?: number;
    altitude?: number;
    satellites?: number;
    hdop?: number;
    [key: string]: unknown;
  };
  gyro?: {
    x?: number;
    y?: number;
    z?: number;
    [key: string]: unknown;
  };
  accel?: {
    x?: number;
    y?: number;
    z?: number;
    [key: string]: unknown;
  };

  ml?: {
    condition?: string;
    anomaly?: boolean;
    anomalyScore?: number;
    anomaly_score?: number;
    riskLevel?: string;
    risk_level?: string;
    riskScore?: number;
    risk_score?: number;
    confidence?: number;
    deformationState?: string;
    deformation_state?: string;
    forecast?: Record<string, unknown>;
    timeToWarningHours?: number;
    time_to_warning_hours?: number;
    timeToCriticalHours?: number;
    time_to_critical_hours?: number;
    spatialCorroboration?: string;
    spatial_corroboration?: string;
    physicsConsistency?: string;
    physics_consistency?: string;
    reasonCodes?: string[];
    reason_codes?: string[];
    explanation?: string;
  };

  extendedTelemetry?: {
    availability?: string;
    gyroscope?: {
      x?: number | null;
      y?: number | null;
      z?: number | null;
    };
    accelerometer?: {
      x?: number | null;
      y?: number | null;
      z?: number | null;
    };
    gps?: {
      latitude?: number | null;
      longitude?: number | null;
      altitudeM?: number | null;
      altitude?: number | null;
      satellites?: number | null;
      hdop?: number | null;
    };
  };

  /** Index signature allows future unknown backend fields without TypeScript errors */
  [key: string]: unknown;
}

/**
 * Stable, normalized view model for all node detail UI components.
 */
export interface NodeDetailViewModel {
  nodeId: string;
  displayName: string;
  timestampIso: string;
  timestampFormatted: string;
  timeAgo: string;
  source: TelemetrySource;
  sourceLabel: 'Simulator data' | 'Live backend data';
  isLive: boolean;

  orientation: {
    pitchDeg: number | null;
    rollDeg: number | null;
    resultantTiltDeg: number | null;
    tiltRateDegPerH: number | null;
    isAvailable: boolean;
  };

  vibration: {
    rmsMg: number | null;
    peakFrequencyHz: number | null;
    severity: SemanticSeverity;
    isAvailable: boolean;
  };

  environment: {
    temperatureC: number | null;
    battery: {
      rawValue: number | null;
      unit: 'mV' | 'V' | '%';
      displayString: string;
      percentage: number;
      health: BatteryHealth;
    };
    rssiDbm: number | null;
    snrDb: number | null;
    radioQuality: RadioQuality;
    gnssStatus: string | null;
    gnssSats: number | null;
    gnssLockState: GnssLockState;
    isAvailable: boolean;
  };

  ml: {
    condition: string;
    conditionSeverity: SemanticSeverity;
    anomaly: boolean | null;
    anomalyScore: number | null; // 0.0 - 1.0
    riskLevel: string;
    riskScore: number | null; // 0.0 - 1.0
    confidence: number | null; // 0.0 - 1.0
    deformationState: string | null;
    spatialCorroboration: string | null;
    physicsConsistency: string | null;
    reasonCodes: string[];
    explanation: string | null;
    isSimulatedAi: boolean;
  };

  forecast: {
    forecast1h: string;
    forecast6h: string;
    forecast12h: string;
    forecast24h: string;
    timeToWarningHours: number | null;
    timeToCriticalHours: number | null;
    timeToWarningDisplay: string;
    timeToCriticalDisplay: string;
    isAvailable: boolean;
  };

  extended: {
    availability: string;
    isSimulatedContract: boolean;
    isSuppliedByBackend: boolean;
    disclaimerNote: string;
    gyroscope: {
      x: number | null;
      y: number | null;
      z: number | null;
      isSupplied: boolean;
    };
    accelerometer: {
      x: number | null;
      y: number | null;
      z: number | null;
      isSupplied: boolean;
    };
    gps: {
      latitude: number | null;
      longitude: number | null;
      altitudeM: number | null;
      satellites: number | null;
      hdop: number | null;
      isSupplied: boolean;
    };
  };

  /** Preserved raw payload for dev/expert inspection */
  rawPayload: unknown;
}
