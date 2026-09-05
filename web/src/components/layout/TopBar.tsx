import { motion } from 'framer-motion';
import { IconBell, IconCloud, IconShield, IconUser } from '@/components/ui/icons';

interface Props {
  alertCount: number;
  online: boolean;
}

export function TopBar({ alertCount, online }: Props) {
  return (
    <header className="flex h-16 shrink-0 items-center gap-4 border-b border-hairline bg-surface/60 px-4 backdrop-blur">
      {/* Brand */}
      <div className="flex w-[196px] shrink-0 items-center gap-2.5">
        <motion.span
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 260, damping: 18 }}
          className="grid h-9 w-9 place-items-center rounded-lg bg-brand/12 text-brand ring-1 ring-brand/30"
        >
          <IconShield size={20} />
        </motion.span>
        <div className="leading-none">
          <div className="text-[17px] font-bold tracking-tight">
            MINE<span className="text-brand">GUARD</span>
          </div>
          <div className="mt-0.5 text-[10px] font-medium tracking-wide text-ink-3">
            Smart Subsidence. Safer Mines.
          </div>
        </div>
      </div>

      {/* Title */}
      <motion.h1
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.1 }}
        className="min-w-0 flex-1 truncate text-center text-[15px] font-bold uppercase tracking-[0.05em] text-brand"
      >
        MineGuard — AI Enabled Smart Mine Subsidence Monitoring System
      </motion.h1>

      {/* Status cluster */}
      <div className="flex shrink-0 items-center gap-4">
        <div className="flex items-center gap-2 text-xs">
          <IconCloud size={16} className={online ? 'text-brand' : 'text-ink-3'} />
          <span className="text-ink-2">Cloud Sync:</span>
          <span className={online ? 'font-semibold text-brand' : 'font-semibold text-ink-3'}>
            {online ? 'Online' : 'Offline'}
          </span>
        </div>

        <button
          type="button"
          className="focus-ring relative grid h-9 w-9 place-items-center rounded-lg text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
          aria-label={`${alertCount} active alerts`}
        >
          <IconBell size={18} />
          {alertCount > 0 && (
            <motion.span
              key={alertCount}
              initial={{ scale: 0.5 }}
              animate={{ scale: 1 }}
              transition={{ type: 'spring', stiffness: 420, damping: 16 }}
              className="absolute -right-0.5 -top-0.5 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-critical px-1 text-[10px] font-bold text-white"
            >
              {alertCount}
            </motion.span>
          )}
        </button>

        <div className="flex items-center gap-2.5 border-l border-hairline pl-4">
          <span className="grid h-9 w-9 place-items-center rounded-full bg-surface-3 text-ink-2">
            <IconUser size={18} />
          </span>
          <div className="leading-tight">
            <div className="text-[13px] font-semibold">Admin</div>
            <div className="text-[10px] text-ink-3">Mine Operator</div>
          </div>
        </div>
      </div>
    </header>
  );
}
