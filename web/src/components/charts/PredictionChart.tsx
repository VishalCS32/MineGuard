import { motion } from 'framer-motion';
import { LineChart, type Series } from './LineChart';
import type { PredictionPoint } from '@/data/types';

interface Props {
  data: PredictionPoint[];
  hoursToThreshold: number | null;
}

/** Actual vs forecast risk. The forecast arm is dashed and the observed series
 *  simply stops, so the boundary between measurement and prediction is visible
 *  in the mark itself rather than only in the legend. */
export function PredictionChart({ data, hoursToThreshold }: Props) {
  const series: Series[] = [
    {
      key: 'actual',
      label: 'Actual risk score',
      color: '#3987e5',
      points: data.map((d) => ({ x: d.t, y: d.actual })),
    },
    {
      key: 'predicted',
      label: 'Predicted risk score',
      color: '#d95926',
      dashed: true,
      points: data.map((d) => ({ x: d.t, y: d.predicted })),
    },
  ];

  const dayLabel = (t: number) => {
    const d = new Date();
    d.setDate(d.getDate() - (7 - t));
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  };

  const lead =
    hoursToThreshold === null
      ? null
      : hoursToThreshold > 48
        ? `${Math.round(hoursToThreshold / 24)}–${Math.round(hoursToThreshold / 24) + 1} days`
        : `${Math.round(hoursToThreshold)} hours`;

  return (
    <div className="relative h-full px-3 pb-2">
      <LineChart
        series={series}
        height={168}
        yDomain={[0, 1]}
        yTicks={5}
        formatY={(v) => v.toFixed(1)}
        formatX={dayLabel}
        xTickValues={[0, 2, 4, 6, 8, 10]}
      />
      {lead && (
        <motion.div
          initial={{ opacity: 0, scale: 0.92 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ type: 'spring', stiffness: 300, damping: 22, delay: 0.4 }}
          className="absolute right-5 top-8 rounded-lg border border-critical/40 bg-critical/15 px-3 py-2 text-right backdrop-blur"
        >
          <div className="text-[11px] font-bold text-critical">High Risk</div>
          <div className="text-[10px] text-ink-2">in {lead}</div>
        </motion.div>
      )}
    </div>
  );
}
