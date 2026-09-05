import { useEffect, useMemo, useRef, useState } from 'react';
import { TopBar } from '@/components/layout/TopBar';
import { Sidebar, type NavKey } from '@/components/layout/Sidebar';
import { Footer } from '@/components/layout/Footer';
import { KpiRow } from '@/components/kpi/KpiRow';
import { Card } from '@/components/ui/Card';
import { MapPanel } from '@/components/map/MapPanel';
import { PredictionChart } from '@/components/charts/PredictionChart';
import { DeformationTrend, type Range } from '@/components/charts/DeformationTrend';
import { AlertsPanel, ViewAllButton } from '@/components/alerts/AlertsPanel';
import { ParamsPanel } from '@/components/params/ParamsPanel';
import { SystemHealth } from '@/components/health/SystemHealth';
import { DataFlow } from '@/components/health/DataFlow';
import { SimulatedSource } from '@/sim/feed';
import type { Snapshot, TrendPoint } from '@/data/types';

/**
 * Hours until the forecast risk crosses into the High band.
 *
 * A countdown, not a red light: "tilt crosses the limit in about 14 hours" is
 * something a shift supervisor can act on, where a severity colour is not.
 */
function hoursToThreshold(snap: Snapshot | null): number | null {
  if (!snap) return null;
  const forecast = snap.prediction.filter((p) => p.actual === null);
  const hit = forecast.find((p) => p.predicted >= 0.85);
  if (!hit) return null;
  const now = snap.prediction.filter((p) => p.actual !== null).length - 1;
  return Math.max(1, (hit.t - now) * 24);
}

export default function App() {
  const sourceRef = useRef<SimulatedSource | null>(null);
  if (sourceRef.current === null) sourceRef.current = new SimulatedSource();
  const source = sourceRef.current;

  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [history, setHistory] = useState<TrendPoint[]>([]);
  const [nav, setNav] = useState<NavKey>('dashboard');
  const [range, setRange] = useState<Range>('24H');
  const [selected, setSelected] = useState<number | null>(null);
  const [clock, setClock] = useState(new Date());

  useEffect(() => {
    const unsub = source.subscribe(setSnap);
    source.start();
    return () => {
      unsub();
      source.stop();
    };
  }, [source]);

  useEffect(() => {
    const id = window.setInterval(() => setClock(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  // Default the detail panels to whichever node is currently in most trouble --
  // an operator opening the dashboard should land on the problem, not on node 1.
  const riskiest = useMemo(() => {
    if (!snap) return null;
    const live = snap.nodes.filter((n) => n.online);
    return live.reduce<null | typeof live[number]>(
      (best, n) => (best === null || n.riskScore > best.riskScore ? n : best), null);
  }, [snap]);

  const selectedAddr = selected ?? riskiest?.addr ?? snap?.nodes[0]?.addr ?? 0;
  const selectedNode = snap?.nodes.find((n) => n.addr === selectedAddr);

  useEffect(() => {
    if (snap) setHistory([...source.history(selectedAddr)]);
  }, [snap, selectedAddr, source]);

  if (!snap) {
    return (
      <div className="grid h-full place-items-center text-sm text-ink-3">
        Initialising sensor field…
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <TopBar alertCount={snap.alerts.length} online />

      <div className="flex min-h-0 flex-1">
        <Sidebar
          active={nav}
          onSelect={setNav}
          alertCount={snap.alerts.length}
          clock={clock}
          gatewayVolts={snap.gatewayVolts}
          gatewayBatteryPct={snap.gatewayBatteryPct}
        />

        <main className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
          <KpiRow kpis={snap.kpis} />

          <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-[minmax(0,2.05fr)_minmax(0,1fr)]">
            {/* ------------------------------------------------ left column */}
            <div className="flex min-h-0 flex-col gap-3">
              <Card
                title="Live Subsidence Map"
                subtitle={`Jharia Panel L-7 · face at ${snap.faceX.toFixed(0)} m`}
                className="min-h-[340px] flex-1"
                delay={0.05}
              >
                <MapPanel
                  nodes={snap.nodes}
                  links={snap.links}
                  day={snap.day}
                  selectedAddr={selectedAddr}
                  onSelect={setSelected}
                  onToggleNode={(addr) => source.toggleNode(addr)}
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
                  subtitle={selectedNode ? `Node ${selectedNode.id} · ${selectedNode.zone}` : ''}
                  delay={0.16}
                >
                  <DeformationTrend history={history} range={range} onRange={setRange} />
                </Card>
              </div>
            </div>

            {/* ----------------------------------------------- right column */}
            <div className="flex min-h-0 flex-col gap-3">
              <Card
                title="Latest Alerts"
                action={<ViewAllButton />}
                className="min-h-[180px] flex-1"
                delay={0.08}
              >
                <AlertsPanel alerts={snap.alerts} />
              </Card>

              <Card
                className="shrink-0" title="Real-Time Parameters"
                delay={0.14}
                action={
                  <select
                    value={selectedAddr}
                    onChange={(e) => setSelected(Number(e.target.value))}
                    className="focus-ring rounded-md border border-hairline bg-surface-2 px-2 py-1 text-[11px] text-ink"
                    aria-label="Select node"
                  >
                    {snap.nodes.map((n) => (
                      <option key={n.addr} value={n.addr}>
                        Node {n.id}{n.online ? '' : ' (offline)'}
                      </option>
                    ))}
                  </select>
                }
              >
                <ParamsPanel node={selectedNode} />
              </Card>

              <Card className="shrink-0" title="System Health" delay={0.2}>
                <SystemHealth kpis={snap.kpis} gatewayOnline storagePct={snap.storagePct} />
              </Card>

              <Card className="shrink-0" title="Data Flow" delay={0.24}>
                <DataFlow />
              </Card>
            </div>
          </div>
        </main>
      </div>

      <Footer />
    </div>
  );
}
