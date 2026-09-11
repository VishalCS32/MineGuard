import { useState } from 'react';
import { Card } from '@/components/ui/Card';
import { IconBell, IconCheck, IconFilter, IconWarning } from '@/components/ui/icons';
import { EmptyState } from '@/components/ui/EmptyState';
import type { AlertItem } from '@/data/types';

interface Props {
  alerts: AlertItem[];
  onAckAlert?: (id: string) => void;
}

const SEVERITY_STYLES: Record<
  AlertItem['severity'],
  { ring: string; bg: string; text: string; badge: string; label: string }
> = {
  critical: {
    ring: 'border-l-critical',
    bg: 'bg-critical/10',
    text: 'text-critical',
    badge: 'bg-critical text-white',
    label: 'CRITICAL',
  },
  high: {
    ring: 'border-l-critical',
    bg: 'bg-critical/8',
    text: 'text-critical',
    badge: 'bg-critical text-white',
    label: 'HIGH',
  },
  medium: {
    ring: 'border-l-warning',
    bg: 'bg-warning/8',
    text: 'text-warning',
    badge: 'bg-warning text-black',
    label: 'MEDIUM',
  },
};

export function AlertsView({ alerts, onAckAlert }: Props) {
  const [severityFilter, setSeverityFilter] = useState<'all' | AlertItem['severity']>('all');
  const [searchTerm, setSearchTerm] = useState('');

  const filtered = alerts.filter((a) => {
    const matchesSev = severityFilter === 'all' || a.severity === severityFilter;
    const matchesSearch =
      a.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      a.nodeId.toLowerCase().includes(searchTerm.toLowerCase()) ||
      a.zone.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesSev && matchesSearch;
  });

  const criticalCount = alerts.filter((a) => a.severity === 'critical').length;
  const highCount = alerts.filter((a) => a.severity === 'high').length;
  const mediumCount = alerts.filter((a) => a.severity === 'medium').length;

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3 pb-12">
      {/* Alert KPI Summary Bar */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="flex items-center gap-3 rounded-xl border border-hairline bg-surface-2/60 p-3">
          <span className="grid h-10 w-10 place-items-center rounded-lg bg-critical/15 text-critical">
            <IconWarning size={20} />
          </span>
          <div>
            <div className="text-[11px] font-medium text-ink-3">Critical Breaches</div>
            <div className="text-base font-bold text-critical">{criticalCount} Standing</div>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-hairline bg-surface-2/60 p-3">
          <span className="grid h-10 w-10 place-items-center rounded-lg bg-orange-500/15 text-orange-400">
            <IconBell size={20} />
          </span>
          <div>
            <div className="text-[11px] font-medium text-ink-3">High Warnings</div>
            <div className="text-base font-bold text-orange-400">{highCount} Standing</div>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-hairline bg-surface-2/60 p-3">
          <span className="grid h-10 w-10 place-items-center rounded-lg bg-warning/15 text-warning">
            <IconFilter size={20} />
          </span>
          <div>
            <div className="text-[11px] font-medium text-ink-3">Medium / Advisory</div>
            <div className="text-base font-bold text-warning">{mediumCount} Standing</div>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-hairline bg-surface-2/60 p-3">
          <span className="grid h-10 w-10 place-items-center rounded-lg bg-good/15 text-good">
            <IconCheck size={20} />
          </span>
          <div>
            <div className="text-[11px] font-medium text-ink-3">Status Action</div>
            <div className="text-xs font-semibold text-good">
              {alerts.length === 0 ? 'No Active Alerts' : 'Acknowledge Below'}
            </div>
          </div>
        </div>
      </div>

      {/* Main Alert List Card */}
      <Card
        title="Active Early Warning Alerts"
        subtitle="DGMS compliant subsidence & ground acceleration threshold breaches"
        className="flex min-h-0 flex-1 flex-col"
        action={
          <div className="flex items-center gap-2">
            <div className="relative">
              <input
                type="text"
                placeholder="Filter alerts..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="rounded-md border border-hairline bg-surface-2 px-2.5 py-1 text-xs text-ink placeholder:text-ink-3 focus:border-brand focus:outline-none"
              />
            </div>

            <div className="flex rounded-lg border border-hairline bg-surface-2 p-0.5 text-xs">
              {(['all', 'critical', 'high', 'medium'] as const).map((sev) => (
                <button
                  key={sev}
                  type="button"
                  onClick={() => setSeverityFilter(sev)}
                  className={`rounded-md px-2.5 py-1 text-[11px] font-semibold capitalize transition-colors ${
                    severityFilter === sev
                      ? 'bg-brand text-white'
                      : 'text-ink-3 hover:text-ink'
                  }`}
                >
                  {sev}
                </button>
              ))}
            </div>
          </div>
        }
      >
        <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto p-3">
          {filtered.length === 0 ? (
            <EmptyState
              title={alerts.length === 0 ? 'Ground is Stable — Zero Breaches' : 'No alerts match the selected filter'}
              message="Telemetry values are currently within safe operational limits."
            />
          ) : (
            filtered.map((a) => {
              const style = SEVERITY_STYLES[a.severity] || SEVERITY_STYLES.medium;
              return (
                <div
                  key={a.id}
                  className={`flex flex-col gap-2 rounded-xl border border-hairline border-l-4 ${style.ring} ${style.bg} p-3.5`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <span className={`mt-0.5 shrink-0 ${style.text}`}>
                        <IconWarning size={20} />
                      </span>
                      <div>
                        <div className="flex items-center gap-2">
                          <h4 className={`text-sm font-bold ${style.text}`}>{a.title}</h4>
                          <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${style.badge}`}>
                            {style.label}
                          </span>
                        </div>
                        <div className="mt-0.5 text-xs text-ink-2">
                          Node: <span className="font-semibold text-ink">{a.nodeId}</span> &nbsp;·&nbsp;
                          Zone: <span className="font-medium">{a.zone}</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <time className="font-mono text-xs text-ink-3">
                        {new Date(a.ts).toLocaleTimeString('en-IN', {
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit',
                          hour12: true,
                        })}
                      </time>
                      {onAckAlert && (
                        <button
                          type="button"
                          onClick={() => onAckAlert(a.id)}
                          className="focus-ring flex items-center gap-1 rounded bg-surface-3 px-2.5 py-1 text-xs font-semibold text-ink transition-colors hover:bg-good hover:text-white"
                        >
                          <IconCheck size={13} /> Acknowledge
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="mt-1 flex flex-wrap items-center gap-4 border-t border-hairline/60 pt-2 text-xs text-ink-2">
                    {a.metrics.map((m) => (
                      <div key={m.label} className="flex items-center gap-1.5">
                        <span className="text-ink-3">{m.label}:</span>
                        <span className="font-mono font-bold text-ink">{m.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </Card>
    </div>
  );
}
