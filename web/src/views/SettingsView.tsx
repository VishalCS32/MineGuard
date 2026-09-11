import { useState } from 'react';
import { Card } from '@/components/ui/Card';
import { IconCheck, IconCloud, IconGear, IconWarning } from '@/components/ui/icons';
import { api, apiClient } from '@/api';

interface Props {
  nodeId?: string;
}

export function SettingsView({ nodeId = 'NODE-001' }: Props) {
  const [apiBase, setApiBase] = useState(apiClient.baseUrl);
  const [wsBase, setWsBase] = useState(apiClient.wsUrl);
  const [targetNode, setTargetNode] = useState(nodeId);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Anomaly test states
  const [injectTicks, setInjectTicks] = useState(6);
  const [injecting, setInjecting] = useState(false);
  const [injectResult, setInjectResult] = useState<string | null>(null);

  // Health check state
  const [checkingHealth, setCheckingHealth] = useState(false);
  const [healthResult, setHealthResult] = useState<string | null>(null);

  const handleSaveConfig = () => {
    apiClient.updateConfig({
      baseUrl: apiBase,
      wsUrl: wsBase,
      defaultNodeId: targetNode,
    });
    localStorage.setItem('mineguard_api_base', apiBase);
    localStorage.setItem('mineguard_ws_base', wsBase);
    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 2500);
  };

  const handleInjectAnomaly = async () => {
    setInjecting(true);
    setInjectResult(null);
    try {
      const res = await api.injectAnomaly(targetNode, injectTicks);
      setInjectResult(`Anomaly episode successfully queued for ${res.node_id} (${res.anomaly_ticks} ticks)`);
    } catch (err) {
      setInjectResult(`Backend response: Anomaly injection endpoint not supported on remote host (Simulator feature)`);
    } finally {
      setInjecting(false);
    }
  };

  const handleTestConnection = async () => {
    setCheckingHealth(true);
    setHealthResult(null);
    try {
      const res = await api.getHealth();
      setHealthResult(`Connected successfully: Status '${res.status}' · ${res.service || 'Node Live Telemetry API'}`);
    } catch (err) {
      setHealthResult(`Connection error: Failed to reach ${apiBase}`);
    } finally {
      setCheckingHealth(false);
    }
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3 pb-12">
      {/* Top Header Card */}
      <div className="flex items-center gap-3 rounded-xl border border-hairline bg-surface-2/70 p-4">
        <span className="grid h-10 w-10 place-items-center rounded-lg bg-brand/15 text-brand">
          <IconGear size={22} />
        </span>
        <div>
          <div className="text-sm font-bold text-ink">System Configuration & Integration Endpoints</div>
          <div className="text-xs text-ink-3">
            Manage Node 1 backend API contracts, WebSocket telemetry channels, and safety limits
          </div>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-2">
        {/* Backend API Endpoints Card */}
        <Card
          title="Backend Connection & Telemetry URLs"
          subtitle="Configured endpoints for REST polling & WebSocket streaming"
        >
          <div className="flex flex-col gap-3 p-4 text-xs">
            <div>
              <label className="mb-1 block font-semibold text-ink-2">REST API Base URL</label>
              <input
                type="text"
                value={apiBase}
                onChange={(e) => setApiBase(e.target.value)}
                placeholder="https://mineguard-api.tenant.eu.org"
                className="w-full rounded-lg border border-hairline bg-surface-2 p-2 font-mono text-xs text-ink focus:border-brand focus:outline-none"
              />
              <div className="mt-1 text-[10px] text-ink-3">
                Remote: <span className="font-mono text-ink-2">https://mineguard-api.tenant.eu.org</span> · Local: <span className="font-mono text-ink-2">http://localhost:8000</span>
              </div>
            </div>

            <div>
              <label className="mb-1 block font-semibold text-ink-2">WebSocket Base URL</label>
              <input
                type="text"
                value={wsBase}
                onChange={(e) => setWsBase(e.target.value)}
                placeholder="wss://mineguard-api.tenant.eu.org"
                className="w-full rounded-lg border border-hairline bg-surface-2 p-2 font-mono text-xs text-ink focus:border-brand focus:outline-none"
              />
              <div className="mt-1 text-[10px] text-ink-3">
                Live streaming stream target: <span className="font-mono text-ink-2">/ws/NODE-001</span> or <span className="font-mono text-ink-2">/ws/live</span>
              </div>
            </div>

            <div>
              <label className="mb-1 block font-semibold text-ink-2">Primary Monitored Node ID</label>
              <input
                type="text"
                value={targetNode}
                onChange={(e) => setTargetNode(e.target.value)}
                placeholder="NODE-001"
                className="w-full rounded-lg border border-hairline bg-surface-2 p-2 font-mono text-xs text-ink focus:border-brand focus:outline-none"
              />
            </div>

            <div className="mt-2 flex items-center justify-between border-t border-hairline/80 pt-3">
              <button
                type="button"
                onClick={handleTestConnection}
                disabled={checkingHealth}
                className="focus-ring flex items-center gap-1.5 rounded-lg bg-surface-3 px-3 py-1.5 font-semibold text-ink transition-colors hover:bg-surface-2 hover:text-brand disabled:opacity-50"
              >
                <IconCloud size={15} /> {checkingHealth ? 'Testing…' : 'Test API Health'}
              </button>

              <button
                type="button"
                onClick={handleSaveConfig}
                className="focus-ring flex items-center gap-1.5 rounded-lg bg-brand px-4 py-1.5 font-bold text-white shadow-glow transition-colors hover:bg-brand/80"
              >
                <IconCheck size={15} /> Save & Apply
              </button>
            </div>

            {saveSuccess && (
              <div className="flex items-center gap-2 rounded bg-good/15 p-2 text-[11px] font-semibold text-good">
                <IconCheck size={14} /> Configuration saved and active.
              </div>
            )}

            {healthResult && (
              <div className="rounded bg-surface-2 p-2 font-mono text-[11px] text-ink">
                {healthResult}
              </div>
            )}
          </div>
        </Card>

        {/* Right Column: Anomaly Injection & DGMS Thresholds */}
        <div className="flex flex-col gap-3">
          {/* Anomaly Testing */}
          <Card
            title="Simulator Anomaly Injection Test"
            subtitle="Trigger a controlled deformation anomaly episode for testing"
          >
            <div className="flex flex-col gap-3 p-4 text-xs">
              <p className="text-[11px] text-ink-3">
                Sends a request to <span className="font-mono text-ink-2">POST /api/nodes/{targetNode}/inject-anomaly</span>.
                Forces a temporary elevation in pitch, roll, and vibration RMS to verify early warning response.
              </p>

              <div className="flex items-center gap-3">
                <label className="text-ink-2">Duration (ticks):</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={injectTicks}
                  onChange={(e) => setInjectTicks(Number(e.target.value))}
                  className="w-20 rounded border border-hairline bg-surface-2 p-1.5 font-mono text-ink"
                />
                <button
                  type="button"
                  onClick={handleInjectAnomaly}
                  disabled={injecting}
                  className="focus-ring flex items-center gap-1.5 rounded-lg bg-warning/20 px-3 py-1.5 font-bold text-warning hover:bg-warning/30 disabled:opacity-50"
                >
                  <IconWarning size={15} /> {injecting ? 'Injecting…' : 'Trigger Anomaly'}
                </button>
              </div>

              {injectResult && (
                <div className="rounded border border-hairline bg-surface-2 p-2 font-mono text-[11px] text-ink-2">
                  {injectResult}
                </div>
              )}
            </div>
          </Card>

          {/* Safety Threshold Limits */}
          <Card
            title="DGMS Safety Limits Reference"
            subtitle="Regulatory bounds governing automated alerting logic"
          >
            <div className="grid grid-cols-2 gap-2.5 p-4 text-xs">
              <div className="rounded-lg border border-hairline bg-surface-2/60 p-2.5">
                <div className="text-[10px] text-ink-3">Max Allowable Tilt</div>
                <div className="font-mono text-sm font-bold text-ink">0.60° (10 mm/m)</div>
                <div className="text-[10px] text-ink-3">Disruptive structural bound</div>
              </div>

              <div className="rounded-lg border border-hairline bg-surface-2/60 p-2.5">
                <div className="text-[10px] text-ink-3">Tensile Strain Bound</div>
                <div className="font-mono text-sm font-bold text-ink">3.00 mm/m</div>
                <div className="text-[10px] text-ink-3">NCB Appreciable Damage</div>
              </div>

              <div className="rounded-lg border border-hairline bg-surface-2/60 p-2.5">
                <div className="text-[10px] text-ink-3">Vibration RMS Bound</div>
                <div className="font-mono text-sm font-bold text-ink">200 mg (0.20g)</div>
                <div className="text-[10px] text-ink-3">Seismic blasting limit</div>
              </div>

              <div className="rounded-lg border border-hairline bg-surface-2/60 p-2.5">
                <div className="text-[10px] text-ink-3">Tilt Rate Acceleration</div>
                <div className="font-mono text-sm font-bold text-ink">0.05° / hour</div>
                <div className="text-[10px] text-ink-3">Rapid roof acceleration</div>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
