import { Card } from '@/components/ui/Card';
import { DataFlow } from '@/components/health/DataFlow';
import { IconBattery, IconCpu, IconDatabase, IconGateway, IconHeart, IconWifi } from '@/components/ui/icons';
import type { Snapshot } from '@/data/types';

interface Props {
  snap: Snapshot;
}

export function HealthView({ snap }: Props) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3 pb-12">
      {/* Infrastructure Stat Cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-hairline bg-surface-2/60 p-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-ink-3">Gateway Battery</span>
            <span className="text-good"><IconBattery size={18} /></span>
          </div>
          <div className="mt-1 font-mono text-base font-bold text-ink">
            {snap.gatewayVolts.toFixed(1)} V
            <span className="ml-1 text-xs font-normal text-ink-3">({snap.gatewayBatteryPct}%)</span>
          </div>
          <div className="text-[10px] text-ink-3">LiFePO4 Solar Buffer Nominal</div>
        </div>

        <div className="rounded-xl border border-hairline bg-surface-2/60 p-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-ink-3">LoRa Packet Delivery</span>
            <span className="text-good"><IconWifi size={18} /></span>
          </div>
          <div className="mt-1 font-mono text-base font-bold text-good">
            {snap.kpis.packetDeliveryPct.toFixed(1)}%
          </div>
          <div className="text-[10px] text-ink-3">Zero dropped wire frames</div>
        </div>

        <div className="rounded-xl border border-hairline bg-surface-2/60 p-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-ink-3">System Uptime</span>
            <span className="text-brand"><IconHeart size={18} /></span>
          </div>
          <div className="mt-1 font-mono text-base font-bold text-ink">
            {snap.kpis.uptimePct.toFixed(1)}%
          </div>
          <div className="text-[10px] text-ink-3">Service health verified</div>
        </div>

        <div className="rounded-xl border border-hairline bg-surface-2/60 p-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-ink-3">Local Storage Buffer</span>
            <span className="text-cyan-400"><IconDatabase size={18} /></span>
          </div>
          <div className="mt-1 font-mono text-base font-bold text-ink">
            {snap.storagePct}% Used
          </div>
          <div className="text-[10px] text-ink-3">MicroSD store-and-forward</div>
        </div>
      </div>

      {/* Main Container */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3">
          {/* Hardware Subsystem Status */}
          <Card
            title="Subsystem Hardware Diagnostic Health"
            subtitle="Field concentrator & sensor node hardware state"
          >
            <div className="flex flex-col gap-3 p-4 text-xs">
              <div className="flex items-center justify-between rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="flex items-center gap-3">
                  <span className="grid h-9 w-9 place-items-center rounded-lg bg-surface-3 text-brand">
                    <IconGateway size={18} />
                  </span>
                  <div>
                    <div className="font-semibold text-ink">ESP32-S3 Gateway Concentrator</div>
                    <div className="text-[10px] text-ink-3">E220 LoRa SPI + SIM800L Cellular Modem</div>
                  </div>
                </div>
                <span className="rounded bg-good/15 px-2 py-0.5 text-[10px] font-bold text-good uppercase">
                  Online
                </span>
              </div>

              <div className="flex items-center justify-between rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="flex items-center gap-3">
                  <span className="grid h-9 w-9 place-items-center rounded-lg bg-surface-3 text-sky-400">
                    <IconCpu size={18} />
                  </span>
                  <div>
                    <div className="font-semibold text-ink">LoRa 865 MHz Mesh Radio</div>
                    <div className="text-[10px] text-ink-3">Time-Synchronized Channel Discipline · 12 Hops Max</div>
                  </div>
                </div>
                <span className="rounded bg-good/15 px-2 py-0.5 text-[10px] font-bold text-good uppercase">
                  Connected
                </span>
              </div>

              <div className="flex items-center justify-between rounded-lg border border-hairline bg-surface-2/60 p-3">
                <div className="flex items-center gap-3">
                  <span className="grid h-9 w-9 place-items-center rounded-lg bg-surface-3 text-purple-400">
                    <IconWifi size={18} />
                  </span>
                  <div>
                    <div className="font-semibold text-ink">FastAPI Telemetry Ingress Service</div>
                    <div className="text-[10px] text-ink-3">WebSocket & REST Coalesced at 1 Hz</div>
                  </div>
                </div>
                <span className="rounded bg-good/15 px-2 py-0.5 text-[10px] font-bold text-good uppercase">
                  Streaming
                </span>
              </div>
            </div>
          </Card>

          {/* End to End Pipeline */}
          <Card
            title="End-to-End Data Pipeline Flow"
            subtitle="Real-time frame transport from LIS3DH sensor to browser dashboard"
          >
            <div className="p-4">
              <DataFlow />
            </div>
          </Card>
        </div>

        {/* Right Column: Node Battery & Radio List */}
        <div className="flex flex-col gap-3">
          <Card
            title="Mesh Node Battery & Link Status"
            subtitle={`${snap.nodes.length} field units reporting battery & RSSI`}
          >
            <div className="flex max-h-[380px] flex-col gap-2 overflow-y-auto p-3 text-xs">
              {snap.nodes.map((n) => (
                <div
                  key={n.addr}
                  className="flex items-center justify-between rounded-lg border border-hairline bg-surface-2/60 p-2.5"
                >
                  <div className="flex items-center gap-2.5">
                    <span className="grid h-7 w-7 place-items-center rounded bg-surface-3 font-mono text-xs font-bold text-ink">
                      {n.id}
                    </span>
                    <div>
                      <div className="font-semibold text-ink">{n.label}</div>
                      <div className="text-[10px] text-ink-3">{n.gnssSats} Satellites Fix · RSSI: {n.rssi} dBm</div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 text-right">
                    <div className="w-16">
                      <div className="text-[10px] font-semibold text-ink">{n.batteryPct}%</div>
                      <div className="h-1.5 w-full rounded-full bg-surface-3">
                        <div
                          className={`h-full rounded-full ${n.batteryPct > 50 ? 'bg-good' : n.batteryPct > 20 ? 'bg-warning' : 'bg-critical'}`}
                          style={{ width: `${n.batteryPct}%` }}
                        />
                      </div>
                    </div>
                    <span className={`inline-block h-2 w-2 rounded-full ${n.online ? 'bg-good' : 'bg-critical'}`} />
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
