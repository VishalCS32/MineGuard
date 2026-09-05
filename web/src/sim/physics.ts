/**
 * Subsidence physics -- browser port of `ml/simulator/physics.py`.
 *
 * The dashboard runs the same influence-function (Knothe) model the backend and
 * the ML training pipeline use, so what you see on screen is real subsidence
 * behaviour rather than decorative noise: the trough is symmetric, subsidence is
 * exactly half of maximum above the panel edge, tilt peaks at the edge and
 * vanishes at the centre, and strain is tensile at the rim but compressive over
 * the goaf. Those are the shapes an operator learns to read.
 *
 * When the FastAPI backend is connected this module stops driving the UI and
 * becomes the offline demo fallback -- the shapes it produces stay identical.
 */

/** Complementary error function, Chebyshev approximation (|err| < 1.2e-7). */
export function erfc(x: number): number {
  const z = Math.abs(x);
  const t = 2 / (2 + z);
  const ty = 4 * t - 2;
  const cof = [
    -1.3026537197817094, 6.4196979235649026e-1, 1.9476473204185836e-2,
    -9.561514786808631e-3, -9.46595344482036e-4, 3.66839497852761e-4,
    4.2523324806907e-5, -2.0278578112534e-5, -1.624290004647e-6,
    1.30365583558e-6, 1.5626441722e-8, -8.5238095915e-8,
    6.529054439e-9, 5.059343495e-9, -9.91364156e-10,
    -2.27365122e-10, 9.6467911e-11, 2.394038e-12,
    -6.886027e-12, 8.94487e-13, 3.13092e-13,
    -1.12708e-13, 3.81e-16, 7.106e-15,
  ];
  let d = 0;
  let dd = 0;
  for (let j = cof.length - 1; j > 0; j--) {
    const tmp = d;
    d = ty * d - dd + cof[j];
    dd = tmp;
  }
  const ans = t * Math.exp(-z * z + 0.5 * (cof[0] + ty * d) - dd);
  return x >= 0 ? ans : 2 - ans;
}

export interface PanelGeometry {
  xStart: number;
  xEnd: number;
  yMin: number;
  yMax: number;
  seamDepthM: number;
  extractionThicknessM: number;
  subsidenceFactor: number;
  angleOfDrawDeg: number;
  horizontalDispFactor: number;
}

export const DEFAULT_PANEL: PanelGeometry = {
  xStart: 0,
  xEnd: 600,
  yMin: -150,
  yMax: 150,
  seamDepthM: 150,
  extractionThicknessM: 3.0,
  subsidenceFactor: 0.65,
  angleOfDrawDeg: 35,
  horizontalDispFactor: 0.4,
};

/** Maximum possible subsidence for a fully critical panel, in metres. */
export const sMax = (p: PanelGeometry) => p.subsidenceFactor * p.extractionThicknessM;

/** r = H / tan(beta) -- how far past the panel edge movement reaches. */
export const radiusOfInfluence = (p: PanelGeometry) =>
  p.seamDepthM / Math.tan((p.angleOfDrawDeg * Math.PI) / 180);

/** B, relating tilt to horizontal displacement. */
export const bCoefficient = (p: PanelGeometry) => p.horizontalDispFactor * p.seamDepthM;

export interface Movement {
  /** Vertical displacement, mm (positive downward). */
  subsidenceMm: number;
  /** Tilt components, mm/m. */
  tiltX: number;
  tiltY: number;
  /** Governing horizontal strain, mm/m. Tensile positive. */
  strain: number;
  /** Resultant tilt magnitude, mm/m. */
  tilt: number;
}

/** Fraction of S_max from extraction spanning [a, b] along one axis. */
function profile(u: number, a: number, b: number, r: number): number {
  const k = Math.sqrt(Math.PI) / r;
  return 0.5 * (erfc(k * (u - b)) - erfc(k * (u - a)));
}

/** First derivative -- the difference of two Knothe influence functions. */
function profileD1(u: number, a: number, b: number, r: number): number {
  return (
    (1 / r) *
    (Math.exp((-Math.PI * (u - a) ** 2) / (r * r)) -
      Math.exp((-Math.PI * (u - b) ** 2) / (r * r)))
  );
}

/** Second derivative -- drives horizontal strain. */
function profileD2(u: number, a: number, b: number, r: number): number {
  const coef = (2 * Math.PI) / r ** 3;
  return (
    coef *
    ((u - b) * Math.exp((-Math.PI * (u - b) ** 2) / (r * r)) -
      (u - a) * Math.exp((-Math.PI * (u - a) ** 2) / (r * r)))
  );
}

/**
 * Surface movement at (x, y) for a face that has reached `faceX`.
 * `completion` in [0, 1] models the lag between extraction and final settlement.
 */
export function evaluate(
  p: PanelGeometry,
  x: number,
  y: number,
  faceX: number,
  completion = 1,
): Movement {
  const r = radiusOfInfluence(p);
  const x2 = Math.min(Math.max(faceX, p.xStart), p.xEnd);
  if (x2 <= p.xStart) {
    return { subsidenceMm: 0, tiltX: 0, tiltY: 0, strain: 0, tilt: 0 };
  }
  const sMaxMm = sMax(p) * 1000 * completion;

  const fx = profile(x, p.xStart, x2, r);
  const fy = profile(y, p.yMin, p.yMax, r);
  const dfx = profileD1(x, p.xStart, x2, r);
  const dfy = profileD1(y, p.yMin, p.yMax, r);
  const d2fx = profileD2(x, p.xStart, x2, r);
  const d2fy = profileD2(y, p.yMin, p.yMax, r);

  const b = bCoefficient(p);
  const tiltX = sMaxMm * dfx * fy;
  const tiltY = sMaxMm * fx * dfy;
  const strainX = b * sMaxMm * d2fx * fy;
  const strainY = b * sMaxMm * fx * d2fy;

  return {
    subsidenceMm: sMaxMm * fx * fy,
    tiltX,
    tiltY,
    // Governing strain keeps its sign: tension opens cracks, compression does not.
    strain: Math.abs(strainX) >= Math.abs(strainY) ? strainX : strainY,
    tilt: Math.hypot(tiltX, tiltY),
  };
}

export type DamageClass = 'negligible' | 'slight' | 'appreciable' | 'severe' | 'very_severe';

const DAMAGE_ORDER: DamageClass[] = [
  'negligible', 'slight', 'appreciable', 'severe', 'very_severe',
];

/**
 * NCB-style structural damage band from strain, escalated by disruptive tilt.
 * Stated in the units a mine planner and a regulator already work in.
 */
export function classifyDamage(strainMmPerM: number, tiltMmPerM = 0): DamageClass {
  const magnitude = Math.abs(strainMmPerM);
  let damage: DamageClass = 'very_severe';
  for (const [limit, label] of [
    [0.5, 'negligible'], [1.5, 'slight'], [3.0, 'appreciable'], [6.0, 'severe'],
  ] as [number, DamageClass][]) {
    if (magnitude < limit) {
      damage = label;
      break;
    }
  }
  if (tiltMmPerM > 10) {
    damage = DAMAGE_ORDER[Math.min(DAMAGE_ORDER.indexOf(damage) + 1, DAMAGE_ORDER.length - 1)];
  }
  return damage;
}
