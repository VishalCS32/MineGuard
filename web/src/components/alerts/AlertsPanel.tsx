import { AnimatePresence, motion } from 'framer-motion';
import { IconChevron, IconWarning } from '@/components/ui/icons';
import type { AlertItem } from '@/data/types';

const TONE: Record<AlertItem['severity'], { ring: string; bg: string; text: string; pill: string; label: string }> = {
  critical: {
    ring: 'border-l-critical', bg: 'bg-critical/10', text: 'text-critical',
    pill: 'bg-critical text-white', label: 'CRITICAL',
  },
  high: {
    ring: 'border-l-critical', bg: 'bg-critical/8', text: 'text-critical',
    pill: 'bg-critical text-white', label: 'HIGH',
  },
  medium: {
    ring: 'border-l-warning', bg: 'bg-warning/8', text: 'text-warning',
    pill: 'bg-warning text-black', label: 'MEDIUM',
  },
};

export function AlertsPanel({ alerts }: { alerts: AlertItem[] }) {
  return (
    <div
      className="flex h-full min-h-0 flex-col gap-2 overflow-y-auto px-3 pb-3"
      style={{
        maskImage: 'linear-gradient(to bottom, #000 calc(100% - 28px), transparent)',
        WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 28px), transparent)',
      }}
    >
      {/* Sync mode, not popLayout: popLayout takes exiting cards out of flow
          and paints them over the incoming one mid-transition. */}
      <AnimatePresence initial={false}>
        {alerts.slice(0, 6).map((a) => {
          const t = TONE[a.severity];
          return (
            <motion.article
              key={a.id}
              layout
              initial={{ opacity: 0, x: 24, scale: 0.97 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, height: 0, marginBottom: -8, transition: { duration: 0.18 } }}
              transition={{ type: 'spring', stiffness: 320, damping: 30 }}
              className={`rounded-lg border border-hairline border-l-[3px] ${t.ring} ${t.bg} px-3 py-2.5`}
            >
              <div className="flex items-start gap-2.5">
                {/* Icon + label, so severity never rides on colour alone. */}
                <span className={`mt-0.5 shrink-0 ${t.text}`} aria-hidden="true">
                  <IconWarning size={17} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <h3 className={`truncate text-[13px] font-semibold ${t.text}`}>{a.title}</h3>
                    <time className="shrink-0 text-[10px] tabular-nums text-ink-3">
                      {new Date(a.ts).toLocaleTimeString('en-IN', {
                        hour: '2-digit', minute: '2-digit', hour12: true,
                      })}
                    </time>
                  </div>
                  <p className="mt-0.5 text-[11px] text-ink-2">
                    Node ID: {a.nodeId} &nbsp;·&nbsp; Zone: {a.zone}
                  </p>
                  <div className="mt-1 flex items-center justify-between gap-2">
                    <p className="truncate text-[11px] text-ink-2">
                      {a.metrics.map((m) => `${m.label}: ${m.value}`).join('  •  ')}
                    </p>
                    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold tracking-wide ${t.pill}`}>
                      {t.label}
                    </span>
                  </div>
                </div>
              </div>
            </motion.article>
          );
        })}
      </AnimatePresence>

      {alerts.length === 0 && (
        <div className="grid flex-1 place-items-center text-center text-[12px] text-ink-3">
          <div>
            <div className="mb-1 text-good">
              <IconWarning size={22} className="mx-auto opacity-40" />
            </div>
            No active alerts — ground is stable
          </div>
        </div>
      )}
    </div>
  );
}

export function ViewAllButton() {
  return (
    <button
      type="button"
      className="focus-ring flex items-center gap-1 rounded px-1 text-[11px] font-medium text-ink-2 transition-colors hover:text-brand"
    >
      View All <IconChevron size={13} />
    </button>
  );
}
