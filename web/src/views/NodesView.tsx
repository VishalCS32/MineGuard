import { useMemo, useState } from 'react';
import { Card } from '@/components/ui/Card';
import { IconBattery, IconNodes, IconSensor, IconWifi } from '@/components/ui/icons';
import { NodeDetailPanel } from '@/components/nodes/NodeDetailPanel';
import { normalizeNodeTelemetry } from '@/data/telemetry';
import type { NodeReading } from '@/data/types';

interface Props {
  nodes: NodeReading[];
  selectedAddr: number;
  onSelect: (addr: number) => void;
}

export function NodesView({ nodes, selectedAddr, onSelect }: Props) {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterOnline, setFilterOnline] = useState<'all' | 'online' | 'offline'>('all');

  const selectedNode = nodes.find((n) => n.addr === selectedAddr) || nodes[0];

  const filteredNodes = useMemo(() => {
    return nodes.filter((n) => {
      if (filterOnline === 'online' && !n.online) return false;
      if (filterOnline === 'offline' && n.online) return false;
      if (searchTerm.trim()) {
        const query = searchTerm.toLowerCase();
        return (
          n.label.toLowerCase().includes(query) ||
          n.zone.toLowerCase().includes(query) ||
          String(n.id).toLowerCase().includes(query) ||
          String(n.addr).toLowerCase().includes(query)
        );
      }
      return true;
    });
  }, [nodes, filterOnline, searchTerm]);

  const viewModel = useMemo(() => {
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
      {/* Node Metrics Summary */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="flex items-center gap-3 rounded-xl border border-hairline bg-surface-2/60 p-3">
          <span className="grid h-10 w-10 place-items-center rounded-lg bg-brand/15 text-brand">
            <IconNodes size={20} />
          </span>
          <div>
            <div className="text-[11px] font-medium text-ink-3">Total Deployed Nodes</div>
            <div className="text-base font-bold text-ink">{nodes.length} Units</div>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-hairline bg-surface-2/60 p-3">
          <span className="grid h-10 w-10 place-items-center rounded-lg bg-good/15 text-good">
            <IconWifi size={20} />
          </span>
          <div>
            <div className="text-[11px] font-medium text-ink-3">Online Telemetry Stream</div>
            <div className="text-base font-bold text-good">
              {nodes.filter((n) => n.online).length} / {nodes.length} Active
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-hairline bg-surface-2/60 p-3">
          <span className="grid h-10 w-10 place-items-center rounded-lg bg-warning/15 text-warning">
            <IconBattery size={20} />
          </span>
          <div>
            <div className="text-[11px] font-medium text-ink-3">Battery Health</div>
            <div className="text-base font-bold text-ink">
              {Math.round(nodes.reduce((acc, n) => acc + n.batteryPct, 0) / Math.max(1, nodes.length))}% Avg
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-hairline bg-surface-2/60 p-3">
          <span className="grid h-10 w-10 place-items-center rounded-lg bg-cyan-500/15 text-cyan-400">
            <IconSensor size={20} />
          </span>
          <div>
            <div className="text-[11px] font-medium text-ink-3">Telemetry Frequency</div>
            <div className="text-base font-bold text-cyan-400">1.0 Hz Real-Time</div>
          </div>
        </div>
      </div>

      {/* Main Grid: Left is Node List, Right is Selected Node Inspector */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        {/* Node List Card */}
        <Card
          title="Deployed Sensor Units"
          subtitle="Click to inspect real-time sensor streams and diagnostic frames"
          action={
            <div className="flex items-center gap-2">
              <div className="relative">
                <input
                  type="text"
                  placeholder="Search nodes..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="rounded-md border border-hairline bg-surface-2 px-2.5 py-1 text-xs text-ink placeholder:text-ink-3 focus:border-brand focus:outline-none"
                />
              </div>
              <select
                value={filterOnline}
                onChange={(e) => setFilterOnline(e.target.value as any)}
                className="rounded-md border border-hairline bg-surface-2 px-2 py-1 text-xs text-ink focus:border-brand focus:outline-none cursor-pointer"
              >
                <option value="all">All Status</option>
                <option value="online">Online Only</option>
                <option value="offline">Offline Only</option>
              </select>
            </div>
          }
        >
          <div className="flex flex-col gap-2 p-3">
            {filteredNodes.map((n) => {
              const isSelected = n.addr === selectedAddr;
              const hasRaw = !!n.rawFrame;
              return (
                <div
                  key={n.addr}
                  onClick={() => onSelect(n.addr)}
                  className={`flex cursor-pointer items-center justify-between rounded-lg border p-3 transition-all ${
                    isSelected
                      ? 'border-brand bg-brand/10 shadow-glow'
                      : 'border-hairline bg-surface-2/60 hover:bg-surface-2'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span
                      className={`grid h-8 w-8 place-items-center rounded-lg text-xs font-bold ${
                        isSelected ? 'bg-brand text-white' : 'bg-surface-3 text-ink-2'
                      }`}
                    >
                      {n.id}
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-ink">{n.label}</span>
                        {hasRaw && (
                          <span className="rounded bg-brand/20 px-1.5 py-0.5 text-[9px] font-bold text-brand uppercase">
                            Live Stream
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-ink-3">
                        {n.zone} · {n.lat.toFixed(4)}° N, {n.lon.toFixed(4)}° E
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-4 text-right">
                    <div className="text-[11px]">
                      <div className="font-mono text-xs font-semibold text-ink">
                        Tilt: {n.tiltDeg.toFixed(2)}°
                      </div>
                      <div className="text-ink-3">Vib: {n.vibrationMg} mg</div>
                    </div>

                    <div className="flex flex-col items-end gap-1">
                      <span
                        className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                          n.online ? 'bg-good/15 text-good' : 'bg-critical/15 text-critical'
                        }`}
                      >
                        <span className={`h-1.5 w-1.5 rounded-full ${n.online ? 'bg-good animate-pulse' : 'bg-critical'}`} />
                        {n.online ? 'Online' : 'Offline'}
                      </span>
                      <span className="text-[10px] tabular-nums text-ink-3">
                        Bat: {n.batteryPct}%
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        {/* Selected Node Rich Detail Inspector */}
        <div className="flex flex-col gap-3">
          {viewModel ? (
            <NodeDetailPanel viewModel={viewModel} />
          ) : (
            <Card title="Telemetry Inspector" subtitle="Select a node to inspect details">
              <div className="p-8 text-center text-sm text-ink-3">No node selected</div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
