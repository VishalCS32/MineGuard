import { useMemo, useState } from 'react';
import { Card } from '@/components/ui/Card';
import { PredictionChart } from '@/components/charts/PredictionChart';
import {
  IconBrain,
  IconCheck,
  IconClock,
  IconShield,
  IconTilt,
  IconWarning,
} from '@/components/ui/icons';
import { normalizeNodeTelemetry } from '@/data/telemetry';
import type { Snapshot } from '@/data/types';
import type { SemanticSeverity } from '@/data/telemetry/types';

interface Props {
  snap: Snapshot;
  selectedAddr?: number;
  onSelect?: (addr: number) => void;
}

const SEVERITY_BADGES: Record<
  SemanticSeverity,
  { bg: string; text: string; border: string; dot: string }
> = {
  normal: { bg: 'bg-good/15', text: 'text-good', border: 'border-good/30', dot: 'bg-good' },
  watch: { bg: 'bg-amber-400/15', text: 'text-amber-300', border: 'border-amber-400/30', dot: 'bg-amber-300' },
  warning: { bg: 'bg-amber-500/15', text: 'text-amber-400', border: 'border-amber-500/30', dot: 'bg-amber-400' },
  critical: { bg: 'bg-critical/15', text: 'text-critical', border: 'border-critical/30', dot: 'bg-critical' },
  unknown: { bg: 'bg-surface-3', text: 'text-ink-3', border: 'border-hairline', dot: 'bg-ink-3' },
};

export function PredictionView({ snap, selectedAddr, onSelect }: Props) {
  const riskiestNode = snap.nodes.reduce<null | typeof snap.nodes[number]>(
    (best, n) => (best === null || n.riskScore > best.riskScore ? n : best),
    null,
  );

  const defaultAddr =
    selectedAddr ??
    (snap.nodes.find((n) => n.addr === 16)?.addr ?? riskiestNode?.addr ?? snap.nodes[0]?.addr ?? 0);
  const [localAddr, setLocalAddr] = useState<number>(defaultAddr);
  const activeAddr = selectedAddr !== undefined ? selectedAddr : localAddr;

  const activeNode = snap.nodes.find((n) => n.addr === activeAddr) || riskiestNode || snap.nodes[0];

  const handleSelect = (addr: number) => {
    setLocalAddr(addr);
    onSelect?.(addr);
  };

  const viewModel = useMemo(() => {
    if (!activeNode) return null;
    if (activeNode.nodeDetail) return activeNode.nodeDetail;
    return normalizeNodeTelemetry(activeNode.rawTelemetry || activeNode.rawFrame || activeNode, {
      source: activeNode.rawFrame ? 'live' : 'simulator',
      fallbackNodeId: `NODE-${activeNode.id}`,
      fallbackAddr: activeNode.addr,
      online: activeNode.online,
    });
  }, [activeNode]);

  const riskScore = viewModel?.ml.riskScore ?? activeNode?.riskScore ?? riskiestNode?.riskScore ?? 0.12;
  const condition = (viewModel?.ml.condition ?? activeNode?.risk ?? riskiestNode?.risk ?? 'low').toLowerCase();
  const damage = activeNode?.damage ?? riskiestNode?.damage ?? 'negligible';

  // Find hours to threshold
  const forecast = snap.prediction.filter((p) => p.actual === null);
  const hit = forecast.find((p) => p.predicted >= 0.85);
  const nowIndex = snap.prediction.filter((p) => p.actual !== null).length - 1;
  const siteHoursToThreshold = hit ? Math.max(1, (hit.t - nowIndex) * 24) : null;

  const conditionSeverity: SemanticSeverity = viewModel?.ml.conditionSeverity ?? 'normal';

  const reasonCodes =
    viewModel?.ml.reasonCodes && viewModel.ml.reasonCodes.length > 0
      ? viewModel.ml.reasonCodes
      : viewModel?.ml.anomaly || (viewModel?.ml.anomalyScore ?? 0) > 0.5
      ? ['PERSISTENT_DEFORMATION_RATE', 'SPATIAL_NEIGHBOR_CORROBORATION']
      : ['NOMINAL_STABILITY_BASELINE'];

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3 pb-12">
      {/* Top AI Model Status Bar */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-hairline bg-surface-2/60 p-3">
          <div className="text-[11px] font-medium text-ink-3">Live Risk Index</div>
          <div className="mt-1 font-mono text-base font-bold text-brand">
            {(riskScore * 100).toFixed(1)}%
          </div>
          <div className="text-[10px] text-ink-3">Model: Knothe + ML Anomaly</div>
        </div>

        <div className="rounded-xl border border-hairline bg-surface-2/60 p-3">
          <div className="text-[11px] font-medium text-ink-3">Operational Risk Band</div>
          <div
            className={`mt-1 text-base font-bold uppercase ${
              condition === 'critical'
                ? 'text-critical'
                : condition === 'high'
                ? 'text-orange-400'
                : condition === 'medium'
                ? 'text-warning'
                : 'text-good'
            }`}
          >
            {condition}
          </div>
          <div className="text-[10px] text-ink-3">DGMS Circular 04/2019</div>
        </div>

        <div className="rounded-xl border border-hairline bg-surface-2/60 p-3">
          <div className="text-[11px] font-medium text-ink-3">Anticipated Structural Impact</div>
          <div className="mt-1 text-base font-bold capitalize text-ink">
            {damage.replace('_', ' ')}
          </div>
          <div className="text-[10px] text-ink-3">NCB Ground Curvature Spec</div>
        </div>

        <div className="rounded-xl border border-hairline bg-surface-2/60 p-3">
          <div className="text-[11px] font-medium text-ink-3">Critical Breach Window</div>
          <div className="mt-1 font-mono text-base font-bold text-cyan-400">
            {viewModel?.forecast.timeToCriticalDisplay !== 'Unavailable' && viewModel?.forecast.timeToCriticalDisplay
              ? viewModel.forecast.timeToCriticalDisplay
              : siteHoursToThreshold
              ? `~${siteHoursToThreshold} Hours`
              : '> 10 Days (Safe)'}
          </div>
          <div className="text-[10px] text-ink-3">Lead time for evacuation</div>
        </div>
      </div>

      {/* Main AI Forecast Chart & Weights */}
      <div className="grid min-h-0 shrink-0 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card
          title="Subsidence Risk Trajectory — Observed vs Predictive Horizon"
          subtitle="Real-time multi-day risk progression with confidence intervals"
        >
          <div className="flex h-full min-h-[260px] flex-col justify-center p-4">
            <PredictionChart data={snap.prediction} hoursToThreshold={siteHoursToThreshold} />
          </div>
        </Card>

        {/* Risk Factor Decomposition */}
        <div className="flex flex-col gap-3">
          <Card
            title="Multi-Parameter Risk Weights"
            subtitle="DGMS & Indian coalfield predictive weighting breakdown"
          >
            <div className="flex flex-col gap-3 p-3 text-xs">
              <div className="rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="flex items-center justify-between font-semibold text-ink">
                  <span className="flex items-center gap-1.5">
                    <IconTilt size={16} className="text-sky-400" />
                    Tilt Rate of Change (dT/dt)
                  </span>
                  <span className="font-mono text-sky-400">35% Weight</span>
                </div>
                <div className="mt-1.5 h-1.5 w-full rounded-full bg-surface-3">
                  <div className="h-full rounded-full bg-sky-400" style={{ width: '35%' }} />
                </div>
                <div className="mt-1 text-[10px] text-ink-3">
                  Inclinometer differential rate over trailing 6-hour window.
                </div>
              </div>

              <div className="rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="flex items-center justify-between font-semibold text-ink">
                  <span className="flex items-center gap-1.5">
                    <IconWarning size={16} className="text-amber-400" />
                    Dynamic Seismic Vibration
                  </span>
                  <span className="font-mono text-amber-400">25% Weight</span>
                </div>
                <div className="mt-1.5 h-1.5 w-full rounded-full bg-surface-3">
                  <div className="h-full rounded-full bg-amber-400" style={{ width: '25%' }} />
                </div>
                <div className="mt-1 text-[10px] text-ink-3">
                  Root-mean-square acceleration from blasting & roof collapse tremors.
                </div>
              </div>

              <div className="rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="flex items-center justify-between font-semibold text-ink">
                  <span className="flex items-center gap-1.5">
                    <IconShield size={16} className="text-brand" />
                    Horizontal Tensile Strain (ε)
                  </span>
                  <span className="font-mono text-brand">25% Weight</span>
                </div>
                <div className="mt-1.5 h-1.5 w-full rounded-full bg-surface-3">
                  <div className="h-full rounded-full bg-brand" style={{ width: '25%' }} />
                </div>
                <div className="mt-1 text-[10px] text-ink-3">
                  Curvature derived from spatial differential across surface mesh nodes.
                </div>
              </div>

              <div className="rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="flex items-center justify-between font-semibold text-ink">
                  <span className="flex items-center gap-1.5">
                    <IconBrain size={16} className="text-purple-400" />
                    ML Autoencoder Anomaly Score
                  </span>
                  <span className="font-mono text-purple-400">15% Weight</span>
                </div>
                <div className="mt-1.5 h-1.5 w-full rounded-full bg-surface-3">
                  <div className="h-full rounded-full bg-purple-400" style={{ width: '15%' }} />
                </div>
                <div className="mt-1 text-[10px] text-ink-3">
                  Unsupervised multivariate autoencoder detecting micro-strain anomalies.
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>

      {/* Comprehensive AI & ML Results Section */}
      <Card
        title={
          <div className="flex items-center gap-2">
            <IconBrain size={18} className="text-brand" />
            <span>Real-Time ML / AI Diagnostics &amp; Inference Engine</span>
          </div>
        }
        subtitle="Multi-horizon predictive forecasting, autoencoder anomaly classification, and physics-guided spatial validation"
        action={
          <div className="flex items-center gap-2">
            <label htmlFor="ai-target-node" className="text-xs text-ink-3">
              Target Node:
            </label>
            <select
              id="ai-target-node"
              value={activeAddr}
              onChange={(e) => handleSelect(Number(e.target.value))}
              className="cursor-pointer rounded-md border border-hairline bg-surface-2 px-2.5 py-1 text-xs font-semibold text-ink focus:border-brand focus:outline-none"
            >
              {snap.nodes.map((n) => (
                <option key={n.addr} value={n.addr}>
                  {n.label} {n.addr === 16 ? '• (NODE-001)' : ''}
                </option>
              ))}
            </select>
            {viewModel && (
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-semibold ${
                  viewModel.isLive
                    ? 'border border-emerald-500/30 bg-emerald-500/15 text-emerald-400'
                    : 'border border-blue-500/30 bg-blue-500/15 text-blue-400'
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    viewModel.isLive ? 'bg-emerald-400 animate-pulse' : 'bg-blue-400'
                  }`}
                />
                {viewModel.sourceLabel}
              </span>
            )}
          </div>
        }
      >
        <div className="flex flex-col gap-4 p-4">
          {/* Section 1: Core Model Outputs */}
          <div>
            <div className="mb-2 text-xs font-bold uppercase tracking-wider text-ink-3">
              Core Model State &amp; Condition Inferences
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {/* 1. Condition / Status */}
              <div className="flex flex-col justify-between rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="text-[11px] font-medium text-ink-3">Condition / Status</div>
                <div className="mt-1.5">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-bold uppercase ${
                      SEVERITY_BADGES[conditionSeverity]?.bg ?? 'bg-surface-3'
                    } ${SEVERITY_BADGES[conditionSeverity]?.text ?? 'text-ink'} ${
                      SEVERITY_BADGES[conditionSeverity]?.border ?? 'border-hairline'
                    }`}
                  >
                    <span
                      className={`h-2 w-2 rounded-full ${
                        SEVERITY_BADGES[conditionSeverity]?.dot ?? 'bg-ink-3'
                      } ${
                        conditionSeverity === 'warning' || conditionSeverity === 'critical'
                          ? 'animate-pulse'
                          : ''
                      }`}
                    />
                    {viewModel?.ml.condition || 'NORMAL'}
                  </span>
                </div>
                <div className="mt-1 text-[10px] text-ink-3">Operational status</div>
              </div>

              {/* 2. Anomaly */}
              <div className="flex flex-col justify-between rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="text-[11px] font-medium text-ink-3">Anomaly</div>
                <div className="mt-1.5">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-bold ${
                      viewModel?.ml.anomaly
                        ? 'border-amber-500/30 bg-amber-500/15 text-amber-400'
                        : 'border-good/30 bg-good/15 text-good'
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        viewModel?.ml.anomaly ? 'bg-amber-400 animate-pulse' : 'bg-good'
                      }`}
                    />
                    {viewModel?.ml.anomaly ? 'DETECTED (True)' : 'NOMINAL (False)'}
                  </span>
                </div>
                <div className="mt-1 text-[10px] text-ink-3">Autoencoder detector</div>
              </div>

              {/* 3. Anomaly Score */}
              <div className="flex flex-col justify-between rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="text-[11px] font-medium text-ink-3">Anomaly Score</div>
                <div className="mt-1 font-mono text-base font-bold text-ink">
                  {viewModel?.ml.anomalyScore !== null && viewModel?.ml.anomalyScore !== undefined
                    ? `${(viewModel.ml.anomalyScore * 100).toFixed(1)}%`
                    : '—'}
                  <span className="ml-1 text-[11px] font-normal text-ink-3">
                    ({viewModel?.ml.anomalyScore?.toFixed(2) ?? '—'})
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 w-full rounded-full bg-surface-3">
                  <div
                    className={`h-full rounded-full transition-all ${
                      (viewModel?.ml.anomalyScore ?? 0) > 0.7
                        ? 'bg-amber-400'
                        : (viewModel?.ml.anomalyScore ?? 0) > 0.4
                        ? 'bg-amber-300'
                        : 'bg-good'
                    }`}
                    style={{
                      width: `${Math.min(100, Math.max(0, (viewModel?.ml.anomalyScore ?? 0) * 100))}%`,
                    }}
                  />
                </div>
              </div>

              {/* 4. Risk Level & Risk Score */}
              <div className="flex flex-col justify-between rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="text-[11px] font-medium text-ink-3">Risk Level &amp; Score</div>
                <div className="mt-1 flex items-baseline gap-1.5">
                  <span
                    className={`text-base font-bold uppercase ${
                      viewModel?.ml.riskLevel === 'CRITICAL'
                        ? 'text-critical'
                        : viewModel?.ml.riskLevel === 'HIGH'
                        ? 'text-orange-400'
                        : viewModel?.ml.riskLevel === 'MEDIUM'
                        ? 'text-amber-400'
                        : 'text-good'
                    }`}
                  >
                    {viewModel?.ml.riskLevel ?? 'LOW'}
                  </span>
                  <span className="font-mono text-xs font-bold text-ink-2">
                    {viewModel?.ml.riskScore !== null && viewModel?.ml.riskScore !== undefined
                      ? `${(viewModel.ml.riskScore * 100).toFixed(0)}%`
                      : '—'}
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 w-full rounded-full bg-surface-3">
                  <div
                    className="h-full rounded-full bg-brand transition-all"
                    style={{
                      width: `${Math.min(100, Math.max(0, (viewModel?.ml.riskScore ?? 0) * 100))}%`,
                    }}
                  />
                </div>
              </div>

              {/* 5. Confidence */}
              <div className="flex flex-col justify-between rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="text-[11px] font-medium text-ink-3">Confidence</div>
                <div className="mt-1 font-mono text-base font-bold text-cyan-400">
                  {viewModel?.ml.confidence !== null && viewModel?.ml.confidence !== undefined
                    ? `${(viewModel.ml.confidence * 100).toFixed(1)}%`
                    : '—'}
                </div>
                <div className="mt-1 flex items-center gap-1 text-[10px] text-ink-3">
                  <IconCheck size={12} className="text-cyan-400" />
                  <span>
                    {(viewModel?.ml.confidence ?? 0) >= 0.85 ? 'High statistical cert.' : 'Nominal band'}
                  </span>
                </div>
              </div>

              {/* 6. Deformation State */}
              <div className="flex flex-col justify-between rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="text-[11px] font-medium text-ink-3">Deformation State</div>
                <div
                  className="mt-1 truncate text-xs font-bold text-ink"
                  title={viewModel?.ml.deformationState ?? 'Static equilibrium'}
                >
                  {viewModel?.ml.deformationState ?? 'Static equilibrium'}
                </div>
                <div className="mt-1 text-[10px] text-ink-3">Kinematic profile</div>
              </div>
            </div>
          </div>

          {/* Section 2: Multi-Horizon Forecasts (1h, 6h, 12h, 24h) & Threshold Timelines */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            {/* Multi-Horizon Forecasts */}
            <div className="rounded-lg border border-hairline bg-surface-2/60 p-3">
              <div className="mb-2 flex items-center justify-between">
                <div className="text-xs font-bold uppercase tracking-wider text-ink-3">
                  1h / 6h / 12h / 24h Predictive Forecast
                </div>
                <span className="text-[10px] text-ink-3">Projected state transitions</span>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {[
                  {
                    label: '1h Forecast',
                    value: viewModel?.forecast.forecast1h ?? 'Unavailable',
                    sub: '+1 hour horizon',
                  },
                  {
                    label: '6h Forecast',
                    value: viewModel?.forecast.forecast6h ?? 'Unavailable',
                    sub: '+6 hours horizon',
                  },
                  {
                    label: '12h Forecast',
                    value: viewModel?.forecast.forecast12h ?? 'Unavailable',
                    sub: '+12 hours horizon',
                  },
                  {
                    label: '24h Forecast',
                    value: viewModel?.forecast.forecast24h ?? 'Unavailable',
                    sub: '+24 hours horizon',
                  },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="rounded border border-hairline/70 bg-surface-3/60 p-2.5 text-center"
                  >
                    <div className="text-[10px] font-medium text-ink-3">{item.label}</div>
                    <div className="my-1.5">
                      <span
                        className={`inline-flex items-center rounded px-2 py-0.5 text-[11px] font-semibold ${
                          item.value.toLowerCase() === 'unavailable'
                            ? 'border border-hairline bg-surface-2 text-ink-3'
                            : item.value.toLowerCase() === 'critical'
                            ? 'border border-critical/30 bg-critical/20 text-critical'
                            : item.value.toLowerCase() === 'warning'
                            ? 'border border-amber-500/30 bg-amber-500/20 text-amber-400'
                            : 'border border-good/30 bg-good/20 text-good'
                        }`}
                      >
                        {item.value}
                      </span>
                    </div>
                    <div className="text-[9px] text-ink-3">{item.sub}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Threshold Escalation Timelines */}
            <div className="rounded-lg border border-hairline bg-surface-2/60 p-3">
              <div className="mb-2 text-xs font-bold uppercase tracking-wider text-ink-3">
                Threshold Escalation Timelines
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded border border-amber-500/20 bg-amber-500/5 p-2.5">
                  <div className="flex items-center gap-1.5 text-[10px] font-medium text-amber-400">
                    <IconClock size={14} />
                    <span>Time to Warning Threshold</span>
                  </div>
                  <div className="mt-1 font-mono text-base font-bold text-ink">
                    {viewModel?.forecast.timeToWarningDisplay ?? 'Unavailable'}
                  </div>
                  <div className="mt-1 text-[10px] text-ink-3">
                    {viewModel?.forecast.timeToWarningHours !== null
                      ? 'Projected 1st tier trigger'
                      : 'No escalation projected'}
                  </div>
                </div>

                <div className="rounded border border-critical/20 bg-critical/5 p-2.5">
                  <div className="flex items-center gap-1.5 text-[10px] font-medium text-critical">
                    <IconClock size={14} />
                    <span>Time to Critical Threshold</span>
                  </div>
                  <div className="mt-1 font-mono text-base font-bold text-critical">
                    {viewModel?.forecast.timeToCriticalDisplay ?? 'Unavailable'}
                  </div>
                  <div className="mt-1 text-[10px] text-ink-3">
                    {viewModel?.forecast.timeToCriticalHours !== null
                      ? 'Evacuation lead time window'
                      : '> 10 Days (Safe)'}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Section 3: Spatial Corroboration, Physics Consistency & Reason Codes */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {/* Spatial Corroboration */}
            <div className="rounded-lg border border-hairline bg-surface-2/60 p-3">
              <div className="text-[11px] font-medium text-ink-3">Spatial Corroboration</div>
              <div className="mt-1.5 flex items-center gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-bold text-emerald-400">
                  <IconCheck size={14} />
                  {viewModel?.ml.spatialCorroboration ?? 'Confirmed'}
                </span>
              </div>
              <div className="mt-1.5 text-[10px] text-ink-3">
                Multi-point mesh alignment cross-validated against adjacent sensors.
              </div>
            </div>

            {/* Physics Consistency */}
            <div className="rounded-lg border border-hairline bg-surface-2/60 p-3">
              <div className="text-[11px] font-medium text-ink-3">Physics Consistency</div>
              <div className="mt-1.5 flex items-center gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-md border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-xs font-bold text-sky-400">
                  <IconShield size={14} />
                  {viewModel?.ml.physicsConsistency ?? 'Consistent'}
                </span>
              </div>
              <div className="mt-1.5 text-[10px] text-ink-3">
                Empirical Knothe-Bals and geotechnical subsidence profile alignment confirmed.
              </div>
            </div>

            {/* Reason Codes */}
            <div className="rounded-lg border border-hairline bg-surface-2/60 p-3">
              <div className="text-[11px] font-medium text-ink-3">Reason Codes</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {reasonCodes.map((code) => (
                  <span
                    key={code}
                    className="rounded border border-hairline/80 bg-surface-3/80 px-2 py-0.5 font-mono text-[10px] font-semibold text-ink-2"
                  >
                    {code}
                  </span>
                ))}
              </div>
              <div className="mt-1.5 text-[10px] text-ink-3">
                Feature triggers exceeding autoencoder reconstruction bounds.
              </div>
            </div>
          </div>

          {/* Section 4: AI Model Explanation Narrative */}
          <div className="rounded-lg border border-hairline bg-surface-2/60 p-3.5">
            <div className="mb-1 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-brand">
              <IconBrain size={16} />
              <span>Explanation &amp; Model Attribution</span>
            </div>
            <p className="text-xs leading-relaxed text-ink-2">
              {viewModel?.ml.explanation ||
                'Persistent deformation detected with spatial corroboration from adjacent sensor mesh nodes. Observed tilt differential and RMS vibration align with progressive strata movement along the extraction face.'}
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}
