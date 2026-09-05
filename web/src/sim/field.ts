/**
 * Node field layout -- browser port of `ml/simulator/field.py`.
 *
 * Deliberately not a uniform grid. Tilt and strain peak directly above the panel
 * edge, so the outer rows sit in the draw-angle margin, the next ones sit exactly
 * on the panel boundary, and gaps wider than the radio can bridge are subdivided.
 * Sensing coverage and radio connectivity are separate constraints, and a layout
 * that satisfies only the first measures the ground perfectly while failing to
 * deliver a single frame home.
 */
import { DEFAULT_PANEL, radiusOfInfluence, type PanelGeometry } from './physics';

const EARTH_RADIUS_M = 6378137;

export interface NodeSpec {
  addr: number;
  id: string;
  label: string;
  x: number;
  y: number;
  lat: number;
  lon: number;
  isEdge: boolean;
  zone: string;
}

/** Jharia Coalfield, Jharkhand -- anchors the demo in real geography. */
export const SITE_ORIGIN = { lat: 23.75, lon: 86.42, name: 'Jharia Panel L-7' };

export function localToWgs84(x: number, y: number) {
  return {
    lat: SITE_ORIGIN.lat + (y / EARTH_RADIUS_M) * (180 / Math.PI),
    lon:
      SITE_ORIGIN.lon +
      (x / (EARTH_RADIUS_M * Math.cos((SITE_ORIGIN.lat * Math.PI) / 180))) * (180 / Math.PI),
  };
}

function edgeAnchored(lo: number, hi: number, margin: number, n: number): number[] {
  if (n <= 2) return [lo, hi];
  if (n === 3) return [lo, (lo + hi) / 2, hi];
  const interior = n - 4;
  const out = [lo - margin, lo];
  if (interior > 0) {
    const step = (hi - lo) / (interior + 1);
    for (let i = 0; i < interior; i++) out.push(lo + step * (i + 1));
  }
  out.push(hi, hi + margin);
  return out;
}

function enforceMaxSpacing(positions: number[], maxSpacing: number): number[] {
  const out = [positions[0]];
  for (let i = 0; i < positions.length - 1; i++) {
    const a = positions[i];
    const b = positions[i + 1];
    const gap = b - a;
    const extra = Math.max(0, Math.ceil(gap / maxSpacing) - 1);
    for (let k = 0; k < extra; k++) out.push(a + (gap * (k + 1)) / (extra + 1));
    out.push(b);
  }
  return out;
}

function zoneFor(p: PanelGeometry, x: number, y: number): string {
  const midY = (p.yMin + p.yMax) / 2;
  const band = (p.yMax - p.yMin) / 3;
  if (y < midY - band / 2) return 'Panel A - South';
  if (y > midY + band / 2) return 'Panel A - North';
  const span = p.xEnd - p.xStart;
  if (x < p.xStart + span / 3) return 'Panel A - West';
  if (x > p.xEnd - span / 3) return 'Panel A - East';
  return 'Panel A - Center';
}

export function buildField(
  panel: PanelGeometry = DEFAULT_PANEL,
  cols = 5,
  rows = 3,
  maxSpacingM = 200,
): NodeSpec[] {
  const margin = 0.35 * radiusOfInfluence(panel);
  const xs = enforceMaxSpacing(edgeAnchored(panel.xStart, panel.xEnd, margin, cols), maxSpacingM);
  const ys = enforceMaxSpacing(edgeAnchored(panel.yMin, panel.yMax, margin, rows), maxSpacingM);
  const edgeBand = 0.2 * radiusOfInfluence(panel);

  const nodes: NodeSpec[] = [];
  let addr = 0x10;
  ys.forEach((y, row) => {
    xs.forEach((x, col) => {
      const { lat, lon } = localToWgs84(x, y);
      const nearX = Math.min(Math.abs(x - panel.xStart), Math.abs(x - panel.xEnd)) <= edgeBand;
      const nearY = Math.min(Math.abs(y - panel.yMin), Math.abs(y - panel.yMax)) <= edgeBand;
      nodes.push({
        addr,
        id: String(addr - 0x0f).padStart(2, '0'),
        label: `N${row + 1}-${col + 1}`,
        x,
        y,
        lat,
        lon,
        isEdge: nearX || nearY,
        zone: zoneFor(panel, x, y),
      });
      addr += 1;
    });
  });
  return nodes;
}

/** Gateway sits back from the panel edge, uphill of the field. */
export const GATEWAY_LOCAL = { x: DEFAULT_PANEL.xStart - 0.5 * radiusOfInfluence(DEFAULT_PANEL), y: 0 };
export const GATEWAY_LATLON = localToWgs84(GATEWAY_LOCAL.x, GATEWAY_LOCAL.y);
