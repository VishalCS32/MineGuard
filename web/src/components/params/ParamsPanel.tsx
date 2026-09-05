import { CRACK_THRESHOLD_MM, TILT_THRESHOLD_DEG } from '@/sim/feed';
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
        label="Crack Width" value={node.crackMm} limit={CRACK_THRESHOLD_MM} unit="mm"
        note={`Limit: ${CRACK_THRESHOLD_MM.toFixed(2)}`}
      />
    </div>
  );
}
