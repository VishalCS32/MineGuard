import { motion } from 'framer-motion';
import {
  IconDatabase, IconGateway, IconNodes, IconWifi,
} from '@/components/ui/icons';
import type { Kpis } from '@/data/types';

interface Props {
  kpis: Kpis;
  gatewayOnline: boolean;
  storagePct: number;
}

export function SystemHealth({ kpis, gatewayOnline, storagePct }: Props) {
  const items = [
    {
      Icon: IconGateway,
      label: 'Gateway',
      value: gatewayOnline ? 'Online' : 'Offline',
      tone: gatewayOnline ? 'text-good' : 'text-critical',
    },
    {
      Icon: IconNodes,
      label: 'Nodes',
      value: `${kpis.activeNodes} / ${kpis.totalNodes} Online`,
      tone: kpis.inactiveNodes === 0 ? 'text-good' : 'text-warning',
    },
    {
      Icon: IconWifi,
      label: 'Radio Link',
      value: `${kpis.packetDeliveryPct >= 90 ? 'Good' : 'Weak'} (${kpis.packetDeliveryPct.toFixed(1)}%)`,
      tone: kpis.packetDeliveryPct >= 90 ? 'text-good' : 'text-warning',
    },
    {
      Icon: IconDatabase,
      label: 'Storage',
      value: `${storagePct}% Used`,
      tone: storagePct < 90 ? 'text-good' : 'text-serious',
    },
  ];

  return (
    <div className="grid grid-cols-4 gap-2 px-3 pb-3">
      {items.map(({ Icon, label, value, tone }, i) => (
        <motion.div
          key={label}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 * i }}
          className="flex items-center gap-2 rounded-lg border border-hairline bg-surface-2/60 px-2 py-2"
        >
          <span className={`shrink-0 ${tone}`}><Icon size={19} /></span>
          <div className="min-w-0 leading-tight">
            <div className="truncate text-[10px] font-semibold text-ink">{label}</div>
            <div className={`truncate text-[10px] ${tone}`}>{value}</div>
          </div>
        </motion.div>
      ))}
    </div>
  );
}
