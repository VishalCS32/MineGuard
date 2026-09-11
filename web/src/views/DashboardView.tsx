import { useMemo, useState } from 'react';
import { Card } from '@/components/ui/Card';
import { KpiRow } from '@/components/kpi/KpiRow';
import { MapPanel } from '@/components/map/MapPanel';
import { PredictionChart } from '@/components/charts/PredictionChart';
import { DeformationTrend, type Range } from '@/components/charts/DeformationTrend';
import { AlertsPanel, ViewAllButton } from '@/components/alerts/AlertsPanel';
import { ParamsPanel } from '@/components/params/ParamsPanel';
import { NodeDetailModal } from '@/components/nodes/NodeDetailModal';
import { normalizeNodeTelemetry } from '@/data/telemetry';
import { SystemHealth } from '@/components/health/SystemHealth';
import { DataFlow } from '@/components/health/DataFlow';
import type { Snapshot, TrendPoint } from '@/data/types';
import type { SourceMode } from '@/data/createSource';

interface Props {
  snap: Snapshot;
  history: TrendPoint[];
  range: Range;
  onRange: (r: Range) => void;
  selectedAddr: number;
  onSelect: (addr: number) => void;
  onToggleNode?: (addr: number) => void;
  sourceMode: SourceMode;
  onNavigateAlerts?: () => void;
}

function hoursToThreshold(snap: Snapshot | null): number | null {
  if (!snap) return null;
  const forecast = snap.prediction.filter((p) => p.actual === null);
  const hit = forecast.find((p) => p.predicted >= 0.85);
  if (!hit) return null;
  const now = snap.prediction.filter((p) => p.actual !== null).length - 1;
  return Math.max(1, (hit.t - now) * 24);
}

export function DashboardView({
  snap,
  history,
  range,
  onRange,
  selectedAddr,
  onSelect,
  onToggleNode,
  sourceMode,
  onNavigateAlerts,
}: Props) {
  const [inspectModalOpen, setInspectModalOpen] = useState(false);
  const selectedNode = snap.nodes.find((n) => n.addr === selectedAddr) || snap.nodes[0];

  const selectedViewModel = useMemo(() => {
    if (!selectedNode) return null;
    if (selectedNode.nodeDetail) return selectedNode.nodeDetail;
    return normalizeNodeTelemetry(selectedNode.rawTelemetry || selectedNode.rawFrame || selectedNode, {
      source: selectedNode.rawFrame ? 'live' : 'simulator',
      fallbackNodeId: `NODE-${selectedNode.id}`,
      fallbackAddr: selectedNode.addr,
      online: selectedNode.online,
    });
  }, [selectedNode]);

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3 pb-12">
      <KpiRow kpis={snap.kpis} />

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-[minmax(0,2.05fr)_minmax(0,1fr)]">
        {/* Left column */}
        <div className="flex min-h-0 flex-col gap-3">
          <Card
            title="Live Subsidence Map"
            subtitle={
              sourceMode === 'remote'
                ? `Live Telemetry Site · NODE-001 at ${snap.nodes[0]?.lat?.toFixed(4) ?? '28.6139'}° N, ${snap.nodes[0]?.lon?.toFixed(4) ?? '77.2090'}° E`
                : `Jharia Panel L-7 · face at ${snap.faceX.toFixed(0)} m`
            }
            className="min-h-[340px] flex-1"
            delay={0.05}
          >
            <MapPanel
              nodes={snap.nodes}
              links={snap.links}
              day={snap.day}
              selectedAddr={selectedAddr}
              onSelect={onSelect}
              onToggleNode={onToggleNode}
            />
          </Card>

          <div className="grid shrink-0 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <Card title="AI Prediction — Subsidence Risk" delay={0.12}>
              <PredictionChart
                data={snap.prediction}
                hoursToThreshold={hoursToThreshold(snap)}
              />
            </Card>

            <Card
              title="Deformation Trend"
              subtitle={
                selectedNode
                  ? selectedNode.addr === 16 && sourceMode === 'remote'
                    ? 'Node 01 (NODE-001) · Live API Stream (mineguard-api.tenant.eu.org)'
                    : `Node ${selectedNode.id} · ${selectedNode.zone}`
                  : ''
              }
              delay={0.16}
            >
              <DeformationTrend history={history} range={range} onRange={onRange} />
            </Card>
          </div>
        </div>

        {/* Right column */}
        <div className="flex min-h-0 flex-col gap-3">
          <Card
            title="Latest Alerts"
            action={<ViewAllButton onClick={onNavigateAlerts} />}
            className="min-h-[180px] flex-1"
            delay={0.08}
          >
            <AlertsPanel alerts={snap.alerts} />
          </Card>

          <Card
            className="shrink-0"
            title="Real-Time Parameters"
            delay={0.14}
            action={
              <select
                value={selectedAddr}
                onChange={(e) => onSelect(Number(e.target.value))}
                className="focus-ring rounded-md border border-hairline bg-surface-2 px-2 py-1 text-[11px] text-ink cursor-pointer"
                aria-label="Select node"
              >
                {snap.nodes.map((n) => (
                  <option key={n.addr} value={n.addr}>
                    Node {n.id} {n.addr === 16 && sourceMode === 'remote' ? '• NODE-001 (Live)' : ''}{n.online ? '' : ' (offline)'}
                  </option>
                ))}
              </select>
            }
          >
            <ParamsPanel
              node={selectedNode}
              onInspect={() => setInspectModalOpen(true)}
            />
          </Card>

          <Card className="shrink-0" title="System Health" delay={0.2}>
            <SystemHealth kpis={snap.kpis} gatewayOnline storagePct={snap.storagePct} />
          </Card>

          <Card className="shrink-0" title="Data Flow" delay={0.24}>
            <DataFlow />
          </Card>
        </div>
      </div>

      {inspectModalOpen && selectedViewModel && (
        <NodeDetailModal
          viewModel={selectedViewModel}
          isOpen={inspectModalOpen}
          onClose={() => setInspectModalOpen(false)}
        />
      )}
    </div>
  );
}
