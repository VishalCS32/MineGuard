import { motion, useMotionValue, useSpring, useTransform } from 'framer-motion';
import { useEffect, type ReactNode } from 'react';
import {
  IconStrain, IconNodes, IconPacket, IconShield, IconTilt, IconWarning,
} from '@/components/ui/icons';
import type { Kpis } from '@/data/types';

/** Value that eases to its new target instead of snapping -- the movement itself
 *  tells the operator something changed. */
function AnimatedNumber({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const mv = useMotionValue(value);
  const spring = useSpring(mv, { stiffness: 90, damping: 20, mass: 0.6 });
  const text = useTransform(spring, (v) => v.toFixed(decimals));
  useEffect(() => { mv.set(value); }, [value, mv]);
  return <motion.span>{text}</motion.span>;
}

interface TileProps {
  label: string;
  value: ReactNode;
  sub: ReactNode;
  Icon: (p: { size?: number; className?: string }) => JSX.Element;
  tone: 'brand' | 's1' | 's4' | 'serious' | 's3' | 'good';
  index: number;
}

const TONES: Record<TileProps['tone'], { text: string; bg: string; ring: string }> = {
  brand: { text: 'text-brand', bg: 'bg-brand/18', ring: 'ring-brand/40' },
  s1: { text: 'text-s1', bg: 'bg-s1/18', ring: 'ring-s1/40' },
  s4: { text: 'text-s4', bg: 'bg-s4/18', ring: 'ring-s4/40' },
  serious: { text: 'text-serious', bg: 'bg-serious/18', ring: 'ring-serious/40' },
  s3: { text: 'text-s3', bg: 'bg-s3/18', ring: 'ring-s3/40' },
  good: { text: 'text-good', bg: 'bg-good/18', ring: 'ring-good/40' },
};

function Tile({ label, value, sub, Icon, tone, index }: TileProps) {
  const t = TONES[tone];
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay: index * 0.05, ease: [0.22, 1, 0.36, 1] }}
      whileHover={{ y: -2 }}
      className="panel flex items-center gap-3 px-3.5 py-3"
    >
      <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ring-1 ${t.bg} ${t.ring} ${t.text}`}>
        <Icon size={21} />
      </span>
      <div className="min-w-0 leading-tight">
        <div className="truncate text-[11px] font-medium text-ink-2">{label}</div>
        <div className="mt-0.5 font-mono tabular-nums text-[22px] font-semibold tracking-tight text-ink">{value}</div>
        <div className="mt-0.5 truncate text-[10px] text-ink-3">{sub}</div>
      </div>
    </motion.div>
  );
}

export function KpiRow({ kpis }: { kpis: Kpis }) {
  return (
    <div className="grid shrink-0 grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Tile
        index={0} tone="brand" Icon={IconNodes} label="Total Nodes"
        value={<AnimatedNumber value={kpis.totalNodes} />}
        sub={<>Active: {kpis.activeNodes} &nbsp; Inactive: {kpis.inactiveNodes}</>}
      />
      <Tile
        index={1} tone="s1" Icon={IconWarning} label="Total Alerts"
        value={<AnimatedNumber value={kpis.totalAlerts} />}
        sub={<>Critical: {kpis.criticalAlerts} &nbsp; High: {kpis.highAlerts}</>}
      />
      <Tile
        index={2} tone="s4" Icon={IconTilt} label="Max Tilt"
        value={<><AnimatedNumber value={kpis.maxTiltDeg} decimals={2} />°</>}
        sub={`Threshold: ${kpis.tiltThresholdDeg.toFixed(2)}°`}
      />
      <Tile
        index={3} tone="serious" Icon={IconStrain} label="Max Ground Strain"
        value={kpis.strainResolved
          ? <><AnimatedNumber value={kpis.maxStrainMmPerM} decimals={2} /> mm/m</>
          : <span className="text-ink-3">—</span>}
        sub={kpis.strainResolved
          ? `Threshold: ${kpis.strainThresholdMmPerM.toFixed(2)} mm/m`
          : 'Array too sparse to resolve'}
      />
      <Tile
        index={4} tone="s3" Icon={IconPacket} label="Packet Delivery"
        value={<><AnimatedNumber value={kpis.packetDeliveryPct} decimals={1} />%</>}
        sub={`Uptime: ${kpis.uptimePct.toFixed(1)}%`}
      />
      <Tile
        index={5} tone={kpis.healthy ? 'good' : 'serious'} Icon={IconShield} label="System Status"
        value={
          <span className={kpis.healthy ? 'text-good' : 'text-serious'}>
            {kpis.healthy ? 'Healthy' : 'Degraded'}
          </span>
        }
        sub={kpis.healthy ? 'All Systems Operational' : 'Critical deformation detected'}
      />
    </div>
  );
}
