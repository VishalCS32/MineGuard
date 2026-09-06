import { motion } from 'framer-motion';

interface Props {
  label: string;
  value: number;
  limit: number;
  unit: string;
  decimals?: number;
  /** Secondary reading in the physically-native unit, shown under the value. */
  note?: string;
}

const START = -125;
const SWEEP = 250;

/** Radial meter: one ratio against a limit.
 *  The fill carries severity and the unfilled track is a muted step of the same
 *  ramp, so state reads across the whole arc. The numeric value and the limit are
 *  both printed -- the arc is the at-a-glance layer, not the only layer. */
export function Gauge({ label, value, limit, unit, decimals = 2, note }: Props) {
  const ratio = Math.max(0, Math.min(1.15, value / limit));
  const colour = ratio >= 1 ? '#e80038' : ratio >= 0.75 ? '#ff7a00' : ratio >= 0.5 ? '#f2dc00' : '#00c14f';

  const r = 32;
  const cx = 44;
  const cy = 40;
  const toXY = (deg: number) => {
    const rad = ((deg - 90) * Math.PI) / 180;
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
  };

  // One static arc path for both track and fill.
  //
  // The fill is revealed with a dash offset rather than by animating `d`.
  // Interpolating a path string interpolates *every* number in it, including an
  // arc command's large-arc and sweep flags -- which are booleans, so a tween
  // emits `A32 32 0 0.76 1 ...` mid-flight and the browser rejects the path.
  // pathLength normalises the arc to 1 so the offset is just the ratio.
  const [x1, y1] = toXY(START);
  const [x2, y2] = toXY(START + SWEEP);
  const largeArc = SWEEP > 180 ? 1 : 0;
  const track = `M${x1} ${y1} A${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`;
  const filled = Math.min(ratio, 1);

  return (
    <div className="flex flex-col items-center rounded-lg border border-hairline bg-surface-2/60 px-1.5 py-2">
      <div className="mb-0.5 text-center text-[10px] font-medium leading-tight text-ink-2">{label}</div>
      <svg
        width="88" height="58" viewBox="0 0 88 58" role="img"
        aria-label={`${label}: ${value.toFixed(decimals)} ${unit}, limit ${limit}`}
      >
        <path d={track} fill="none" stroke="#28374a" strokeWidth="6" strokeLinecap="round" />
        <motion.path
          d={track}
          fill="none"
          stroke={colour}
          strokeWidth="6"
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray="1 1"
          initial={false}
          animate={{ strokeDashoffset: 1 - filled }}
          transition={{ type: 'spring', stiffness: 90, damping: 18 }}
        />
      </svg>
      <div className="-mt-3.5 text-center">
        <div className="text-[17px] font-semibold leading-none tracking-tight" style={{ color: colour }}>
          {value.toFixed(decimals)}
        </div>
        <div className="mt-0.5 text-[9px] text-ink-3">{unit}</div>
        <div className="text-[9px] text-ink-3">{note ?? `Limit: ${limit.toFixed(decimals)}`}</div>
      </div>
    </div>
  );
}
