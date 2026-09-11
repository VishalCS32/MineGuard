import { Card } from '@/components/ui/Card';
import { LineChart } from '@/components/charts/LineChart';
import type { Range } from '@/components/charts/DeformationTrend';
import type { TrendPoint } from '@/data/types';

interface Props {
  history: TrendPoint[];
  range: Range;
  onRange: (r: Range) => void;
  nodeLabel?: string;
}

const secondTimeLabel = (t: number) =>
  new Date(t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

const timeLabel = (t: number) =>
  new Date(t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });

const dayTimeLabel = (t: number) =>
  new Date(t).toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });

export function AnalyticsView({ history, range, onRange, nodeLabel = 'NODE-001 (Live)' }: Props) {
  const isLiveStream = history.length > 1 && history[history.length - 1].t - history[0].t < 3600 * 1000 * 4;

  const windows: Record<Range, number> = isLiveStream
    ? { '1H': 30, '6H': 60, '24H': 120, '7D': 300 }
    : { '1H': 4, '6H': 24, '24H': 96, '7D': 672 };

  const data = history.slice(-windows[range]);

  const xTicks = data.length
    ? [0, 0.25, 0.5, 0.75, 1].map((f) => data[Math.round(f * (data.length - 1))].t)
    : [];

  const formatX = isLiveStream ? secondTimeLabel : range === '7D' || range === '24H' ? dayTimeLabel : timeLabel;

  const common = {
    formatX,
    xTickValues: xTicks,
    padLeft: 44,
  };

  const peakPitch = data.reduce((max, d) => Math.max(max, Math.abs(d.pitch)), 0);
  const peakRoll = data.reduce((max, d) => Math.max(max, Math.abs(d.roll)), 0);
  const peakVib = data.reduce((max, d) => Math.max(max, d.vib), 0);
  const avgAnomaly = Math.round(data.reduce((acc, d) => acc + (d.anomalyScore ?? 0), 0) / Math.max(1, data.length));

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3 pb-12">
      {/* Analytics KPI Stat Row */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-hairline bg-surface-2/60 p-3">
          <div className="text-[11px] font-medium text-ink-3">Peak Pitch Angle</div>
          <div className="mt-1 font-mono text-base font-bold text-sky-400">{peakPitch.toFixed(3)}°</div>
          <div className="text-[10px] text-ink-3">Threshold: 0.60°</div>
        </div>

        <div className="rounded-xl border border-hairline bg-surface-2/60 p-3">
          <div className="text-[11px] font-medium text-ink-3">Peak Roll Angle</div>
          <div className="mt-1 font-mono text-base font-bold text-orange-400">{peakRoll.toFixed(3)}°</div>
          <div className="text-[10px] text-ink-3">Threshold: 0.60°</div>
        </div>

        <div className="rounded-xl border border-hairline bg-surface-2/60 p-3">
          <div className="text-[11px] font-medium text-ink-3">Peak Dynamic Vibration</div>
          <div className="mt-1 font-mono text-base font-bold text-amber-400">{peakVib} mg</div>
          <div className="text-[10px] text-ink-3">Safe Limit: 200 mg</div>
        </div>

        <div className="rounded-xl border border-hairline bg-surface-2/60 p-3">
          <div className="text-[11px] font-medium text-ink-3">Mean ML Anomaly Score</div>
          <div className="mt-1 font-mono text-base font-bold text-brand">{avgAnomaly}%</div>
          <div className="text-[10px] text-ink-3">Baseline: &lt; 45%</div>
        </div>
      </div>

      {/* Main Multi-Channel Charts */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-2">
        {/* Tilt Channel */}
        <Card
          title="Inclinometer Tilt Decomposition"
          subtitle={`${nodeLabel} · Pitch & Roll orthogonal channels`}
          action={
            <div className="flex gap-0.5 rounded-lg border border-hairline bg-surface-2 p-0.5">
              {(['1H', '6H', '24H', '7D'] as const).map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => onRange(r)}
                  className={`rounded-md px-2 py-0.5 text-[10px] font-semibold transition-colors ${
                    r === range ? 'bg-brand text-white' : 'text-ink-3 hover:text-ink'
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
          }
        >
          <div className="p-3">
            <LineChart
              {...common}
              height={180}
              yTicks={4}
              unit="°"
              formatY={(v) => v.toFixed(2)}
              series={[
                { key: 'pitch', label: 'Pitch (X)', color: '#38bdf8', points: data.map((d) => ({ x: d.t, y: d.pitch })) },
                { key: 'roll', label: 'Roll (Y)', color: '#fb923c', points: data.map((d) => ({ x: d.t, y: d.roll })) },
              ]}
            />
          </div>
        </Card>

        {/* Vibration Channel */}
        <Card
          title="Dynamic Seismic & Machinery Vibration"
          subtitle={`${nodeLabel} · High-frequency RMS envelope`}
        >
          <div className="p-3">
            <LineChart
              {...common}
              height={180}
              yTicks={4}
              unit=" mg"
              formatY={(v) => Math.round(v).toString()}
              series={[
                { key: 'vib', label: 'RMS Vibration', color: '#eab308', points: data.map((d) => ({ x: d.t, y: d.vib })) },
              ]}
            />
          </div>
        </Card>

        {/* AI ML Anomaly Score Progression */}
        <Card
          title="AI Anomaly Score Correlation"
          subtitle={`${nodeLabel} · Machine Learning risk index (0–100%)`}
        >
          <div className="p-3">
            <LineChart
              {...common}
              height={180}
              yTicks={4}
              yDomain={[0, 100]}
              unit="%"
              formatY={(v) => `${Math.round(v)}%`}
              series={[
                {
                  key: 'anomaly',
                  label: 'Anomaly Score',
                  color: '#10b981',
                  points: data.map((d) => ({ x: d.t, y: d.anomalyScore ?? 10 })),
                },
              ]}
            />
          </div>
        </Card>

        {/* Combined Resultant Motion */}
        <Card
          title="Resultant Ground Motion Magnitude"
          subtitle={`${nodeLabel} · Vector magnitude √(Pitch² + Roll²)`}
        >
          <div className="p-3">
            <LineChart
              {...common}
              height={180}
              yTicks={4}
              unit="°"
              formatY={(v) => v.toFixed(2)}
              series={[
                {
                  key: 'resultant',
                  label: 'Resultant Tilt',
                  color: '#a855f7',
                  points: data.map((d) => ({ x: d.t, y: Math.hypot(d.pitch, d.roll) })),
                },
              ]}
            />
          </div>
        </Card>
      </div>
    </div>
  );
}
