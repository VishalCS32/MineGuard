import { useState } from 'react';
import { Card } from '@/components/ui/Card';
import { IconDownload, IconHistory, IconRefresh } from '@/components/ui/icons';
import type { TrendPoint } from '@/data/types';

interface Props {
  history: TrendPoint[];
  nodeLabel?: string;
  onRefresh?: () => void;
}

export function HistoricalView({ history, nodeLabel = 'NODE-001 (Live)', onRefresh }: Props) {
  const [pageSize, setPageSize] = useState<number>(15);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [timeRange, setTimeRange] = useState<'1H' | '6H' | '24H' | 'all'>('all');

  // Filter history records based on selected time range
  const now = Date.now();
  const rangeCutoff =
    timeRange === '1H' ? now - 3600 * 1000 : timeRange === '6H' ? now - 6 * 3600 * 1000 : timeRange === '24H' ? now - 24 * 3600 * 1000 : 0;

  const records = history.filter((r) => r.t >= rangeCutoff).slice().reverse();

  const totalPages = Math.max(1, Math.ceil(records.length / pageSize));
  const pagedRecords = records.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  // CSV Export
  const exportCsv = () => {
    const headers = ['Timestamp', 'ISO Time', 'Pitch (deg)', 'Roll (deg)', 'Resultant Tilt (deg)', 'Vibration (mg)', 'ML Anomaly Score (%)'];
    const rows = records.map((r) => [
      r.t,
      new Date(r.t).toISOString(),
      r.pitch.toFixed(3),
      r.roll.toFixed(3),
      Math.hypot(r.pitch, r.roll).toFixed(3),
      r.vib,
      r.anomalyScore ?? 0,
    ]);

    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map((e) => e.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `mineguard_history_${nodeLabel.replace(/\s+/g, '_')}_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // JSON Export
  const exportJson = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(records, null, 2));
    const link = document.createElement('a');
    link.setAttribute('href', dataStr);
    link.setAttribute('download', `mineguard_history_${nodeLabel.replace(/\s+/g, '_')}_${Date.now()}.json`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3 pb-12">
      {/* Top Filter & Export Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-hairline bg-surface-2/70 px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand/15 text-brand">
            <IconHistory size={18} />
          </span>
          <div>
            <div className="text-xs font-bold text-ink">Historical Telemetry Ingress Log</div>
            <div className="text-[11px] text-ink-3">
              {records.length} samples recorded for {nodeLabel}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Time Filter */}
          <div className="flex rounded-lg border border-hairline bg-surface-2 p-0.5 text-xs">
            {(['1H', '6H', '24H', 'all'] as const).map((range) => (
              <button
                key={range}
                type="button"
                onClick={() => {
                  setTimeRange(range);
                  setCurrentPage(1);
                }}
                className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition-colors uppercase ${
                  timeRange === range ? 'bg-brand text-white' : 'text-ink-3 hover:text-ink'
                }`}
              >
                {range}
              </button>
            ))}
          </div>

          {/* Page size select */}
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setCurrentPage(1);
            }}
            className="rounded-md border border-hairline bg-surface-2 px-2 py-1 text-xs text-ink focus:border-brand focus:outline-none cursor-pointer"
          >
            <option value={15}>15 rows</option>
            <option value={30}>30 rows</option>
            <option value={50}>50 rows</option>
            <option value={100}>100 rows</option>
          </select>

          {/* Export Actions */}
          <button
            type="button"
            onClick={exportCsv}
            className="focus-ring flex items-center gap-1.5 rounded-lg bg-surface-3 px-3 py-1 text-xs font-semibold text-ink transition-colors hover:bg-surface hover:text-brand"
          >
            <IconDownload size={14} /> Export CSV
          </button>

          <button
            type="button"
            onClick={exportJson}
            className="focus-ring flex items-center gap-1.5 rounded-lg bg-surface-3 px-3 py-1 text-xs font-semibold text-ink transition-colors hover:bg-surface hover:text-cyan-400"
          >
            <IconDownload size={14} /> Export JSON
          </button>

          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              className="focus-ring flex items-center gap-1 rounded-lg bg-surface-3 px-2 py-1 text-xs text-ink-2 hover:text-ink"
              title="Refresh records"
            >
              <IconRefresh size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Main Historical Table Card */}
      <Card
        title="Recorded Sensor Telemetry Frames"
        subtitle="Chronological sequence with pitch, roll, resultant tilt, and vibration RMS"
        className="flex min-h-0 flex-1 flex-col overflow-hidden"
      >
        <div className="flex min-h-0 flex-1 flex-col overflow-x-auto p-3">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-hairline text-[11px] font-semibold uppercase text-ink-3">
                <th className="pb-2 pl-2">Time (Local)</th>
                <th className="pb-2">Pitch Angle</th>
                <th className="pb-2">Roll Angle</th>
                <th className="pb-2">Resultant Tilt</th>
                <th className="pb-2">Vibration RMS</th>
                <th className="pb-2">Anomaly Score</th>
                <th className="pb-2 pr-2 text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline/60 font-mono text-[11px]">
              {pagedRecords.map((r, i) => {
                const resultantTilt = Math.hypot(r.pitch, r.roll);
                const isTiltBreach = resultantTilt >= 0.6;
                const isVibBreach = r.vib > 200;
                const isAnomaly = (r.anomalyScore ?? 0) >= 45;

                return (
                  <tr key={i} className="hover:bg-surface-2/40 transition-colors">
                    <td className="py-2 pl-2 text-ink">
                      {new Date(r.t).toLocaleTimeString('en-IN', {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                        hour12: true,
                      })}
                      <span className="ml-1 text-[10px] text-ink-3">
                        {new Date(r.t).toLocaleDateString('en-IN', { month: 'short', day: 'numeric' })}
                      </span>
                    </td>
                    <td className="py-2 text-sky-400">{r.pitch.toFixed(3)}°</td>
                    <td className="py-2 text-orange-400">{r.roll.toFixed(3)}°</td>
                    <td className={`py-2 font-bold ${isTiltBreach ? 'text-critical' : 'text-brand'}`}>
                      {resultantTilt.toFixed(3)}°
                    </td>
                    <td className={`py-2 ${isVibBreach ? 'text-warning font-bold' : 'text-ink'}`}>
                      {r.vib} mg
                    </td>
                    <td className="py-2">
                      <span className={`${isAnomaly ? 'text-critical font-bold' : 'text-good'}`}>
                        {r.anomalyScore ?? 0}%
                      </span>
                    </td>
                    <td className="py-2 pr-2 text-right font-sans">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${
                          isTiltBreach || isAnomaly
                            ? 'bg-critical/15 text-critical'
                            : isVibBreach
                            ? 'bg-warning/15 text-warning'
                            : 'bg-good/15 text-good'
                        }`}
                      >
                        {isTiltBreach || isAnomaly ? 'Warning' : 'Normal'}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {records.length === 0 && (
            <div className="grid flex-1 place-items-center py-12 text-center text-xs text-ink-3">
              No historical records found for the selected time range.
            </div>
          )}

          {/* Pagination Controls */}
          {records.length > 0 && (
            <div className="mt-auto flex items-center justify-between border-t border-hairline/80 pt-3 text-xs text-ink-3">
              <div>
                Showing {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, records.length)} of {records.length} records
              </div>

              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  className="rounded px-2.5 py-1 text-xs font-semibold text-ink hover:bg-surface-2 disabled:opacity-30"
                >
                  Previous
                </button>
                <span className="px-2 font-mono text-ink">
                  {currentPage} / {totalPages}
                </span>
                <button
                  type="button"
                  disabled={currentPage >= totalPages}
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  className="rounded px-2.5 py-1 text-xs font-semibold text-ink hover:bg-surface-2 disabled:opacity-30"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
