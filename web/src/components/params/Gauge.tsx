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
  const arc = (fromDeg: number, toDeg: number) => {
    const [x1, y1] = toXY(fromDeg);
    const [x2, y2] = toXY(toDeg);
    const large = Math.abs(toDeg - fromDeg) > 180 ? 1 : 0;
    return `M${x1} ${y1} A${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
  };

  const end = START + SWEEP * Math.min(ratio, 1);

  return (
    <div className="flex flex-col items-center rounded-lg border border-hairline bg-surface-2/60 px-1.5 py-2">
      <div className="mb-0.5 text-center text-[10px] font-medium leading-tight text-ink-2">{label}</div>
      <svg width="88" height="58" viewBox="0 0 88 58" role="img" aria-label={`${label}: ${value.toFixed(decimals)} ${unit} of ${limit} limit`}>
        <path d={arc(START, START + SWEEP)} fill="none" stroke="#28374a" strokeWidth="6" strokeLinecap="round" />
        <motion.path
          d={arc(START, end)}
          fill="none"
          stroke={colour}
          strokeWidth="6"
          strokeLinecap="round"
          initial={false}
          animate={{ d: arc(START, end) }}
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
