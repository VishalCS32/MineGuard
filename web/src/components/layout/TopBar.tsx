import { motion } from 'framer-motion';
import { IconBell, IconCloud, IconLogout, IconShield, IconUser } from '@/components/ui/icons';
import type { SourceStatus } from '@/data/source';
import type { SourceMode } from '@/data/createSource';
import type { UserProfile } from '@/api/auth';

interface Props {
  alertCount: number;
  status: SourceStatus;
  mode?: SourceMode;
  onModeChange?: (mode: SourceMode) => void;
  onNavigateAlerts?: () => void;
  user?: UserProfile | null;
  onLogout?: () => void;
  onOpenLogin?: () => void;
}

export function TopBar({
  alertCount,
  status,
  mode = 'remote',
  onModeChange,
  onNavigateAlerts,
  user,
  onLogout,
  onOpenLogin,
}: Props) {
  // Three honest states, never a green light that means nothing: live and
  // connected, live but the link has dropped, or running on the local model.
  const live = status.kind === 'live';
  const label = live ? (status.connected ? 'Online' : 'Reconnecting…') : 'Local model';
  const tone = live && status.connected ? 'text-brand'
    : live ? 'text-warning' : 'text-ink-2';
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

      {/* Status & Source cluster */}
      <div className="flex shrink-0 items-center gap-3">
        {onModeChange && (
          <div className="flex items-center gap-1.5 rounded-lg border border-hairline bg-surface-2 p-1 text-xs">
            <span className="px-1 text-[10px] font-medium text-ink-3 uppercase">Feed:</span>
            <select
              value={mode}
              onChange={(e) => onModeChange(e.target.value as SourceMode)}
              className="rounded bg-surface-3 px-2 py-1 text-xs font-semibold text-brand outline-none cursor-pointer hover:bg-surface-3/80 transition-colors"
            >
              <option value="remote">Live Node API (NODE-001)</option>
              <option value="simulated">Built-in Simulator</option>
              <option value="local">Local Backend (Port 8000)</option>
            </select>
          </div>
        )}

        <div className="flex items-center gap-1.5 text-xs" title={status.detail ?? ''}>
          <IconCloud size={16} className={tone} />
          <span className={`font-semibold ${tone}`}>{label}</span>
          {status.connected && (
            <span className="inline-block h-2 w-2 rounded-full bg-brand animate-pulse" />
          )}
        </div>

        <button
          type="button"
          onClick={onNavigateAlerts}
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
          {user ? (
            <>
              <span className="grid h-9 w-9 place-items-center rounded-full bg-brand/15 text-brand ring-1 ring-brand/30">
                <IconUser size={18} />
              </span>
              <div className="leading-tight max-w-[130px]">
                <div className="truncate text-[13px] font-semibold text-ink" title={user.name}>
                  {user.name}
                </div>
                <div
                  className="truncate text-[10px] text-ink-3"
                  title={user.email || user.phoneNumber || 'Mine Operator'}
                >
                  {user.role === 'admin'
                    ? 'Administrator'
                    : user.email || user.phoneNumber || 'Mine Operator'}
                </div>
              </div>

              {onLogout && (
                <button
                  type="button"
                  onClick={onLogout}
                  className="focus-ring ml-1 grid h-8 w-8 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-critical/15 hover:text-critical"
                  title="Sign Out"
                  aria-label="Sign out of MineGuard"
                >
                  <IconLogout size={16} />
                </button>
              )}
            </>
          ) : (
            <button
              type="button"
              onClick={onOpenLogin}
              className="group flex items-center gap-2.5 rounded-lg py-1 px-2 transition-colors hover:bg-surface-2 cursor-pointer text-left border border-transparent hover:border-hairline"
              title="Click to Sign In"
            >
              <span className="grid h-9 w-9 place-items-center rounded-full bg-surface-3 text-ink-2 group-hover:bg-brand/15 group-hover:text-brand transition-colors">
                <IconUser size={18} />
              </span>
              <div className="leading-tight max-w-[130px]">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-[13px] font-semibold text-ink group-hover:text-brand transition-colors">
                    Sign In
                  </span>
                  <span className="rounded bg-brand/15 px-1 py-0.5 text-[9px] font-bold text-brand uppercase tracking-wider">
                    Login
                  </span>
                </div>
                <div className="truncate text-[10px] text-ink-3">
                  Mine Operator
                </div>
              </div>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
