/**
 * Dedicated Simulator Fixture for NODE-001
 *
 * Seeded with the canonical test vector for the rich IoT and AI/ML node details experience.
 * Can be replaced or supplemented by backend adapters without redesigning the dashboard.
 */
import type { RawNodeTelemetry } from '../telemetry/types';

export const NODE_001_SIMULATOR_SEED: RawNodeTelemetry = {
  nodeId: 'NODE-001',
  timestamp: new Date().toISOString(),
  source: 'simulator',
  orientation: {
    pitchDeg: 0.12,
    rollDeg: 0.08,
  },
  vibration: {
    rmsMg: 18.5,
    peakFrequencyHz: 42,
  },
  environment: {
    temperatureC: 31.2,
    batteryMv: 3890,
    rssiDbm: -82,
    snrDb: 7.5,
    gnssStatus: 'OK',
  },
  ml: {
    condition: 'WARNING',
    anomaly: true,
    anomalyScore: 0.82,
    riskLevel: 'HIGH',
    riskScore: 0.78,
    confidence: 0.91,
    deformationState: 'Persistent deformation',
    forecast: {
      '1h': 'Unavailable',
      '6h': 'Unavailable',
      '12h': 'Unavailable',
      '24h': 'Unavailable',
    },
    timeToWarningHours: 3.8,
    timeToCriticalHours: 18.2,
    spatialCorroboration: 'Confirmed',
    physicsConsistency: 'Consistent',
    reasonCodes: [],
    explanation: 'Persistent deformation with spatial corroboration.',
  },
  extendedTelemetry: {
    availability: 'simulator_only',
    gyroscope: { x: null, y: null, z: null },
    accelerometer: { x: null, y: null, z: null },
    gps: {
      latitude: null,
      longitude: null,
      altitudeM: null,
      satellites: null,
      hdop: null,
    },
  },
};

/**
 * Returns an instance of the simulated telemetry payload with an updated timestamp
 * and optional realistic micro-fluctuations (without violating base seed specs).
 */
export function getSimulatedNode001Payload(timestamp?: string | number): RawNodeTelemetry {
  return {
    ...NODE_001_SIMULATOR_SEED,
    timestamp: timestamp ? new Date(timestamp).toISOString() : new Date().toISOString(),
  };
}

/**
 * Generates a realistic simulated telemetry payload for any peer node in the network.
 */
export function getSimulatedPeerPayload(
  nodeId: string,
  index: number,
  timestamp?: string | number,
): RawNodeTelemetry {
  const isWarning = index === 2;
  const isCritical = index === 5;
  const condition = isCritical ? 'CRITICAL' : isWarning ? 'WARNING' : 'NORMAL';
  const anomalyScore = isCritical ? 0.92 : isWarning ? 0.65 : 0.08;
  const riskLevel = isCritical ? 'CRITICAL' : isWarning ? 'HIGH' : 'LOW';

  return {
    nodeId,
    timestamp: timestamp ? new Date(timestamp).toISOString() : new Date().toISOString(),
    source: 'simulator',
    orientation: {
      pitchDeg: Number((0.04 + index * 0.03).toFixed(2)),
      rollDeg: Number((0.03 + index * 0.02).toFixed(2)),
    },
    vibration: {
      rmsMg: Math.round(12 + index * 3.5),
      peakFrequencyHz: Math.round(28 + (index * 7) % 30),
    },
    environment: {
      temperatureC: Number((29.5 + (index % 4) * 0.8).toFixed(1)),
      batteryMv: Math.max(3400, 3950 - index * 60),
      rssiDbm: -68 - index * 5,
      snrDb: Number((12.5 - index * 0.9).toFixed(1)),
      gnssStatus: 'OK',
    },
    ml: {
      condition,
      anomaly: isCritical || isWarning,
      anomalyScore,
      riskLevel,
      riskScore: anomalyScore * 0.95,
      confidence: 0.88,
      deformationState: isCritical ? 'Accelerating shear' : isWarning ? 'Boundary flexure' : 'Stable ground',
      forecast: {
        '1h': 'Unavailable',
        '6h': 'Unavailable',
        '12h': 'Unavailable',
        '24h': 'Unavailable',
      },
      timeToWarningHours: isCritical ? 0.8 : isWarning ? 6.5 : null as unknown as number,
      timeToCriticalHours: isCritical ? 3.2 : isWarning ? 24.0 : null as unknown as number,
      spatialCorroboration: isCritical || isWarning ? 'Confirmed' : 'Uncorrelated',
      physicsConsistency: 'Consistent',
      reasonCodes: isCritical ? ['INCLINE_ACCEL', 'VIB_SURGE'] : isWarning ? ['INCLINE_FLEX'] : [],
      explanation: isCritical
        ? 'Accelerated tilt rate exceeds safe working threshold.'
        : isWarning
        ? 'Minor boundary strain detected along extraction panel edge.'
        : 'Ground deformation within baseline limits.',
    },
    extendedTelemetry: {
      availability: 'simulator_only',
      gyroscope: { x: null, y: null, z: null },
      accelerometer: { x: null, y: null, z: null },
      gps: {
        latitude: null,
        longitude: null,
        altitudeM: null,
        satellites: null,
        hdop: null,
      },
    },
  };
}
