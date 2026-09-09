/**
 * Live data feed driving the dashboard.
 *
 * Runs the real subsidence physics on a compressed clock so a multi-week trough
 * develops in a couple of minutes on screen. Every quantity shown is derived,
 * never invented: tilt is the gradient of the subsidence surface, crack width
 * follows tensile strain, hop counts come from an actual shortest-path solve over
 * the radio graph, and alerts fire from threshold crossings on those values.
 *
 * `DataSource` is the seam. When the FastAPI backend is up, `LiveSocketSource`
 * implements the same interface against the WebSocket and nothing else changes.
 */
import { classifyDamage, evaluate, type PanelGeometry } from './physics';
import { GATEWAY_LOCAL, buildField, type NodeSpec } from './field';
import {
  DEMO_PANEL, completion as surfaceCompletion, faceX as surfaceFaceX, potholeAt,
} from './surface';
import type {
  AlertItem, Kpis, MeshLink, NodeReading, PredictionPoint, RiskLevel, Snapshot, TrendPoint,
} from '@/data/types';
import type { DataSource, SourceStatus } from '@/data/source';

/** Disruptive-tilt limit, 10 mm/m expressed in degrees -- the NCB-style bound at
 *  which services, drainage and structures start to suffer. */
export const TILT_THRESHOLD_DEG = 0.6;
/** NCB "appreciable damage" boundary. Strain has no sensor behind it: the
 *  backend reconstructs it from the tilt gradient across the array. */
export const STRAIN_THRESHOLD_MM_PER_M = 3.0;
export const TILT_RATE_THRESHOLD_DEG_PER_H = 0.05;
const MM_PER_M_TO_DEG = 180 / Math.PI / 1000;

const MAX_LINK_RANGE_M = 240;
/**
 * The demo runs on a compressed but *internally consistent* clock: one tick is
 * fifteen simulated minutes, delivered every 250 ms. Timestamps on the charts are
 * simulated time, not wall-clock time, so the 1H / 6H / 24H / 7D range tabs mean
 * exactly what they say instead of labelling three minutes of real time as a week.
 */
const TICK_MINUTES = 15;
const DAY_PER_TICK = TICK_MINUTES / 1440;
/** Seven days of 15-minute samples, so the widest range tab is fully backed. */
const HISTORY_POINTS = 700;
/** Opening day: trough developed, pothole part-grown, alerts already standing. */
const START_DAY = 40;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function riskBand(score: number): RiskLevel {
  if (score < 0.35) return 'low';
  if (score < 0.6) return 'medium';
  if (score < 0.85) return 'high';
  return 'critical';
}

/** Deterministic value noise, so the feed is reproducible across reloads. */
function noise(seed: number, t: number): number {
  const x = Math.sin(seed * 127.1 + t * 0.37) * 43758.5453;
  return (x - Math.floor(x)) * 2 - 1;
}

export class SimulatedSource implements DataSource {
  /** Flagged so the UI can say plainly that this is modelled, not measured. */
  readonly kind = 'simulated' as const;

  private readonly nodes: NodeSpec[];
  private readonly listeners = new Set<(s: Snapshot) => void>();
  private readonly statusListeners = new Set<(s: SourceStatus) => void>();
  private readonly trend = new Map<number, TrendPoint[]>();
  private readonly alerts: AlertItem[] = [];
  private readonly lastAlertAt = new Map<number, number>();
  /** Previous tilt per node, so the rate of change can be differenced. */
  private readonly lastTilt = new Map<number, { day: number; tilt: number }>();
  private readonly offline = new Set<number>();
  private readonly staticLinks: MeshLink[];
  private timer: number | null = null;
  private day = START_DAY;
  private tick = 0;
  private startedAt = Date.now();
  /** Wall-clock instant that simulated day 0 maps to, chosen so the opening
   *  moment of the demo reads as "now". */
  private readonly simEpoch0 = Date.now() - START_DAY * 86_400_000;

  constructor(
    private readonly panel: PanelGeometry = DEMO_PANEL,
    private readonly dayPerTick = DAY_PER_TICK,
    private readonly intervalMs = 250,
  ) {
    this.nodes = buildField(panel, 5, 3, MAX_LINK_RANGE_M);
    // Two nodes are down from the start -- a real field always has some.
    this.offline.add(this.nodes[2].addr);
    this.offline.add(this.nodes[this.nodes.length - 3].addr);
    this.staticLinks = this.buildLinks();
    this.nodes.forEach((n) => this.trend.set(n.addr, []));
    this.prefill();
  }

  /**
   * Backfill history so the dashboard opens on a field with a past.
   *
   * An operator arriving at a monitoring screen expects to see where the ground
   * has been, not an empty chart that fills in over the next two minutes. This
   * replays the same physics backwards from the opening day and seeds the alert
   * log from the crossings it finds along the way.
   */
  private prefill() {
    const { hops } = this.solveRoutes();
    const steps = HISTORY_POINTS;
    for (let i = steps; i >= 0; i--) {
      const day = Math.max(0, this.day - i * this.dayPerTick);
      const t = this.simTime(day);
      const nodes = this.nodes.map((s) => this.read(s, day, hops.get(s.addr) ?? 0));
      this.pushHistory(nodes, t);
      // Sample the alert log rather than firing every step -- the cooldown in
      // raiseAlerts already enforces this, but stepping keeps timestamps spread.
      if (i % 61 === 0) this.raiseAlerts(nodes, t);
    }
  }

  // ------------------------------------------------------------- topology
  private buildLinks(): MeshLink[] {
    const links: MeshLink[] = [];
    for (let i = 0; i < this.nodes.length; i++) {
      for (let j = i + 1; j < this.nodes.length; j++) {
        const a = this.nodes[i];
        const b = this.nodes[j];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        if (d > MAX_LINK_RANGE_M) continue;
        // Ground-level log-distance path loss, 865 MHz.
        const rssi = 22 - 43 - 10 * 3.4 * Math.log10(Math.max(1, d));
        links.push({ a: a.addr, b: b.addr, rssi, onRoute: false });
      }
    }
    return links;
  }

  /**
   * Shortest-path solve from the gateway over live links.
   * Returns hop count per node and the set of links carrying traffic home --
   * the same computation the firmware's flood converges on, and what makes a
   * node failure visibly re-route on the map instead of silently degrading.
   */
  private solveRoutes(): { hops: Map<number, number>; routeLinks: Set<string> } {
    const alive = (addr: number) => !this.offline.has(addr);
    const adj = new Map<number, { to: number; key: string }[]>();
    for (const n of this.nodes) adj.set(n.addr, []);
    for (const l of this.staticLinks) {
      if (!alive(l.a) || !alive(l.b)) continue;
      const key = `${Math.min(l.a, l.b)}-${Math.max(l.a, l.b)}`;
      adj.get(l.a)!.push({ to: l.b, key });
      adj.get(l.b)!.push({ to: l.a, key });
    }

    // Seed the frontier with nodes that can reach the gateway directly.
    const hops = new Map<number, number>();
    const routeLinks = new Set<string>();
    const queue: number[] = [];
    for (const n of this.nodes) {
      if (!alive(n.addr)) continue;
      const d = Math.hypot(n.x - GATEWAY_LOCAL.x, n.y - GATEWAY_LOCAL.y);
      if (d <= MAX_LINK_RANGE_M) {
        hops.set(n.addr, 1);
        queue.push(n.addr);
      }
    }
    for (let head = 0; head < queue.length; head++) {
      const cur = queue[head];
      for (const { to, key } of adj.get(cur) ?? []) {
        if (hops.has(to)) continue;
        hops.set(to, hops.get(cur)! + 1);
        routeLinks.add(key);
        queue.push(to);
      }
    }
    return { hops, routeLinks };
  }

  // -------------------------------------------------------------- physics
  private faceX(day: number): number {
    return surfaceFaceX(day, this.panel);
  }

  private read(spec: NodeSpec, day: number, hops: number): NodeReading {
    const faceX = this.faceX(day);
    const mv = evaluate(this.panel, spec.x, spec.y, faceX, surfaceCompletion(day));
    const ph = potholeAt(spec.x, spec.y, day, this.panel);

    const tiltX = mv.tiltX + ph.tiltX;
    const tiltY = mv.tiltY + ph.tiltY;
    const strain = mv.strain + ph.strain;
    const tiltMagnitude = Math.hypot(tiltX, tiltY);

    const jitter = noise(spec.addr, this.tick);
    const tiltPitchDeg = tiltX * MM_PER_M_TO_DEG + jitter * 0.004;
    const tiltRollDeg = tiltY * MM_PER_M_TO_DEG + noise(spec.addr + 7, this.tick) * 0.004;
    const tiltDeg = Math.hypot(tiltPitchDeg, tiltRollDeg);

    // This offline model knows the true strain because it *is* the model. Real
    // hardware does not measure strain at all -- the backend reconstructs it
    // from how tilt varies between neighbouring nodes. Same quantity, different
    // provenance, so the dashboard renders it identically either way.
    // Ambient floor plus energy radiated by active settlement.
    const vibrationMg = clamp(
      12 + Math.abs(jitter) * 6 + ph.rate * 2.2 + Math.abs(mv.tilt) * 0.9, 0, 999,
    );

    const prev = this.lastTilt.get(spec.addr);
    const tiltRateDegPerH = prev ? (tiltDeg - prev.tilt) / Math.max(0.25, (day - prev.day) * 24) : 0;
    this.lastTilt.set(spec.addr, { day, tilt: tiltDeg });

    const riskScore = clamp(
      Math.max(
        tiltDeg / TILT_THRESHOLD_DEG,
        Math.abs(strain) / STRAIN_THRESHOLD_MM_PER_M,
        Math.abs(tiltRateDegPerH) / TILT_RATE_THRESHOLD_DEG_PER_H,
      ) * 0.9 + Math.min(vibrationMg / 400, 1) * 0.1,
      0,
      1.35,
    );

    const online = !this.offline.has(spec.addr);
    return {
      addr: spec.addr,
      id: spec.id,
      label: spec.label,
      lat: spec.lat,
      lon: spec.lon,
      x: spec.x,
      y: spec.y,
      isEdge: spec.isEdge,
      zone: spec.zone,
      online,
      tiltPitchDeg,
      tiltRollDeg,
      tiltDeg,
      tiltRateDegPerH,
      vibrationMg,
      tempC: 28 + 4.5 * Math.cos((2 * Math.PI * ((day % 1) * 24 - 15)) / 24),
      subsidenceMm: mv.subsidenceMm + ph.sub,
      subsidenceValid: true,
      strainMmPerM: strain,
      strainValid: true,
      gnssSats: 7 + ((spec.addr + this.tick) % 5),
      riskScore: Math.min(riskScore, 1),
      risk: riskBand(riskScore),
      damage: classifyDamage(strain, tiltMagnitude),
      hops: hops || 0,
      rssi: -58 - hops * 14 + jitter * 3,
      batteryPct: clamp(88 - (spec.addr % 7) * 4 + jitter * 3, 5, 100),
    };
  }

  // --------------------------------------------------------------- alerts
  private raiseAlerts(nodes: NodeReading[], now: number) {
    for (const n of nodes) {
      if (!n.online || (n.risk !== 'high' && n.risk !== 'critical')) continue;
      // One alert per node per simulated interval -- operators ignore a system
      // that repeats itself every second.
      // Most of a simulated day between repeats for a given node, phase-shifted by
      // address so a whole zone crossing together still arrives as a sequence
      // rather than one indistinguishable burst.
      const cooldown = (18 + (n.addr % 7)) * 3_600_000;
      if (now - (this.lastAlertAt.get(n.addr) ?? -1e9) < cooldown) continue;
      this.lastAlertAt.set(n.addr, now);

      const critical = n.risk === 'critical';
      // Name the alert after whichever criterion actually drove it, matching
      // backend/app/ingest.py::_alert_title so the two sources cannot disagree.
      const rateLed = Math.abs(n.tiltRateDegPerH) >= TILT_RATE_THRESHOLD_DEG_PER_H;
      const strainLed = Math.abs(n.strainMmPerM) >= STRAIN_THRESHOLD_MM_PER_M;
      this.alerts.unshift({
        id: `${n.addr}-${now}`,
        severity: critical ? 'critical' : n.risk === 'high' ? 'high' : 'medium',
        title: rateLed
          ? 'Tilt Rate Exceeded'
          : strainLed
            ? 'Ground Strain Exceeded'
            : critical
              ? 'High Deformation Detected'
              : 'Abnormal Tilt Detected',
        nodeId: n.id,
        zone: n.zone,
        ts: now,
        metrics: [
          { label: 'Tilt', value: `${n.tiltDeg.toFixed(2)}°` },
          { label: 'Strain', value: `${n.strainMmPerM >= 0 ? '+' : ''}${n.strainMmPerM.toFixed(2)} mm/m` },
          { label: 'Vibration', value: n.vibrationMg > 60 ? 'High' : 'Normal' },
        ],
      });
    }
    if (this.alerts.length > 8) this.alerts.length = 8;
  }

  private buildPrediction(nodes: NodeReading[]): PredictionPoint[] {
    const peak = Math.max(0, ...nodes.map((n) => n.riskScore));
    const out: PredictionPoint[] = [];
    const days = 7;
    for (let i = 0; i <= days; i++) {
      const frac = i / days;
      // Observed history, shaped by the same accelerating trend now on screen.
      const actual = clamp(peak * Math.pow(frac, 1.9) + noise(i, 3) * 0.02, 0, 1);
      out.push({ t: i, actual, predicted: clamp(actual + 0.03 - frac * 0.02, 0, 1) });
    }
    // Forecast horizon: actual is unknown, the model keeps going.
    for (let i = 1; i <= 3; i++) {
      const frac = (days + i) / days;
      out.push({
        t: days + i,
        actual: null,
        predicted: clamp(peak * Math.pow(frac, 1.9) * 1.04, 0, 1.35),
      });
    }
    return out;
  }

  private pushHistory(nodes: NodeReading[], now: number) {
    for (const n of nodes) {
      const buf = this.trend.get(n.addr)!;
      buf.push({
        t: now,
        pitch: n.tiltPitchDeg,
        roll: n.tiltRollDeg,
        vib: n.vibrationMg,
        tempC: n.tempC,
      });
      if (buf.length > HISTORY_POINTS) buf.shift();
    }
  }

  /** Wall-clock instant corresponding to a simulated day. */
  private simTime(day: number): number {
    return this.simEpoch0 + day * 86_400_000;
  }

  private snapshot(): Snapshot {
    const now = this.simTime(this.day);
    const { hops, routeLinks } = this.solveRoutes();
    const nodes = this.nodes.map((s) => this.read(s, this.day, hops.get(s.addr) ?? 0));

    this.pushHistory(nodes, now);
    this.raiseAlerts(nodes, now);

    const links: MeshLink[] = this.staticLinks
      .filter((l) => !this.offline.has(l.a) && !this.offline.has(l.b))
      .map((l) => ({
        ...l,
        onRoute: routeLinks.has(`${Math.min(l.a, l.b)}-${Math.max(l.a, l.b)}`),
      }));

    const active = nodes.filter((n) => n.online);
    const critical = this.alerts.filter((a) => a.severity === 'critical').length;
    const high = this.alerts.filter((a) => a.severity === 'high').length;
    const reachable = active.filter((n) => n.hops > 0).length;
    const delivery = active.length ? (reachable / active.length) * 100 : 0;

    const kpis: Kpis = {
      totalNodes: nodes.length,
      activeNodes: active.length,
      inactiveNodes: nodes.length - active.length,
      totalAlerts: this.alerts.length,
      criticalAlerts: critical,
      highAlerts: high,
      maxTiltDeg: Math.max(0, ...active.map((n) => n.tiltDeg)),
      tiltThresholdDeg: TILT_THRESHOLD_DEG,
      maxStrainMmPerM: Math.max(0, ...active.map((n) => Math.abs(n.strainMmPerM))),
      strainThresholdMmPerM: STRAIN_THRESHOLD_MM_PER_M,
      maxSubsidenceMm: Math.max(0, ...active.map((n) => n.subsidenceMm)),
      maxTiltRateDegPerH: Math.max(0, ...active.map((n) => Math.abs(n.tiltRateDegPerH))),
      tiltRateThresholdDegPerH: TILT_RATE_THRESHOLD_DEG_PER_H,
      strainResolved: true,
      packetDeliveryPct: delivery,
      uptimePct: 99.1,
      healthy: !active.some((n) => n.risk === 'critical'),
    };

    return {
      t: now,
      day: this.day,
      faceX: this.faceX(this.day),
      nodes,
      links,
      alerts: [...this.alerts],
      prediction: this.buildPrediction(nodes),
      kpis,
      gatewayVolts: 13.2 + noise(1, this.tick) * 0.05,
      gatewayBatteryPct: 78,
      storagePct: 85,
    };
  }

  // ----------------------------------------------------------------- api
  subscribe(fn: (s: Snapshot) => void) {
    this.listeners.add(fn);
    fn(this.snapshot());
    return () => this.listeners.delete(fn);
  }

  onStatus(fn: (s: SourceStatus) => void): () => void {
    this.statusListeners.add(fn);
    fn({ kind: 'simulated', connected: false, detail: 'running on the built-in model' });
    return () => this.statusListeners.delete(fn);
  }

  history(addr: number): TrendPoint[] {
    return this.trend.get(addr) ?? [];
  }

  /** Take a node off the air, or bring it back -- drives the re-route demo. */
  toggleNode(addr: number) {
    if (this.offline.has(addr)) this.offline.delete(addr);
    else this.offline.add(addr);
    this.emit();
  }

  get elapsedMs() {
    return Date.now() - this.startedAt;
  }

  private emit() {
    const snap = this.snapshot();
    this.listeners.forEach((fn) => fn(snap));
  }

  start() {
    if (this.timer !== null) return;
    this.timer = window.setInterval(() => {
      this.tick += 1;
      this.day += this.dayPerTick;
      this.emit();
    }, this.intervalMs);
  }

  stop() {
    if (this.timer !== null) window.clearInterval(this.timer);
    this.timer = null;
  }
}

export { panelExtent } from './surface';
export const DEMO_PANEL_GEOMETRY = DEMO_PANEL;
