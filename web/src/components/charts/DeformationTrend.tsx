import { motion } from 'framer-motion';
import { LineChart } from './LineChart';
import type { TrendPoint } from '@/data/types';

export const RANGES = ['1H', '6H', '24H', '7D'] as const;
export type Range = (typeof RANGES)[number];

interface Props {
  history: TrendPoint[];
  range: Range;
  onRange: (r: Range) => void;
}

const secondTimeLabel = (t: number) =>
  new Date(t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

const timeLabel = (t: number) =>
  new Date(t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });

/** Longer ranges need the day, or every tick reads as the same clock time. */
const dayTimeLabel = (t: number) =>
  new Date(t).toLocaleString('en-IN', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  });

export function DeformationTrend({ history, range, onRange }: Props) {
  // Check whether the dataset is a live high-frequency stream (timestamps under 4 hours span)
  const isLiveStream =
    history.length > 1 &&
    history[history.length - 1].t - history[0].t < 3600 * 1000 * 4;

  const windows: Record<Range, number> = isLiveStream
    ? { '1H': 30, '6H': 60, '24H': 120, '7D': 300 }
    : { '1H': 4, '6H': 24, '24H': 96, '7D': 672 };

  const data = history.slice(-windows[range]);
  const hasAnomalyScore = data.some((d) => d.anomalyScore !== undefined);

  const xTicks = data.length
    ? [0, 0.25, 0.5, 0.75, 1].map((f) => data[Math.round(f * (data.length - 1))].t)
    : [];

  const formatX = isLiveStream
    ? secondTimeLabel
    : range === '7D' || range === '24H'
    ? dayTimeLabel
    : timeLabel;

  const common = {
    formatX,
    xTickValues: xTicks,
    padLeft: 44,
  };

  return (
    <div className="flex h-full min-h-0 flex-col px-3 pb-2">
      <div className="mb-1 flex justify-end">
        <div className="flex gap-0.5 rounded-lg border border-hairline bg-surface-2 p-0.5">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => onRange(r)}
              className={`focus-ring relative rounded-md px-2.5 py-1 text-[10px] font-semibold transition-colors ${
                r === range ? 'text-white' : 'text-ink-3 hover:text-ink'
              }`}
            >
              {r === range && (
                <motion.span
                  layoutId="range-pill"
                  transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                  className="absolute inset-0 rounded-md bg-brand-dim"
                />
              )}
              <span className="relative">{r}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-0.5">
        <div>
          <div className="px-1 text-[10px] font-medium text-ink-3">Tilt (°)</div>
          <LineChart
            {...common}
            hideXAxis
            height={74}
            yTicks={2}
            unit="°"
            formatY={(v) => v.toFixed(2)}
            series={[
              { key: 'pitch', label: 'Pitch', color: '#258cff', points: data.map((d) => ({ x: d.t, y: d.pitch })) },
              { key: 'roll', label: 'Roll', color: '#e96100', points: data.map((d) => ({ x: d.t, y: d.roll })) },
            ]}
          />
        </div>

        <div>
          <div className="px-1 text-[10px] font-medium text-ink-3">Vibration RMS (mg)</div>
          <LineChart
            {...common}
            hideXAxis
            height={62}
            yTicks={2}
            yDomain={[0, Math.max(40, ...data.map((d) => d.vib)) * 1.15]}
            unit=" mg"
            showLegend={false}
            formatY={(v) => v.toFixed(0)}
            series={[
              { key: 'vib', label: 'Vibration RMS', color: '#00ab70', points: data.map((d) => ({ x: d.t, y: d.vib })) },
            ]}
          />
        </div>

        <div>
          <div className="px-1 text-[10px] font-medium text-ink-3">
            {hasAnomalyScore ? 'AI Anomaly Risk (%)' : 'Post temperature (°C)'}
          </div>
          <LineChart
            {...common}
            height={76}
            yTicks={2}
            yDomain={
              hasAnomalyScore
                ? [0, 100]
                : data.length
                ? [Math.min(...data.map((d) => d.tempC)) - 1, Math.max(...data.map((d) => d.tempC)) + 1]
                : [20, 35]
            }
            unit={hasAnomalyScore ? ' %' : ' °C'}
            showLegend={false}
            formatY={(v) => v.toFixed(hasAnomalyScore ? 0 : 1)}
            series={[
              hasAnomalyScore
                ? {
                    key: 'anomalyScore',
                    label: 'AI Anomaly Score',
                    color: '#9863ff',
                    points: data.map((d) => ({ x: d.t, y: d.anomalyScore ?? 0 })),
                  }
                : {
                    key: 'tempC',
                    label: 'Post temperature',
                    color: '#9863ff',
                    points: data.map((d) => ({ x: d.t, y: d.tempC })),
                  },
            ]}
          />
        </div>
      </div>
    </div>
  );
}
