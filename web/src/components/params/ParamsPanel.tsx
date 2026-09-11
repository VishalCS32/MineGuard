import { STRAIN_THRESHOLD_MM_PER_M, TILT_THRESHOLD_DEG } from '@/sim/feed';
import { Gauge } from './Gauge';
import { IconCpu } from '@/components/ui/icons';
import type { NodeReading } from '@/data/types';

const DEG_TO_MM_PER_M = (Math.PI / 180) * 1000;

interface ParamsPanelProps {
  node: NodeReading | undefined;
  onInspect?: () => void;
}

export function ParamsPanel({ node, onInspect }: ParamsPanelProps) {
  if (!node) return null;
  const raw = node.rawFrame;
  const detail = node.nodeDetail;
  return (
    <div className="flex flex-col gap-2.5 px-3 pb-3">
      <div className="grid grid-cols-4 gap-2">
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

      {(detail || raw) && (
        <div className="rounded-lg border border-hairline bg-surface-2/70 p-2.5 text-[10px]">
          <div className="mb-1.5 flex items-center justify-between border-b border-hairline/80 pb-1">
            <span className="font-semibold text-brand flex items-center gap-1.5 text-[11px]">
              <span className={`inline-block h-2 w-2 rounded-full ${detail?.isLive ? 'bg-emerald-400' : 'bg-brand'} animate-pulse`} />
              {detail ? `${detail.sourceLabel} · ${node.label}` : `Live Sensor Ingress · ${node.label}`}
            </span>
            <span className="text-ink-3">
              {detail?.timestampFormatted ?? (raw?.timestamp ? new Date(raw.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '1 Hz')}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-x-3 gap-y-1">
            <div>
              <span className="text-ink-3">Pitch / Roll: </span>
              <span className="font-mono text-ink font-medium">
                {detail ? `${detail.orientation.pitchDeg?.toFixed(2) ?? '—'}°, ${detail.orientation.rollDeg?.toFixed(2) ?? '—'}°` : `${node.tiltPitchDeg.toFixed(2)}°, ${node.tiltRollDeg.toFixed(2)}°`}
              </span>
            </div>
            <div>
              <span className="text-ink-3">AI Condition: </span>
              <span className={`font-semibold uppercase ${
                detail?.ml.condition === 'CRITICAL' || raw?.ml.condition === 'critical'
                  ? 'text-critical'
                  : detail?.ml.condition === 'WARNING' || raw?.ml.condition === 'warning'
                    ? 'text-amber-400'
                    : 'text-good'
              }`}>
                {detail?.ml.condition ?? raw?.ml.condition ?? 'NORMAL'} {detail?.ml.anomalyScore !== null ? `(${(detail!.ml.anomalyScore * 100).toFixed(0)}%)` : ''}
              </span>
            </div>
            <div>
              <span className="text-ink-3">Battery: </span>
              <span className="font-mono text-ink font-medium">
                {detail?.environment.battery ? `${detail.environment.battery.displayString} (${detail.environment.battery.percentage}%)` : `${node.batteryPct}%`}
              </span>
            </div>
            <div>
              <span className="text-ink-3">Risk Level: </span>
              <span className="font-mono font-semibold text-ink">
                {detail?.ml.riskLevel ?? 'LOW'} {detail?.ml.riskScore !== null ? `(${detail!.ml.riskScore.toFixed(2)})` : ''}
              </span>
            </div>
          </div>
        </div>
      )}

      {onInspect && (
        <button
          type="button"
          onClick={onInspect}
          className="mt-0.5 flex w-full items-center justify-center gap-1.5 rounded-lg border border-brand/40 bg-brand/10 py-1.5 text-[11px] font-semibold text-brand transition-all hover:border-brand/70 hover:bg-brand/20 active:scale-[0.99]"
        >
          <IconCpu size={14} />
          <span>View Full IoT &amp; AI Telemetry Details</span>
        </button>
      )}
    </div>
  );
}
