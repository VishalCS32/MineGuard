import { Card } from '@/components/ui/Card';
import { MapPanel } from '@/components/map/MapPanel';
import type { MeshLink, NodeReading } from '@/data/types';
import { IconCrosshair } from '@/components/ui/icons';

interface Props {
  nodes: NodeReading[];
  links: MeshLink[];
  day: number;
  faceX: number;
  selectedAddr: number;
  onSelect: (addr: number) => void;
  onToggleNode?: (addr: number) => void;
}

export function LiveMapView({
  nodes,
  links,
  day,
  faceX,
  selectedAddr,
  onSelect,
  onToggleNode,
}: Props) {
  const selectedNode = nodes.find((n) => n.addr === selectedAddr) || nodes[0];

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 pb-6">
      {/* Top Telemetry & Anchor Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-hairline bg-surface-2/70 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand/15 text-brand">
            <IconCrosshair size={18} />
          </span>
          <div>
            <div className="text-xs font-bold text-ink">
              Live Sensor Field Transect · NODE-001 Anchor
            </div>
            <div className="text-[11px] text-ink-3">
              GPS Coordinates: {selectedNode?.lat?.toFixed(5)}° N, {selectedNode?.lon?.toFixed(5)}° E · Face Advance: {faceX.toFixed(0)} m
            </div>
          </div>
        </div>

        {selectedNode && (
          <div className="flex items-center gap-4 text-xs">
            <div className="flex items-center gap-1.5 border-r border-hairline pr-4">
              <span className="text-ink-3">Selected:</span>
              <span className="font-semibold text-brand">{selectedNode.label}</span>
              <span className={`inline-block h-2 w-2 rounded-full ${selectedNode.online ? 'bg-good animate-pulse' : 'bg-critical'}`} />
            </div>

            <div className="flex items-center gap-3 font-mono text-[11px]">
              <div>
                <span className="text-ink-3">Pitch: </span>
                <span className="font-semibold text-ink">{selectedNode.tiltPitchDeg.toFixed(2)}°</span>
              </div>
              <div>
                <span className="text-ink-3">Roll: </span>
                <span className="font-semibold text-ink">{selectedNode.tiltRollDeg.toFixed(2)}°</span>
              </div>
              <div>
                <span className="text-ink-3">Vib: </span>
                <span className="font-semibold text-ink">{selectedNode.vibrationMg} mg</span>
              </div>
              <div>
                <span className="text-ink-3">Risk: </span>
                <span className={`font-semibold uppercase ${selectedNode.risk === 'critical' ? 'text-critical' : selectedNode.risk === 'high' ? 'text-warning' : 'text-good'}`}>
                  {selectedNode.risk}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Main Full-Height Map Card */}
      <Card
        title="Surface Subsidence & Displacement Terrain"
        subtitle="Real-time multi-node deployment & mesh radio link topology"
        className="flex min-h-[500px] flex-1 flex-col overflow-hidden"
      >
        <div className="h-full w-full min-h-[460px] flex-1">
          <MapPanel
            nodes={nodes}
            links={links}
            day={day}
            selectedAddr={selectedAddr}
            onSelect={onSelect}
            onToggleNode={onToggleNode}
          />
        </div>
      </Card>
    </div>
  );
}
