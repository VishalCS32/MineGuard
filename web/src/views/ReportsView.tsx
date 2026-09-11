import { Card } from '@/components/ui/Card';
import { IconCheck, IconDownload, IconReport, IconWarning } from '@/components/ui/icons';
import type { Snapshot } from '@/data/types';

interface Props {
  snap: Snapshot;
}

export function ReportsView({ snap }: Props) {
  const generatedAt = new Date().toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  const reportId = `MG-SHIFT-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}-01`;

  const downloadReportJson = () => {
    const reportData = {
      reportId,
      generatedAt,
      mineSite: 'Jharia Coalfield · Panel A',
      standards: 'DGMS Tech Circular 04/2019',
      kpis: snap.kpis,
      nodesCount: snap.nodes.length,
      activeAlertsCount: snap.alerts.length,
      nodes: snap.nodes.map((n) => ({
        id: n.id,
        label: n.label,
        tiltDeg: n.tiltDeg,
        vibrationMg: n.vibrationMg,
        strainMmPerM: n.strainMmPerM,
        batteryPct: n.batteryPct,
        online: n.online,
        risk: n.risk,
      })),
      alerts: snap.alerts,
    };

    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(reportData, null, 2));
    const link = document.createElement('a');
    link.setAttribute('href', dataStr);
    link.setAttribute('download', `${reportId}.json`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const downloadReportCsv = () => {
    const headers = ['Node ID', 'Label', 'Status', 'Tilt (deg)', 'Vibration (mg)', 'Strain (mm/m)', 'Battery (%)', 'Risk Band'];
    const rows = snap.nodes.map((n) => [
      n.id,
      n.label,
      n.online ? 'Online' : 'Offline',
      n.tiltDeg.toFixed(3),
      n.vibrationMg,
      n.strainMmPerM.toFixed(2),
      n.batteryPct,
      n.risk,
    ]);

    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map((e) => e.join(','))].join('\n');
    const link = document.createElement('a');
    link.setAttribute('href', encodeURI(csvContent));
    link.setAttribute('download', `${reportId}_nodes.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3 pb-12">
      {/* Top Action & Report Metadata */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-hairline bg-surface-2/70 px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand/15 text-brand">
            <IconReport size={18} />
          </span>
          <div>
            <div className="text-xs font-bold text-ink">DGMS Compliance Shift Report · {reportId}</div>
            <div className="text-[11px] text-ink-3">
              Generated at {generatedAt} · Target: Jharia Coalfield Panel A
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={downloadReportCsv}
            className="focus-ring flex items-center gap-1.5 rounded-lg bg-surface-3 px-3 py-1.5 text-xs font-semibold text-ink transition-colors hover:bg-surface hover:text-brand"
          >
            <IconDownload size={14} /> Export CSV
          </button>
          <button
            type="button"
            onClick={downloadReportJson}
            className="focus-ring flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-xs font-bold text-white shadow-glow transition-colors hover:bg-brand/80"
          >
            <IconDownload size={14} /> Download Full Audit (JSON)
          </button>
        </div>
      </div>

      {/* Main Report Document Container */}
      <Card
        title="Mine Stability & Ground Subsidence Inspection Audit"
        subtitle="Standard DGMS Form IV — Automated IoT Telemetry Record"
        className="flex min-h-0 flex-1 flex-col overflow-hidden"
      >
        <div className="flex flex-col gap-4 overflow-y-auto p-4 text-xs">
          {/* Executive Summary */}
          <div className="rounded-xl border border-hairline bg-surface-2/60 p-4">
            <div className="mb-3 text-xs font-bold text-brand uppercase tracking-wider">
              1. Executive Safety Summary
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-lg border border-hairline/60 bg-surface-3/50 p-2.5">
                <div className="text-[10px] text-ink-3">Max Surface Tilt</div>
                <div className="font-mono text-sm font-bold text-ink">
                  {snap.kpis.maxTiltDeg.toFixed(2)}°
                </div>
                <div className="text-[10px] text-ink-3">Limit: {snap.kpis.tiltThresholdDeg.toFixed(2)}°</div>
              </div>

              <div className="rounded-lg border border-hairline/60 bg-surface-3/50 p-2.5">
                <div className="text-[10px] text-ink-3">Max Ground Strain</div>
                <div className="font-mono text-sm font-bold text-ink">
                  {snap.kpis.maxStrainMmPerM.toFixed(2)} mm/m
                </div>
                <div className="text-[10px] text-ink-3">Limit: {snap.kpis.strainThresholdMmPerM.toFixed(2)} mm/m</div>
              </div>

              <div className="rounded-lg border border-hairline/60 bg-surface-3/50 p-2.5">
                <div className="text-[10px] text-ink-3">Sensor Availability</div>
                <div className="font-mono text-sm font-bold text-good">
                  {snap.kpis.activeNodes} / {snap.kpis.totalNodes} Online
                </div>
                <div className="text-[10px] text-ink-3">Uptime: {snap.kpis.uptimePct}%</div>
              </div>

              <div className="rounded-lg border border-hairline/60 bg-surface-3/50 p-2.5">
                <div className="text-[10px] text-ink-3">Overall Safety Clearance</div>
                <div className={`font-mono text-sm font-bold uppercase ${snap.kpis.healthy ? 'text-good' : 'text-critical'}`}>
                  {snap.kpis.healthy ? 'Normal (Cleared)' : 'Action Required'}
                </div>
                <div className="text-[10px] text-ink-3">{snap.kpis.totalAlerts} active notices</div>
              </div>
            </div>
          </div>

          {/* Node Status Table */}
          <div className="rounded-xl border border-hairline bg-surface-2/60 p-4">
            <div className="mb-2 text-xs font-bold text-brand uppercase tracking-wider">
              2. Mesh Node Sensor Verification Table
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[11px]">
                <thead>
                  <tr className="border-b border-hairline text-ink-3">
                    <th className="pb-1.5">ID</th>
                    <th className="pb-1.5">Label</th>
                    <th className="pb-1.5">Pitch Angle</th>
                    <th className="pb-1.5">Roll Angle</th>
                    <th className="pb-1.5">Resultant Tilt</th>
                    <th className="pb-1.5">Vibration RMS</th>
                    <th className="pb-1.5">Battery</th>
                    <th className="pb-1.5 text-right">Operational Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline/60 font-mono">
                  {snap.nodes.map((n) => (
                    <tr key={n.addr}>
                      <td className="py-2 text-ink">{n.id}</td>
                      <td className="py-2 font-sans font-medium text-ink">{n.label}</td>
                      <td className="py-2 text-sky-400">{n.tiltPitchDeg.toFixed(3)}°</td>
                      <td className="py-2 text-orange-400">{n.tiltRollDeg.toFixed(3)}°</td>
                      <td className="py-2 font-bold text-ink">{n.tiltDeg.toFixed(3)}°</td>
                      <td className="py-2 text-ink">{n.vibrationMg} mg</td>
                      <td className="py-2 text-ink">{n.batteryPct}%</td>
                      <td className="py-2 text-right font-sans">
                        <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${n.online ? 'bg-good/15 text-good' : 'bg-critical/15 text-critical'}`}>
                          {n.online ? 'Online' : 'Offline'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Active Incident Log */}
          <div className="rounded-xl border border-hairline bg-surface-2/60 p-4">
            <div className="mb-2 text-xs font-bold text-brand uppercase tracking-wider">
              3. Recorded Threshold Exceedances
            </div>
            {snap.alerts.length === 0 ? (
              <div className="flex items-center gap-2 text-xs text-good">
                <IconCheck size={16} /> Zero threshold breaches reported during this monitoring shift.
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {snap.alerts.map((a) => (
                  <div key={a.id} className="flex items-center justify-between rounded border border-hairline p-2 text-xs">
                    <div className="flex items-center gap-2">
                      <IconWarning size={15} className={a.severity === 'critical' ? 'text-critical' : 'text-warning'} />
                      <span className="font-semibold text-ink">{a.title}</span>
                      <span className="text-ink-3">({a.nodeId})</span>
                    </div>
                    <time className="font-mono text-[10px] text-ink-3">
                      {new Date(a.ts).toLocaleTimeString('en-IN')}
                    </time>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}
