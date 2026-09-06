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

const timeLabel = (t: number) =>
  new Date(t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });

/** Longer ranges need the day, or every tick reads as the same clock time. */
const dayTimeLabel = (t: number) =>
  new Date(t).toLocaleString('en-IN', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  });

/**
 * Three stacked panels sharing one time axis, rather than the more common single
 * plot with two y-scales.
 *
 * Tilt (degrees), vibration (mg) and crack width (mm) are three different
 * quantities on three different scales. Overlaying them on a shared axis, or on
 * two axes, makes their crossings look meaningful when the alignment is entirely
 * arbitrary -- an operator would read a correlation that is not in the data. Small
 * multiples keep every series honestly on its own scale while the shared x-axis
 * still lets you read them against each other in time, which is the actual
 * question: did the crack open when the tilt accelerated?
 */
export function DeformationTrend({ history, range, onRange }: Props) {
  // One sample every 15 simulated minutes, so each range is an exact sample count.
  const windows: Record<Range, number> = { '1H': 4, '6H': 24, '24H': 96, '7D': 672 };
  const data = history.slice(-windows[range]);

  const xTicks = data.length
    ? [0, 0.25, 0.5, 0.75, 1].map((f) => data[Math.round(f * (data.length - 1))].t)
    : [];

  const common = {
    formatX: range === '7D' || range === '24H' ? dayTimeLabel : timeLabel,
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
          <div className="px-1 text-[10px] font-medium text-ink-3">Crack width (mm)</div>
          <LineChart
            {...common}
            height={76}
            yTicks={2}
            yDomain={[0, Math.max(0.5, ...data.map((d) => d.crack)) * 1.2]}
            unit=" mm"
            showLegend={false}
            formatY={(v) => v.toFixed(2)}
            series={[
              { key: 'crack', label: 'Crack width', color: '#9863ff', points: data.map((d) => ({ x: d.t, y: d.crack })) },
            ]}
          />
        </div>
      </div>
    </div>
  );
}
