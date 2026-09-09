import { STRAIN_THRESHOLD_MM_PER_M, TILT_THRESHOLD_DEG } from '@/sim/feed';
import { Gauge } from './Gauge';
import type { NodeReading } from '@/data/types';

const DEG_TO_MM_PER_M = (Math.PI / 180) * 1000;

export function ParamsPanel({ node }: { node: NodeReading | undefined }) {
  if (!node) return null;
  return (
    <div className="grid grid-cols-4 gap-2 px-3 pb-3">
      <Gauge
        label="Tilt (Pitch)" value={Math.abs(node.tiltPitchDeg)} limit={TILT_THRESHOLD_DEG}
        unit="°" note={`${(Math.abs(node.tiltPitchDeg) * DEG_TO_MM_PER_M).toFixed(1)} mm/m`}
      />
      <Gauge
        label="Tilt (Roll)" value={Math.abs(node.tiltRollDeg)} limit={TILT_THRESHOLD_DEG}
        unit="°" note={`${(Math.abs(node.tiltRollDeg) * DEG_TO_MM_PER_M).toFixed(1)} mm/m`}
      />
      <Gauge
        label="Vibration RMS" value={node.vibrationMg} limit={400} unit="mg" decimals={1}
        note="Limit: 400"
      />
      <Gauge
        label="Ground Strain" value={Math.abs(node.strainMmPerM)}
        limit={STRAIN_THRESHOLD_MM_PER_M} unit="mm/m"
        note={node.strainValid
          ? `Limit: ${STRAIN_THRESHOLD_MM_PER_M.toFixed(2)}`
          : 'Array too sparse to resolve'}
      />
    </div>
  );
}
