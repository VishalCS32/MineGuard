import { motion } from 'framer-motion';
import {
  IconBattery, IconBell, IconBrain, IconChart, IconClock, IconGear, IconGrid,
  IconHeart, IconHistory, IconMap, IconNodes, IconReport, IconShield,
} from '@/components/ui/icons';

export const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard', Icon: IconGrid },
  { key: 'live-map', label: 'Live Map', Icon: IconMap },
  { key: 'nodes', label: 'Nodes', Icon: IconNodes },
  { key: 'alerts', label: 'Alerts', Icon: IconBell },
  { key: 'analytics', label: 'Analytics', Icon: IconChart },
  { key: 'historical', label: 'Historical Data', Icon: IconHistory },
  { key: 'prediction', label: 'AI Prediction', Icon: IconBrain },
  { key: 'reports', label: 'Reports', Icon: IconReport },
  { key: 'settings', label: 'Settings', Icon: IconGear },
  { key: 'health', label: 'System Health', Icon: IconHeart },
] as const;

export type NavKey = (typeof NAV_ITEMS)[number]['key'];

interface Props {
  active: NavKey;
  onSelect: (key: NavKey) => void;
  alertCount: number;
  clock: Date;
  gatewayVolts: number;
  gatewayBatteryPct: number;
}

export function Sidebar({
  active, onSelect, alertCount, clock, gatewayVolts, gatewayBatteryPct,
}: Props) {
  return (
    <nav className="flex w-[212px] shrink-0 flex-col gap-1 border-r border-hairline bg-surface/40 p-3">
      {NAV_ITEMS.map(({ key, label, Icon }, i) => {
        const isActive = key === active;
        return (
          <motion.button
            key={key}
            type="button"
            onClick={() => onSelect(key)}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3, delay: 0.03 * i }}
            aria-current={isActive ? 'page' : undefined}
            className={`focus-ring relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[13px] font-medium transition-colors ${
              isActive ? 'text-white' : 'text-ink-2 hover:bg-surface-2 hover:text-ink'
            }`}
          >
            {isActive && (
              <motion.span
                layoutId="nav-active"
                transition={{ type: 'spring', stiffness: 380, damping: 32 }}
                className="absolute inset-0 -z-10 rounded-lg bg-gradient-to-r from-brand-dim to-brand/70 shadow-glow"
              />
            )}
            <Icon size={17} className={isActive ? 'text-white' : ''} />
            <span className="flex-1">{label}</span>
            {key === 'alerts' && alertCount > 0 && (
              <span className="grid h-[18px] min-w-[18px] place-items-center rounded-full bg-critical px-1 text-[10px] font-bold text-white">
                {alertCount}
              </span>
            )}
          </motion.button>
        );
      })}

      <div className="mt-auto space-y-2 pt-3">
        <div className="flex items-center gap-3 rounded-lg border border-hairline bg-surface-2/70 px-3 py-2.5">
          <IconClock size={18} className="text-ink-3" />
          <div className="leading-tight">
            <div className="font-mono text-[13px] font-semibold tabular-nums">
              {clock.toLocaleTimeString('en-IN', { hour12: true })}
            </div>
            <div className="text-[10px] text-ink-3">
              {clock.toLocaleDateString('en-IN', {
                day: '2-digit', month: 'short', year: 'numeric',
              })}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-lg border border-hairline bg-surface-2/70 px-3 py-2.5">
          <IconBattery size={18} className="text-brand" />
          <div className="leading-tight">
            <div className="text-[11px] font-semibold text-ink-2">Gateway Battery</div>
            <div className="text-[12px] font-semibold tabular-nums text-ink">
              {gatewayVolts.toFixed(1)} V
              <span className="text-ink-3"> • {gatewayBatteryPct}%</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5 px-1 pt-1 text-[10px] text-ink-3">
          <IconShield size={16} />
          <div className="leading-tight">
            <div>Powered by</div>
            <div className="font-semibold text-ink-2">MINEGUARD Team</div>
          </div>
        </div>
      </div>
    </nav>
  );
}
