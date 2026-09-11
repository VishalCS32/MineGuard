import { useState } from 'react';
import type { NodeDetailViewModel, SemanticSeverity } from '@/data/telemetry/types';
import {
  IconActivity,
  IconBattery,
  IconBrain,
  IconCheck,
  IconChevronDown,
  IconClock,
  IconCompass,
  IconCopy,
  IconCpu,
  IconInfo,
  IconSensor,
  IconTilt,
  IconWarning,
} from '@/components/ui/icons';

interface Props {
  viewModel: NodeDetailViewModel;
  className?: string;
  onClose?: () => void;
}

const SEVERITY_STYLES: Record<
  SemanticSeverity,
  { bg: string; text: string; border: string; dot: string }
> = {
  normal: {
    bg: 'bg-good/15',
    text: 'text-good',
    border: 'border-good/30',
    dot: 'bg-good',
  },
  watch: {
    bg: 'bg-amber-500/15',
    text: 'text-amber-400',
    border: 'border-amber-500/30',
    dot: 'bg-amber-400',
  },
  warning: {
    bg: 'bg-warning/15',
    text: 'text-warning',
    border: 'border-warning/30',
    dot: 'bg-warning',
  },
  critical: {
    bg: 'bg-critical/15',
    text: 'text-critical',
    border: 'border-critical/30',
    dot: 'bg-critical animate-pulse',
  },
  unknown: {
    bg: 'bg-surface-3',
    text: 'text-ink-3',
    border: 'border-hairline',
    dot: 'bg-ink-3',
  },
};

export function NodeDetailPanel({ viewModel: vm, className = '', onClose }: Props) {
  const [copied, setCopied] = useState(false);
  const [extendedOpen, setExtendedOpen] = useState(true);
  const [rawOpen, setRawOpen] = useState(false);

  const handleCopyRaw = () => {
    try {
      void navigator.clipboard.writeText(JSON.stringify(vm.rawPayload, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const condStyle = SEVERITY_STYLES[vm.ml.conditionSeverity];
  const vibStyle = SEVERITY_STYLES[vm.vibration.severity];

  return (
    <div className={`flex flex-col gap-3 text-ink ${className}`}>
      {/* 1. Header & Source Badge */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-hairline bg-surface-2/80 p-3.5 backdrop-blur">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand/15 text-brand shadow-glow">
            <IconCpu size={22} />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-black tracking-wide text-ink">{vm.nodeId}</span>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                  vm.isLive
                    ? 'bg-brand/20 text-brand border border-brand/40 shadow-glow'
                    : 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${vm.isLive ? 'bg-brand animate-pulse' : 'bg-amber-400'}`} />
                {vm.sourceLabel}
              </span>
            </div>
            <div className="flex items-center gap-2 text-[11px] text-ink-3">
              <span className="flex items-center gap-1">
                <IconClock size={12} />
                {vm.timestampFormatted}
              </span>
              <span>·</span>
              <span className="tabular-nums">{vm.timeAgo}</span>
            </div>
          </div>
        </div>

        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-hairline p-1.5 text-ink-3 hover:bg-surface-3 hover:text-ink transition-colors"
            aria-label="Close"
          >
            ✕
          </button>
        )}
      </div>

      {/* 2. Orientation & Tilt Card */}
      <div className="rounded-xl border border-hairline bg-surface-2/60 p-3.5">
        <div className="mb-2.5 flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-brand">
            <IconCompass size={15} />
            <span>Orientation & Inclinometer</span>
          </div>
          <span className="text-[10px] text-ink-3">Biaxial Dual Inclinometer</span>
        </div>

        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="text-[10px] font-medium text-ink-3">Pitch Angle</div>
            <div className="mt-0.5 font-mono text-base font-bold text-ink">
              {vm.orientation.pitchDeg !== null ? `${vm.orientation.pitchDeg.toFixed(2)}°` : '—'}
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">Y-axis transverse</div>
          </div>

          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="text-[10px] font-medium text-ink-3">Roll Angle</div>
            <div className="mt-0.5 font-mono text-base font-bold text-ink">
              {vm.orientation.rollDeg !== null ? `${vm.orientation.rollDeg.toFixed(2)}°` : '—'}
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">X-axis longitudinal</div>
          </div>

          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="text-[10px] font-medium text-ink-3">Resultant Tilt</div>
            <div className="mt-0.5 font-mono text-base font-bold text-brand">
              {vm.orientation.resultantTiltDeg !== null ? `${vm.orientation.resultantTiltDeg.toFixed(2)}°` : '—'}
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">√(pitch² + roll²)</div>
          </div>

          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="text-[10px] font-medium text-ink-3">Tilt Rate (dT/dt)</div>
            <div className="mt-0.5 font-mono text-base font-bold text-ink">
              {vm.orientation.tiltRateDegPerH !== null ? `${vm.orientation.tiltRateDegPerH.toFixed(3)}°/h` : '—'}
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">Angular acceleration</div>
          </div>
        </div>
      </div>

      {/* 3. Vibration Card */}
      <div className="rounded-xl border border-hairline bg-surface-2/60 p-3.5">
        <div className="mb-2.5 flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-cyan-400">
            <IconActivity size={15} />
            <span>Vibration & Kinematics</span>
          </div>
          <span
            className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-bold uppercase ${vibStyle.bg} ${vibStyle.text} border ${vibStyle.border}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${vibStyle.dot}`} />
            {vm.vibration.severity}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="text-[10px] font-medium text-ink-3">RMS Vibration</div>
            <div className="mt-0.5 font-mono text-base font-bold text-ink">
              {vm.vibration.rmsMg !== null ? `${vm.vibration.rmsMg} mg` : '—'}
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">DGMS Alert Limit: 400 mg</div>
          </div>

          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="text-[10px] font-medium text-ink-3">Peak Frequency</div>
            <div className="mt-0.5 font-mono text-base font-bold text-ink">
              {vm.vibration.peakFrequencyHz !== null ? `${vm.vibration.peakFrequencyHz} Hz` : '—'}
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">Dominant spectral peak</div>
          </div>

          <div className="col-span-2 sm:col-span-1 rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5 flex flex-col justify-between">
            <div className="text-[10px] font-medium text-ink-3">Threshold Headroom</div>
            <div className="my-1.5 h-2 w-full overflow-hidden rounded-full bg-surface-2 border border-hairline/80">
              <div
                className={`h-full rounded-full ${
                  (vm.vibration.rmsMg ?? 0) > 300
                    ? 'bg-critical'
                    : (vm.vibration.rmsMg ?? 0) > 150
                    ? 'bg-warning'
                    : 'bg-good'
                }`}
                style={{ width: `${Math.min(100, ((vm.vibration.rmsMg ?? 0) / 400) * 100)}%` }}
              />
            </div>
            <div className="text-[9px] text-ink-3">
              {vm.vibration.rmsMg !== null ? `${((vm.vibration.rmsMg / 400) * 100).toFixed(1)}% of ceiling` : '—'}
            </div>
          </div>
        </div>
      </div>

      {/* 4. Environmental and Device Health */}
      <div className="rounded-xl border border-hairline bg-surface-2/60 p-3.5">
        <div className="mb-2.5 flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-emerald-400">
            <IconBattery size={15} />
            <span>Environmental & Device Health</span>
          </div>
          <span className="text-[10px] text-ink-3">Enclosure Telemetry</span>
        </div>

        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          {/* Temperature */}
          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="text-[10px] font-medium text-ink-3">Temperature</div>
            <div className="mt-0.5 font-mono text-base font-bold text-ink">
              {vm.environment.temperatureC !== null ? `${vm.environment.temperatureC}°C` : '—'}
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">Die ambient temperature</div>
          </div>

          {/* Battery */}
          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="flex items-center justify-between text-[10px] font-medium text-ink-3">
              <span>Battery</span>
              <span
                className={`text-[9px] font-bold uppercase ${
                  vm.environment.battery.health === 'good'
                    ? 'text-good'
                    : vm.environment.battery.health === 'low'
                    ? 'text-warning'
                    : 'text-critical'
                }`}
              >
                {vm.environment.battery.health}
              </span>
            </div>
            <div className="mt-0.5 font-mono text-sm font-bold text-ink">
              {vm.environment.battery.displayString}
            </div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
              <div
                className={`h-full rounded-full ${
                  vm.environment.battery.health === 'critical'
                    ? 'bg-critical'
                    : vm.environment.battery.health === 'low'
                    ? 'bg-warning'
                    : 'bg-good'
                }`}
                style={{ width: `${vm.environment.battery.percentage}%` }}
              />
            </div>
          </div>

          {/* Radio Link (RSSI / SNR) */}
          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="flex items-center justify-between text-[10px] font-medium text-ink-3">
              <span>Radio Quality</span>
              <span className="text-[9px] font-bold uppercase text-brand">
                {vm.environment.radioQuality}
              </span>
            </div>
            <div className="mt-0.5 font-mono text-xs font-bold text-ink">
              {vm.environment.rssiDbm !== null ? `${vm.environment.rssiDbm} dBm` : '—'}
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">
              SNR: {vm.environment.snrDb !== null ? `${vm.environment.snrDb} dB` : '—'}
            </div>
          </div>

          {/* GNSS Status */}
          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="flex items-center justify-between text-[10px] font-medium text-ink-3">
              <span>GNSS Status</span>
              <span
                className={`text-[9px] font-bold uppercase ${
                  vm.environment.gnssLockState === 'locked' ? 'text-good' : 'text-amber-400'
                }`}
              >
                {vm.environment.gnssStatus || 'Unavailable'}
              </span>
            </div>
            <div className="mt-0.5 font-mono text-xs font-bold text-ink">
              {vm.environment.gnssLockState === 'locked' ? 'Satellite Lock' : 'Fix Acquiring'}
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">
              {vm.environment.gnssSats !== null ? `${vm.environment.gnssSats} Satellites Tracked` : 'Constellation N/A'}
            </div>
          </div>
        </div>
      </div>

      {/* 5. AI / ML Assessment Card */}
      <div className="rounded-xl border border-hairline bg-surface-2/60 p-3.5">
        <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="grid h-6 w-6 place-items-center rounded-lg bg-purple-500/20 text-purple-400">
              <IconBrain size={15} />
            </span>
            <span className="text-xs font-bold uppercase tracking-wider text-purple-400">
              AI / ML Structural Assessment
            </span>
          </div>

          <div className="flex items-center gap-2">
            {vm.ml.isSimulatedAi && (
              <span className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-amber-400">
                Simulator AI Model
              </span>
            )}
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase ${condStyle.bg} ${condStyle.text} border ${condStyle.border}`}
            >
              <span className={`h-2 w-2 rounded-full ${condStyle.dot}`} />
              {vm.ml.condition}
            </span>
          </div>
        </div>

        {/* Anomaly, Risk, Confidence Grid */}
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="text-[10px] font-medium text-ink-3">Anomaly Detected</div>
            <div className="mt-1 flex items-center gap-1.5 font-mono text-sm font-bold">
              {vm.ml.anomaly === true ? (
                <span className="flex items-center gap-1 text-warning">
                  <IconWarning size={14} /> YES
                </span>
              ) : vm.ml.anomaly === false ? (
                <span className="flex items-center gap-1 text-good">
                  <IconCheck size={14} /> NO
                </span>
              ) : (
                <span className="text-ink-3">—</span>
              )}
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">Real-time detector flag</div>
          </div>

          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="text-[10px] font-medium text-ink-3">Anomaly Score</div>
            <div className="mt-1 font-mono text-sm font-bold text-ink">
              {vm.ml.anomalyScore !== null ? `${(vm.ml.anomalyScore * 100).toFixed(1)}%` : '—'}
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">Score: {vm.ml.anomalyScore ?? '—'}</div>
          </div>

          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="text-[10px] font-medium text-ink-3">Risk Level & Score</div>
            <div className="mt-1 font-mono text-sm font-bold text-ink">
              <span
                className={
                  vm.ml.riskLevel === 'CRITICAL'
                    ? 'text-critical'
                    : vm.ml.riskLevel === 'HIGH'
                    ? 'text-warning'
                    : vm.ml.riskLevel === 'MEDIUM'
                    ? 'text-amber-400'
                    : 'text-good'
                }
              >
                {vm.ml.riskLevel}
              </span>
              <span className="ml-1 text-xs text-ink-3 font-normal">
                ({vm.ml.riskScore !== null ? (vm.ml.riskScore * 100).toFixed(0) : '—'}%)
              </span>
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">Composite index</div>
          </div>

          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5">
            <div className="text-[10px] font-medium text-ink-3">Inference Confidence</div>
            <div className="mt-1 font-mono text-sm font-bold text-brand">
              {vm.ml.confidence !== null ? `${(vm.ml.confidence * 100).toFixed(1)}%` : '—'}
            </div>
            <div className="mt-0.5 text-[9px] text-ink-3">Bayesian certainty</div>
          </div>
        </div>

        {/* Physics & Spatial Corroboration */}
        <div className="mt-2.5 grid grid-cols-1 gap-2 sm:grid-cols-3 text-xs">
          <div className="rounded-lg border border-hairline/60 bg-surface-3/40 p-2">
            <span className="text-[10px] text-ink-3">Deformation State: </span>
            <span className="font-semibold text-ink">{vm.ml.deformationState || 'Normal'}</span>
          </div>
          <div className="rounded-lg border border-hairline/60 bg-surface-3/40 p-2">
            <span className="text-[10px] text-ink-3">Spatial Corroboration: </span>
            <span className="font-semibold text-brand">{vm.ml.spatialCorroboration || 'Unverified'}</span>
          </div>
          <div className="rounded-lg border border-hairline/60 bg-surface-3/40 p-2">
            <span className="text-[10px] text-ink-3">Physics Consistency: </span>
            <span className="font-semibold text-emerald-400">{vm.ml.physicsConsistency || 'Consistent'}</span>
          </div>
        </div>

        {/* Human-readable explanation */}
        {vm.ml.explanation && (
          <div className="mt-2.5 rounded-lg border border-hairline/70 bg-surface-3/60 p-2.5 text-xs text-ink-2">
            <div className="mb-1 flex items-center gap-1 text-[10px] font-bold uppercase text-ink-3">
              <IconInfo size={12} />
              <span>Model Rationale & Diagnostic Explanation</span>
            </div>
            <p className="leading-relaxed">{vm.ml.explanation}</p>
            {vm.ml.reasonCodes.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {vm.ml.reasonCodes.map((code) => (
                  <span
                    key={code}
                    className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[9px] font-semibold text-ink-2"
                  >
                    #{code}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 6. Forecast and Escalation Thresholds */}
      <div className="rounded-xl border border-hairline bg-surface-2/60 p-3.5">
        <div className="mb-2.5 flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-indigo-400">
            <IconTilt size={15} />
            <span>Forecast & Escalation Timelines</span>
          </div>
          <span className="text-[10px] text-ink-3">Multi-Horizon Projections</span>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5 text-center">
            <div className="text-[10px] font-medium text-ink-3">1-Hour Forecast</div>
            <div
              className={`mt-1 text-xs font-bold ${
                vm.forecast.forecast1h === 'Unavailable' ? 'text-ink-3' : 'text-ink'
              }`}
            >
              {vm.forecast.forecast1h}
            </div>
          </div>

          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5 text-center">
            <div className="text-[10px] font-medium text-ink-3">6-Hour Forecast</div>
            <div
              className={`mt-1 text-xs font-bold ${
                vm.forecast.forecast6h === 'Unavailable' ? 'text-ink-3' : 'text-ink'
              }`}
            >
              {vm.forecast.forecast6h}
            </div>
          </div>

          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5 text-center">
            <div className="text-[10px] font-medium text-ink-3">12-Hour Forecast</div>
            <div
              className={`mt-1 text-xs font-bold ${
                vm.forecast.forecast12h === 'Unavailable' ? 'text-ink-3' : 'text-ink'
              }`}
            >
              {vm.forecast.forecast12h}
            </div>
          </div>

          <div className="rounded-lg border border-hairline/70 bg-surface-3/50 p-2.5 text-center">
            <div className="text-[10px] font-medium text-ink-3">24-Hour Forecast</div>
            <div
              className={`mt-1 text-xs font-bold ${
                vm.forecast.forecast24h === 'Unavailable' ? 'text-ink-3' : 'text-ink'
              }`}
            >
              {vm.forecast.forecast24h}
            </div>
          </div>
        </div>

        {/* Time to Thresholds */}
        <div className="mt-2.5 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div className="flex items-center justify-between rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5">
            <div>
              <div className="text-[10px] font-bold uppercase text-amber-400">
                Time to Warning Threshold
              </div>
              <div className="text-[11px] text-ink-2">Ground flexure boundary limit</div>
            </div>
            <div className="font-mono text-sm font-bold text-amber-400">
              {vm.forecast.timeToWarningDisplay}
            </div>
          </div>

          <div className="flex items-center justify-between rounded-lg border border-red-500/30 bg-red-500/10 p-2.5">
            <div>
              <div className="text-[10px] font-bold uppercase text-red-400">
                Time to Critical Threshold
              </div>
              <div className="text-[11px] text-ink-2">Immediate evacuation limit</div>
            </div>
            <div className="font-mono text-sm font-bold text-red-400">
              {vm.forecast.timeToCriticalDisplay}
            </div>
          </div>
        </div>
      </div>

      {/* 7. Extended IoT Structure — Simulator / UI Contract (Expandable) */}
      <div className="rounded-xl border border-hairline bg-surface-2/60 overflow-hidden">
        <button
          type="button"
          onClick={() => setExtendedOpen((v) => !v)}
          className="flex w-full items-center justify-between bg-surface-3/40 p-3.5 text-left text-xs font-bold text-ink hover:bg-surface-3/70 transition-colors"
        >
          <div className="flex items-center gap-2">
            <span className="grid h-5 w-5 place-items-center rounded bg-brand/15 text-brand">
              <IconSensor size={14} />
            </span>
            <span>Extended Telemetry — Simulator Contract</span>
            <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[9px] font-semibold text-ink-3 uppercase">
              {vm.extended.availability}
            </span>
          </div>
          <span className={`transform transition-transform duration-200 ${extendedOpen ? 'rotate-180' : ''}`}>
            <IconChevronDown size={16} />
          </span>
        </button>

        {extendedOpen && (
          <div className="p-3.5 pt-1 space-y-3">
            {/* Mandatory UI contract note */}
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-200/90 leading-relaxed">
              <div className="mb-1 flex items-center gap-1 text-[10px] font-bold uppercase text-amber-400">
                <IconInfo size={13} />
                <span>Architecture Notice</span>
              </div>
              {vm.extended.disclaimerNote}
            </div>

            {/* Gyroscope */}
            <div className="rounded-lg border border-hairline/70 bg-surface-3/40 p-2.5">
              <div className="mb-1.5 flex items-center justify-between text-xs">
                <span className="font-semibold text-ink">Gyroscope (Angular Velocity)</span>
                <span className="text-[10px] text-ink-3">
                  {vm.extended.gyroscope.isSupplied
                    ? 'Values supplied'
                    : vm.isLive
                    ? 'Not supplied by backend'
                    : 'Simulator contract (null)'}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded bg-surface-2/70 p-2">
                  <span className="text-[10px] text-ink-3">X: </span>
                  <span className="font-mono font-bold text-ink">
                    {vm.extended.gyroscope.x !== null ? `${vm.extended.gyroscope.x.toFixed(3)} °/s` : '—'}
                  </span>
                </div>
                <div className="rounded bg-surface-2/70 p-2">
                  <span className="text-[10px] text-ink-3">Y: </span>
                  <span className="font-mono font-bold text-ink">
                    {vm.extended.gyroscope.y !== null ? `${vm.extended.gyroscope.y.toFixed(3)} °/s` : '—'}
                  </span>
                </div>
                <div className="rounded bg-surface-2/70 p-2">
                  <span className="text-[10px] text-ink-3">Z: </span>
                  <span className="font-mono font-bold text-ink">
                    {vm.extended.gyroscope.z !== null ? `${vm.extended.gyroscope.z.toFixed(3)} °/s` : '—'}
                  </span>
                </div>
              </div>
            </div>

            {/* Accelerometer */}
            <div className="rounded-lg border border-hairline/70 bg-surface-3/40 p-2.5">
              <div className="mb-1.5 flex items-center justify-between text-xs">
                <span className="font-semibold text-ink">Accelerometer (Linear Acceleration)</span>
                <span className="text-[10px] text-ink-3">
                  {vm.extended.accelerometer.isSupplied
                    ? 'Values supplied'
                    : vm.isLive
                    ? 'Not supplied by backend'
                    : 'Simulator contract (null)'}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded bg-surface-2/70 p-2">
                  <span className="text-[10px] text-ink-3">X: </span>
                  <span className="font-mono font-bold text-ink">
                    {vm.extended.accelerometer.x !== null ? `${vm.extended.accelerometer.x.toFixed(2)} m/s²` : '—'}
                  </span>
                </div>
                <div className="rounded bg-surface-2/70 p-2">
                  <span className="text-[10px] text-ink-3">Y: </span>
                  <span className="font-mono font-bold text-ink">
                    {vm.extended.accelerometer.y !== null ? `${vm.extended.accelerometer.y.toFixed(2)} m/s²` : '—'}
                  </span>
                </div>
                <div className="rounded bg-surface-2/70 p-2">
                  <span className="text-[10px] text-ink-3">Z: </span>
                  <span className="font-mono font-bold text-ink">
                    {vm.extended.accelerometer.z !== null ? `${vm.extended.accelerometer.z.toFixed(2)} m/s²` : '—'}
                  </span>
                </div>
              </div>
            </div>

            {/* GPS Coordinates */}
            <div className="rounded-lg border border-hairline/70 bg-surface-3/40 p-2.5">
              <div className="mb-1.5 flex items-center justify-between text-xs">
                <span className="font-semibold text-ink">GPS Geolocation</span>
                <span className="text-[10px] text-ink-3">
                  {vm.extended.gps.isSupplied
                    ? 'Fix available'
                    : vm.isLive
                    ? 'Not supplied by backend'
                    : 'Simulator contract (null)'}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                <div className="rounded bg-surface-2/70 p-2">
                  <div className="text-[10px] text-ink-3">Latitude</div>
                  <div className="font-mono font-bold text-ink">
                    {vm.extended.gps.latitude !== null ? `${vm.extended.gps.latitude.toFixed(5)}°` : '—'}
                  </div>
                </div>
                <div className="rounded bg-surface-2/70 p-2">
                  <div className="text-[10px] text-ink-3">Longitude</div>
                  <div className="font-mono font-bold text-ink">
                    {vm.extended.gps.longitude !== null ? `${vm.extended.gps.longitude.toFixed(5)}°` : '—'}
                  </div>
                </div>
                <div className="rounded bg-surface-2/70 p-2">
                  <div className="text-[10px] text-ink-3">Altitude</div>
                  <div className="font-mono font-bold text-ink">
                    {vm.extended.gps.altitudeM !== null ? `${vm.extended.gps.altitudeM.toFixed(1)} m` : '—'}
                  </div>
                </div>
                <div className="rounded bg-surface-2/70 p-2">
                  <div className="text-[10px] text-ink-3">HDOP / Sats</div>
                  <div className="font-mono font-bold text-ink">
                    {vm.extended.gps.hdop !== null ? `HDOP ${vm.extended.gps.hdop}` : '—'} ·{' '}
                    {vm.extended.gps.satellites !== null ? `${vm.extended.gps.satellites}s` : '—'}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 8. Raw Payload Inspector (Collapsible) */}
      <div className="rounded-xl border border-hairline bg-surface-2/60 overflow-hidden">
        <div className="flex items-center justify-between bg-surface-3/40 px-3.5 py-2.5 text-xs font-semibold text-ink">
          <button
            type="button"
            onClick={() => setRawOpen((v) => !v)}
            className="flex items-center gap-1.5 text-ink hover:text-brand transition-colors"
          >
            <span>Raw Ingest Payload</span>
            <span className={`transform transition-transform duration-200 ${rawOpen ? 'rotate-180' : ''}`}>
              <IconChevronDown size={14} />
            </span>
          </button>

          <button
            type="button"
            onClick={handleCopyRaw}
            className="flex items-center gap-1 rounded bg-surface-2 px-2 py-1 text-[10px] font-medium text-ink-2 hover:bg-surface-3 hover:text-ink transition-colors"
          >
            {copied ? (
              <>
                <IconCheck size={12} className="text-good" />
                <span className="text-good">Copied!</span>
              </>
            ) : (
              <>
                <IconCopy size={12} />
                <span>Copy JSON</span>
              </>
            )}
          </button>
        </div>

        {rawOpen && (
          <div className="p-3">
            <pre className="max-h-56 overflow-x-auto rounded-lg bg-plane p-2.5 font-mono text-[11px] text-ink-2 leading-relaxed">
              {JSON.stringify(vm.rawPayload, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
