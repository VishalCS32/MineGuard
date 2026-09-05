/**
 * The demo's ground surface: panel geometry, face advance, and the pothole that
 * opens over the goaf. Shared by the live feed, the 2-D heat overlay and the 3-D
 * terrain mesh so all three are literally the same ground.
 *
 * The grid sampler exploits a useful property of the model: both terms separate
 * into a product of one-dimensional functions.
 *
 *     S(x, y) = A * Fx(x) * Fy(y)  +  D * Gx(x) * Gy(y)
 *
 * The influence-function profile is a product of the two axis profiles by
 * construction, and the pothole's Gaussian factorises the same way. So a
 * 160 x 120 terrain grid costs 280 profile evaluations instead of 19,200 -- which
 * is what makes re-tessellating the 3-D surface on every frame affordable.
 */
import {
  DEFAULT_PANEL, erfc, radiusOfInfluence, sMax, type PanelGeometry,
} from './physics';

/** Panel is supercritical across the face, so the trough develops fully. */
export const DEMO_PANEL: PanelGeometry = { ...DEFAULT_PANEL, yMin: -200, yMax: 200 };

export const FACE_ADVANCE_M_PER_DAY = 12;

/** A pothole opening over the goaf, well behind the working face. */
export const POTHOLE = {
  startDay: 39,
  // Sudden subsidence over a goaf void develops in hours to a couple of days;
  // this is the conservative end of that, and it is what visibly moves on screen.
  rampDays: 2.5,
  depthMm: 820,
  sigmaM: 92,
  yOffset: 40,
};

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function faceX(day: number, panel: PanelGeometry = DEMO_PANEL): number {
  return Math.min(panel.xStart + FACE_ADVANCE_M_PER_DAY * day, panel.xEnd);
}

/** Knothe time lag: the surface trails the face toward its final shape. */
export function completion(day: number): number {
  return 1 - Math.exp(-0.35 * Math.max(day, 0));
}

/**
 * Pothole centre, anchored inside the goaf. Unmined ground cannot collapse into
 * a void that does not exist yet, so this is always behind the face.
 */
export function potholeCentre(panel: PanelGeometry = DEMO_PANEL) {
  const goafEnd = faceX(POTHOLE.startDay, panel);
  return {
    cx: panel.xStart + 0.45 * (goafEnd - panel.xStart),
    cy: 0.5 * (panel.yMin + panel.yMax) + 0.5 * POTHOLE.sigmaM,
  };
}

export function potholeRamp(day: number): number {
  return clamp((day - POTHOLE.startDay) / POTHOLE.rampDays, 0, 1);
}

/** Local subsidence, tilt and strain contributed by the pothole at one point. */
export function potholeAt(x: number, y: number, day: number, panel: PanelGeometry = DEMO_PANEL) {
  const ramp = potholeRamp(day);
  if (ramp <= 0) return { sub: 0, tiltX: 0, tiltY: 0, strain: 0, rate: 0 };
  const { cx, cy } = potholeCentre(panel);
  const dx = x - cx;
  const dy = y - cy;
  const s2 = POTHOLE.sigmaM ** 2;
  const bump = Math.exp(-(dx * dx + dy * dy) / (2 * s2));
  const depth = POTHOLE.depthMm * ramp;
  const b = 0.4 * panel.seamDepthM;
  return {
    sub: depth * bump,
    tiltX: (-depth * bump * dx) / s2,
    tiltY: (-depth * bump * dy) / s2,
    strain: b * depth * bump * ((dx * dx) / (s2 * s2) - 1 / s2),
    rate: ramp < 1 ? (POTHOLE.depthMm * bump) / (POTHOLE.rampDays * 24) : 0,
  };
}

/** One-dimensional influence profile: fraction of S_max from extraction [a, b]. */
function profile1d(u: number, a: number, b: number, r: number): number {
  const k = Math.sqrt(Math.PI) / r;
  return 0.5 * (erfc(k * (u - b)) - erfc(k * (u - a)));
}

export interface Extent {
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

/**
 * Subsidence in millimetres on an `nx` x `ny` grid over `extent`.
 * Row 0 is the northern edge (yMax), matching canvas and texture orientation.
 */
export function subsidenceGrid(
  day: number, nx: number, ny: number, extent: Extent, panel: PanelGeometry = DEMO_PANEL,
): Float32Array {
  const out = new Float32Array(nx * ny);
  const r = radiusOfInfluence(panel);
  const x2 = clamp(faceX(day, panel), panel.xStart, panel.xEnd);
  const amp = x2 <= panel.xStart ? 0 : sMax(panel) * 1000 * completion(day);

  const ramp = potholeRamp(day);
  const { cx, cy } = potholeCentre(panel);
  const depth = POTHOLE.depthMm * ramp;
  const twoSigmaSq = 2 * POTHOLE.sigmaM ** 2;

  // Separable factors, evaluated once per row and once per column.
  const fx = new Float64Array(nx);
  const gx = new Float64Array(nx);
  for (let i = 0; i < nx; i++) {
    const x = extent.xMin + ((i + 0.5) / nx) * (extent.xMax - extent.xMin);
    fx[i] = amp > 0 ? profile1d(x, panel.xStart, x2, r) : 0;
    gx[i] = depth > 0 ? Math.exp(-((x - cx) ** 2) / twoSigmaSq) : 0;
  }
  const fy = new Float64Array(ny);
  const gy = new Float64Array(ny);
  for (let j = 0; j < ny; j++) {
    const y = extent.yMax - ((j + 0.5) / ny) * (extent.yMax - extent.yMin);
    fy[j] = amp > 0 ? profile1d(y, panel.yMin, panel.yMax, r) : 0;
    gy[j] = depth > 0 ? Math.exp(-((y - cy) ** 2) / twoSigmaSq) : 0;
  }

  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      out[j * nx + i] = amp * fx[i] * fy[j] + depth * gx[i] * gy[j];
    }
  }
  return out;
}

/** Subsidence in millimetres at a single point. */
export function subsidenceAt(
  x: number, y: number, day: number, panel: PanelGeometry = DEMO_PANEL,
): number {
  const r = radiusOfInfluence(panel);
  const x2 = clamp(faceX(day, panel), panel.xStart, panel.xEnd);
  const amp = x2 <= panel.xStart ? 0 : sMax(panel) * 1000 * completion(day);
  const regional = amp > 0
    ? amp * profile1d(x, panel.xStart, x2, r) * profile1d(y, panel.yMin, panel.yMax, r)
    : 0;
  return regional + potholeAt(x, y, day, panel).sub;
}

/** Field extent with a draw-angle margin around the panel. */
export function panelExtent(panel: PanelGeometry = DEMO_PANEL): Extent {
  const margin = 0.5 * radiusOfInfluence(panel);
  return {
    xMin: panel.xStart - margin,
    xMax: panel.xEnd + margin,
    yMin: panel.yMin - margin,
    yMax: panel.yMax + margin,
  };
}
