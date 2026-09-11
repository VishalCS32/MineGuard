/**
 * Telemetry Normalizer & Mapping Layer
 *
 * Provides a resilient adaptation layer between raw wire telemetry (simulator or backend)
 * and the stable frontend NodeDetailViewModel. Tolerates schema changes, absent values,
 * alternative key names, and nested structures.
 */
import type {
  BatteryHealth,
  GnssLockState,
  NodeDetailViewModel,
  RadioQuality,
  RawNodeTelemetry,
  SemanticSeverity,
  TelemetrySource,
} from './types';

export interface NormalizationContext {
  source?: TelemetrySource;
  fallbackNodeId?: string;
  fallbackAddr?: number;
  online?: boolean;
}

const EXTENDED_TELEMETRY_DISCLAIMER =
  'Gyroscope, accelerometer, and GPS values are simulator/UI-contract fields. Production SUBSIDENCE-NET telemetry does not currently provide these raw measurements.';

function formatTimeAgo(date: Date): string {
  const diffSec = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (diffSec < 2) return 'Just now';
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  return `${diffHr}h ago`;
}

function parseSemanticSeverity(conditionStr?: unknown): SemanticSeverity {
  if (typeof conditionStr !== 'string') return 'unknown';
  const c = conditionStr.trim().toUpperCase();
  if (['NORMAL', 'HEALTHY', 'OK', 'GOOD', 'BASELINE'].includes(c)) return 'normal';
  if (['WATCH', 'MODERATE', 'ELEVATED'].includes(c)) return 'watch';
  if (['WARNING', 'HIGH', 'SERIOUS'].includes(c)) return 'warning';
  if (['CRITICAL', 'DANGER', 'EMERGENCY', 'FAILURE'].includes(c)) return 'critical';
  return 'unknown';
}

function normalizeScore(val: unknown): number | null {
  if (typeof val !== 'number' || Number.isNaN(val)) return null;
  // If score is given on a 0-100 scale, normalize to 0.00-1.00
  if (val > 1.0) return Number((val / 100).toFixed(4));
  return Number(val.toFixed(4));
}

function normalizeForecastValue(val: unknown): string {
  if (val === undefined || val === null || val === '') return 'Unavailable';
  if (typeof val === 'string') {
    const trimmed = val.trim();
    return trimmed.length > 0 ? trimmed : 'Unavailable';
  }
  if (typeof val === 'number') {
    return Number.isNaN(val) ? 'Unavailable' : `${(val * 100).toFixed(1)}%`;
  }
  if (typeof val === 'object') {
    const obj = val as Record<string, unknown>;
    if (obj.label) return String(obj.label);
    if (obj.risk) return String(obj.risk);
    if (obj.score !== undefined) return `${(Number(obj.score) * 100).toFixed(1)}%`;
  }
  return 'Unavailable';
}

/**
 * Normalizes any raw telemetry input into a type-safe NodeDetailViewModel.
 */
export function normalizeNodeTelemetry(
  rawInput: unknown,
  context?: NormalizationContext,
): NodeDetailViewModel {
  const raw: RawNodeTelemetry = (typeof rawInput === 'object' && rawInput !== null ? rawInput : {}) as RawNodeTelemetry;

  // 1. Identification & Source
  const nodeId =
    raw.nodeId ||
    raw.node_id ||
    raw.id ||
    context?.fallbackNodeId ||
    (context?.fallbackAddr ? `NODE-${String(context.fallbackAddr).padStart(3, '0')}` : 'NODE-001');

  const rawSource = raw.source || context?.source || 'simulator';
  const source: TelemetrySource = rawSource === 'live' || rawSource === 'backend' ? 'live' : 'simulator';
  const sourceLabel = source === 'live' ? 'Live backend data' : 'Simulator data';
  const isLive = source === 'live';

  // 2. Timestamp
  const rawTs = raw.timestamp ?? raw.time ?? raw.ts;
  let parsedDate: Date;
  if (typeof rawTs === 'string' || typeof rawTs === 'number') {
    const d = new Date(rawTs);
    parsedDate = Number.isNaN(d.getTime()) ? new Date() : d;
  } else {
    parsedDate = new Date();
  }

  const timestampIso = parsedDate.toISOString();
  const timestampFormatted = parsedDate.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
  const timeAgo = formatTimeAgo(parsedDate);

  // 3. Orientation
  const pitchRaw =
    raw.orientation?.pitchDeg ??
    raw.orientation?.pitch ??
    raw.pitchDeg ??
    raw.pitch;
  const rollRaw =
    raw.orientation?.rollDeg ??
    raw.orientation?.roll ??
    raw.rollDeg ??
    raw.roll;

  const pitchDeg = typeof pitchRaw === 'number' && !Number.isNaN(pitchRaw) ? Number(pitchRaw.toFixed(3)) : null;
  const rollDeg = typeof rollRaw === 'number' && !Number.isNaN(rollRaw) ? Number(rollRaw.toFixed(3)) : null;
  const resultantTiltDeg =
    pitchDeg !== null && rollDeg !== null ? Number(Math.hypot(pitchDeg, rollDeg).toFixed(3)) : null;

  // Rate of tilt from raw or calculation
  const rawRate = raw.tiltRateDegPerH ?? raw.tilt_rate_deg_per_h;
  const tiltRateDegPerH = typeof rawRate === 'number' && !Number.isNaN(rawRate) ? Number(rawRate.toFixed(3)) : null;

  // 4. Vibration
  const rmsRaw =
    raw.vibration?.rmsMg ??
    raw.vibration?.rms_mg ??
    (typeof raw.vibration?.rms === 'number' ? raw.vibration.rms * 1000 : undefined) ??
    raw.vibrationMg;
  const rmsMg = typeof rmsRaw === 'number' && !Number.isNaN(rmsRaw) ? Number(rmsRaw.toFixed(1)) : null;

  const peakFreqRaw =
    raw.vibration?.peakFrequencyHz ??
    raw.vibration?.peak_frequency_hz ??
    raw.vibration?.peakHz;
  const peakFrequencyHz =
    typeof peakFreqRaw === 'number' && !Number.isNaN(peakFreqRaw) ? Number(peakFreqRaw.toFixed(1)) : null;

  let vibrationSeverity: SemanticSeverity = 'unknown';
  if (rmsMg !== null) {
    if (rmsMg < 50) vibrationSeverity = 'normal';
    else if (rmsMg < 150) vibrationSeverity = 'watch';
    else if (rmsMg < 300) vibrationSeverity = 'warning';
    else vibrationSeverity = 'critical';
  }

  // 5. Environmental & Device Health
  const tempRaw =
    raw.environment?.temperatureC ??
    raw.environment?.temp_c ??
    raw.environment?.tempC ??
    raw.tempC;
  const temperatureC = typeof tempRaw === 'number' && !Number.isNaN(tempRaw) ? Number(tempRaw.toFixed(1)) : null;

  // Battery decoding (tolerates mV, V, or %)
  const battMvRaw = raw.environment?.batteryMv ?? raw.environment?.battery_mv;
  const battVoltsRaw = raw.environment?.batteryVolts;
  const battPctRaw = raw.environment?.batteryPct ?? raw.batteryPct;

  let batteryRawValue: number | null = null;
  let batteryUnit: 'mV' | 'V' | '%' = 'mV';
  let batteryPercentage = 85;
  let batteryDisplay = 'Unavailable';
  let batteryHealth: BatteryHealth = 'unknown';

  if (typeof battMvRaw === 'number' && !Number.isNaN(battMvRaw)) {
    batteryRawValue = Math.round(battMvRaw);
    batteryUnit = 'mV';
    batteryDisplay = `${batteryRawValue} mV (${(batteryRawValue / 1000).toFixed(2)} V)`;
    // Li-ion 3400 mV (0%) to 4200 mV (100%)
    batteryPercentage = Math.max(0, Math.min(100, Math.round(((batteryRawValue - 3400) / 800) * 100)));
  } else if (typeof battVoltsRaw === 'number' && !Number.isNaN(battVoltsRaw)) {
    batteryRawValue = Number(battVoltsRaw.toFixed(2));
    batteryUnit = 'V';
    batteryDisplay = `${batteryRawValue} V`;
    batteryPercentage = Math.max(0, Math.min(100, Math.round(((batteryRawValue - 3.4) / 0.8) * 100)));
  } else if (typeof battPctRaw === 'number' && !Number.isNaN(battPctRaw)) {
    batteryRawValue = Math.round(battPctRaw);
    batteryUnit = '%';
    batteryPercentage = Math.max(0, Math.min(100, batteryRawValue));
    batteryDisplay = `${batteryPercentage}%`;
  }

  if (batteryRawValue !== null) {
    if (batteryPercentage > 40) batteryHealth = 'good';
    else if (batteryPercentage > 15) batteryHealth = 'low';
    else batteryHealth = 'critical';
  }

  // Radio Link Quality
  const rssiRaw = raw.environment?.rssiDbm ?? raw.environment?.rssi_dbm ?? raw.environment?.rssi ?? raw.rssi;
  const rssiDbm = typeof rssiRaw === 'number' && !Number.isNaN(rssiRaw) ? Math.round(rssiRaw) : null;

  const snrRaw = raw.environment?.snrDb ?? raw.environment?.snr_db ?? raw.environment?.snr;
  const snrDb = typeof snrRaw === 'number' && !Number.isNaN(snrRaw) ? Number(snrRaw.toFixed(1)) : null;

  let radioQuality: RadioQuality = 'unknown';
  if (rssiDbm !== null) {
    if (rssiDbm >= -75) radioQuality = 'excellent';
    else if (rssiDbm >= -85) radioQuality = 'good';
    else if (rssiDbm >= -98) radioQuality = 'fair';
    else radioQuality = 'poor';
  }

  // GNSS
  const gnssStatusRaw = raw.environment?.gnssStatus ?? raw.environment?.gnss_status;
  const gnssSatsRaw = raw.environment?.gnssSats ?? raw.extendedTelemetry?.gps?.satellites ?? raw.gps?.satellites;
  const gnssSats = typeof gnssSatsRaw === 'number' && !Number.isNaN(gnssSatsRaw) ? Math.round(gnssSatsRaw) : null;

  let gnssStatus = typeof gnssStatusRaw === 'string' ? gnssStatusRaw.toUpperCase() : null;
  if (!gnssStatus && gnssSats !== null) {
    gnssStatus = gnssSats >= 4 ? 'LOCKED' : 'SEARCHING';
  }

  let gnssLockState: GnssLockState = 'unknown';
  if (gnssStatus) {
    if (['OK', 'LOCKED', '3D_FIX', 'FIX'].includes(gnssStatus)) gnssLockState = 'locked';
    else if (['SEARCHING', 'ACQUIRING', '2D_FIX'].includes(gnssStatus)) gnssLockState = 'searching';
    else gnssLockState = 'unavailable';
  }

  // 6. AI / ML Assessment
  const mlConditionRaw = raw.ml?.condition;
  const condition = typeof mlConditionRaw === 'string' ? mlConditionRaw.toUpperCase() : 'UNKNOWN';
  const conditionSeverity = parseSemanticSeverity(condition);

  const anomaly = typeof raw.ml?.anomaly === 'boolean' ? raw.ml.anomaly : null;
  const anomalyScore = normalizeScore(raw.ml?.anomalyScore ?? raw.ml?.anomaly_score);

  const riskLevelRaw = raw.ml?.riskLevel ?? raw.ml?.risk_level;
  const riskLevel = typeof riskLevelRaw === 'string' ? riskLevelRaw.toUpperCase() : 'UNKNOWN';

  const riskScore = normalizeScore(raw.ml?.riskScore ?? raw.ml?.risk_score);
  const confidence = normalizeScore(raw.ml?.confidence);

  const deformationState =
    typeof raw.ml?.deformationState === 'string'
      ? raw.ml.deformationState
      : typeof raw.ml?.deformation_state === 'string'
      ? raw.ml.deformation_state
      : null;

  const spatialCorroboration =
    typeof raw.ml?.spatialCorroboration === 'string'
      ? raw.ml.spatialCorroboration
      : typeof raw.ml?.spatial_corroboration === 'string'
      ? raw.ml.spatial_corroboration
      : null;

  const physicsConsistency =
    typeof raw.ml?.physicsConsistency === 'string'
      ? raw.ml.physicsConsistency
      : typeof raw.ml?.physics_consistency === 'string'
      ? raw.ml.physics_consistency
      : null;

  const reasonCodes = Array.isArray(raw.ml?.reasonCodes)
    ? (raw.ml.reasonCodes as string[])
    : Array.isArray(raw.ml?.reason_codes)
    ? (raw.ml.reason_codes as string[])
    : [];

  const explanation = typeof raw.ml?.explanation === 'string' ? raw.ml.explanation : null;

  // 7. Forecast & Thresholds
  const forecastRaw = raw.ml?.forecast || (raw.forecast as Record<string, unknown> | undefined);
  const forecast1h = normalizeForecastValue(forecastRaw?.['1h'] ?? forecastRaw?.h1 ?? forecastRaw?.oneHour);
  const forecast6h = normalizeForecastValue(forecastRaw?.['6h'] ?? forecastRaw?.h6 ?? forecastRaw?.sixHour);
  const forecast12h = normalizeForecastValue(forecastRaw?.['12h'] ?? forecastRaw?.h12 ?? forecastRaw?.twelveHour);
  const forecast24h = normalizeForecastValue(forecastRaw?.['24h'] ?? forecastRaw?.h24 ?? forecastRaw?.twentyFourHour);

  const timeToWarnRaw = raw.ml?.timeToWarningHours ?? raw.ml?.time_to_warning_hours;
  const timeToWarningHours =
    typeof timeToWarnRaw === 'number' && !Number.isNaN(timeToWarnRaw) ? Number(timeToWarnRaw.toFixed(1)) : null;

  const timeToCritRaw = raw.ml?.timeToCriticalHours ?? raw.ml?.time_to_critical_hours;
  const timeToCriticalHours =
    typeof timeToCritRaw === 'number' && !Number.isNaN(timeToCritRaw) ? Number(timeToCritRaw.toFixed(1)) : null;

  const timeToWarningDisplay = timeToWarningHours !== null ? `${timeToWarningHours} hours` : 'Unavailable';
  const timeToCriticalDisplay = timeToCriticalHours !== null ? `${timeToCriticalHours} hours` : 'Unavailable';

  // 8. Extended Telemetry (Gyroscope, Accelerometer, GPS)
  const ext = raw.extendedTelemetry;
  const extAvailability = ext?.availability || (source === 'simulator' ? 'simulator_only' : 'backend_unavailable');

  // Check if real numerical values are provided (either in extendedTelemetry or top-level wire frame)
  const gyroSource = ext?.gyroscope || (raw.gyro as { x?: number | null; y?: number | null; z?: number | null } | undefined);
  const gyroX = gyroSource?.x != null && !Number.isNaN(gyroSource.x) ? gyroSource.x : null;
  const gyroY = gyroSource?.y != null && !Number.isNaN(gyroSource.y) ? gyroSource.y : null;
  const gyroZ = gyroSource?.z != null && !Number.isNaN(gyroSource.z) ? gyroSource.z : null;
  const gyroSupplied = gyroX !== null || gyroY !== null || gyroZ !== null;

  const accelSource = ext?.accelerometer || (raw.accel as { x?: number | null; y?: number | null; z?: number | null } | undefined);
  const accelX = accelSource?.x != null && !Number.isNaN(accelSource.x) ? accelSource.x : null;
  const accelY = accelSource?.y != null && !Number.isNaN(accelSource.y) ? accelSource.y : null;
  const accelZ = accelSource?.z != null && !Number.isNaN(accelSource.z) ? accelSource.z : null;
  const accelSupplied = accelX !== null || accelY !== null || accelZ !== null;

  const gpsSource = ext?.gps || (raw.gps as { latitude?: number | null; longitude?: number | null; altitudeM?: number | null; altitude?: number | null; satellites?: number | null; hdop?: number | null } | undefined);
  const gpsLat = gpsSource?.latitude != null && !Number.isNaN(gpsSource.latitude) ? gpsSource.latitude : null;
  const gpsLon = gpsSource?.longitude != null && !Number.isNaN(gpsSource.longitude) ? gpsSource.longitude : null;
  const gpsAlt = gpsSource?.altitudeM != null && !Number.isNaN(gpsSource.altitudeM) ? gpsSource.altitudeM : gpsSource?.altitude ?? null;
  const gpsSats = gpsSource?.satellites != null && !Number.isNaN(gpsSource.satellites) ? gpsSource.satellites : null;
  const gpsHdop = gpsSource?.hdop != null && !Number.isNaN(gpsSource.hdop) ? gpsSource.hdop : null;
  const gpsSupplied = gpsLat !== null || gpsLon !== null;

  const isSuppliedByBackend = isLive && (gyroSupplied || accelSupplied || gpsSupplied);

  return {
    nodeId,
    displayName: `${nodeId} (${source === 'live' ? 'Live Ingress' : 'Simulator'})`,
    timestampIso,
    timestampFormatted,
    timeAgo,
    source,
    sourceLabel,
    isLive,

    orientation: {
      pitchDeg,
      rollDeg,
      resultantTiltDeg,
      tiltRateDegPerH,
      isAvailable: pitchDeg !== null || rollDeg !== null,
    },

    vibration: {
      rmsMg,
      peakFrequencyHz,
      severity: vibrationSeverity,
      isAvailable: rmsMg !== null || peakFrequencyHz !== null,
    },

    environment: {
      temperatureC,
      battery: {
        rawValue: batteryRawValue,
        unit: batteryUnit,
        displayString: batteryDisplay,
        percentage: batteryPercentage,
        health: batteryHealth,
      },
      rssiDbm,
      snrDb,
      radioQuality,
      gnssStatus,
      gnssSats,
      gnssLockState,
      isAvailable: temperatureC !== null || batteryRawValue !== null || rssiDbm !== null,
    },

    ml: {
      condition,
      conditionSeverity,
      anomaly,
      anomalyScore,
      riskLevel,
      riskScore,
      confidence,
      deformationState,
      spatialCorroboration,
      physicsConsistency,
      reasonCodes,
      explanation,
      isSimulatedAi: source === 'simulator',
    },

    forecast: {
      forecast1h,
      forecast6h,
      forecast12h,
      forecast24h,
      timeToWarningHours,
      timeToCriticalHours,
      timeToWarningDisplay,
      timeToCriticalDisplay,
      isAvailable:
        forecast1h !== 'Unavailable' ||
        forecast6h !== 'Unavailable' ||
        timeToWarningHours !== null,
    },

    extended: {
      availability: extAvailability,
      isSimulatedContract: source === 'simulator',
      isSuppliedByBackend,
      disclaimerNote: EXTENDED_TELEMETRY_DISCLAIMER,
      gyroscope: {
        x: gyroX,
        y: gyroY,
        z: gyroZ,
        isSupplied: gyroSupplied,
      },
      accelerometer: {
        x: accelX,
        y: accelY,
        z: accelZ,
        isSupplied: accelSupplied,
      },
      gps: {
        latitude: gpsLat,
        longitude: gpsLon,
        altitudeM: gpsAlt,
        satellites: gpsSats,
        hdop: gpsHdop,
        isSupplied: gpsSupplied,
      },
    },

    rawPayload: rawInput,
  };
}
