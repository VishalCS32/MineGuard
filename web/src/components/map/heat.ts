/**
 * Renders the interpolated deformation surface into a canvas for the map overlay.
 *
 * Values between nodes come from inverse-distance weighting of the live node
 * readings -- the same spatial fusion the backend does before polygonising risk
 * zones. It is an interpolation of real measurements, not a decorative blob, so
 * the shape between sensors is an honest estimate and is drawn as one.
 *
 * Risk is a *banded* quantity (Low / Medium / High / Critical), so it is painted
 * with the reserved status palette rather than a rainbow. Band boundaries also
 * carry a contour stroke: the warning and serious steps sit closer together than
 * the normal-vision separation floor, so the bands must not be told apart by hue
 * alone. Contour + legend label + node badge carry it instead.
 */
import type { NodeReading } from '@/data/types';

export interface Extent {
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

/** Reserved status palette. Index = risk band. */
const BANDS = [
  { stop: 0.35, rgb: [0, 193, 79] as const },    // good      -> Low
  { stop: 0.6, rgb: [242, 220, 0] as const },    // warning   -> Medium
  { stop: 0.85, rgb: [255, 122, 0] as const },   // serious   -> High
  { stop: 1.01, rgb: [232, 0, 56] as const },    // critical  -> Critical
];

export const RISK_BANDS = [
  { key: 'low', label: 'Low', hex: '#00c14f' },
  { key: 'medium', label: 'Medium', hex: '#f2dc00' },
  { key: 'high', label: 'High', hex: '#ff7a00' },
  { key: 'critical', label: 'Critical', hex: '#e80038' },
] as const;

function bandIndex(v: number): number {
  for (let i = 0; i < BANDS.length; i++) if (v < BANDS[i].stop) return i;
  return BANDS.length - 1;
}

/** Smooth colour within the banded ramp, so the surface still reads continuously. */
function rampColor(v: number): [number, number, number] {
  const idx = bandIndex(v);
  const lo = idx === 0 ? 0 : BANDS[idx - 1].stop;
  const hi = BANDS[idx].stop;
  const t = Math.min(1, Math.max(0, (v - lo) / (hi - lo)));
  const from = idx === 0 ? BANDS[0].rgb : BANDS[idx - 1].rgb;
  const to = BANDS[idx].rgb;
  return [
    Math.round(from[0] + (to[0] - from[0]) * t),
    Math.round(from[1] + (to[1] - from[1]) * t),
    Math.round(from[2] + (to[2] - from[2]) * t),
  ];
}

/** Inverse-distance weighting over the live node readings. */
function interpolate(
  x: number, y: number, nodes: NodeReading[], power = 2, smoothing = 24,
): number {
  let num = 0;
  let den = 0;
  for (const n of nodes) {
    const d2 = (x - n.x) ** 2 + (y - n.y) ** 2 + smoothing ** 2;
    const w = 1 / Math.pow(d2, power / 2);
    num += w * n.riskScore;
    den += w;
  }
  return den === 0 ? 0 : num / den;
}

export function renderHeat(
  canvas: HTMLCanvasElement,
  nodes: NodeReading[],
  extent: Extent,
): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const { width: w, height: h } = canvas;
  const img = ctx.createImageData(w, h);
  const data = img.data;

  const live = nodes.filter((n) => n.online);
  if (live.length === 0) {
    ctx.clearRect(0, 0, w, h);
    return;
  }

  // Pass 1: interpolated risk value per pixel.
  const field = new Float32Array(w * h);
  for (let py = 0; py < h; py++) {
    // Canvas y runs downward; local y runs north-up.
    const y = extent.yMax - ((py + 0.5) / h) * (extent.yMax - extent.yMin);
    for (let px = 0; px < w; px++) {
      const x = extent.xMin + ((px + 0.5) / w) * (extent.xMax - extent.xMin);
      field[py * w + px] = interpolate(x, y, live);
    }
  }

  // Pass 1b: distance to the nearest live node, as a confidence mask.
  const confidence = new Float32Array(w * h);
  const FULL_M = 120;   // within this, a node effectively observes the ground
  const FADE_M = 260;   // beyond this, we claim nothing
  for (let py = 0; py < h; py++) {
    const y = extent.yMax - ((py + 0.5) / h) * (extent.yMax - extent.yMin);
    for (let px = 0; px < w; px++) {
      const x = extent.xMin + ((px + 0.5) / w) * (extent.xMax - extent.xMin);
      let nearest = Infinity;
      for (const n of live) {
        const d2 = (x - n.x) ** 2 + (y - n.y) ** 2;
        if (d2 < nearest) nearest = d2;
      }
      const d = Math.sqrt(nearest);
      const t = 1 - Math.min(1, Math.max(0, (d - FULL_M) / (FADE_M - FULL_M)));
      confidence[py * w + px] = t * t * (3 - 2 * t);   // smoothstep
    }
  }

  // Pass 2: colour, alpha ramp, and contour strokes on band boundaries.
  for (let py = 0; py < h; py++) {
    for (let px = 0; px < w; px++) {
      const i = py * w + px;
      const v = field[i];
      const [r, g, b] = rampColor(v);

      // Opacity tracks risk across the whole range, not just the bottom of it.
      // Saturating alpha early makes calm ground as loud as a failing panel and
      // flattens the gradient; ramping it right through means the overlay only
      // becomes solid where the danger actually is, and quiet ground keeps
      // showing the terrain underneath.
      let alpha = Math.min(1, Math.max(0, (v - 0.08) / 0.62)) ** 0.85 * 242;

      // And fade out away from the sensors themselves. Inverse-distance
      // weighting will happily extrapolate a confident-looking value across
      // ground no node can see, which would paint a hard-edged rectangle of
      // invented certainty. Confidence decays with distance to the nearest node,
      // so the overlay stops where the evidence does.
      alpha *= confidence[i];

      const bi = bandIndex(v);
      const leftDiff = px > 0 && bandIndex(field[i - 1]) !== bi;
      const upDiff = py > 0 && bandIndex(field[i - w]) !== bi;
      const onContour = leftDiff || upDiff;

      const o = i * 4;
      if (onContour && v > 0.1) {
        // Darkened boundary: geometry carries the band change, not hue alone.
        data[o] = Math.round(r * 0.45);
        data[o + 1] = Math.round(g * 0.45);
        data[o + 2] = Math.round(b * 0.45);
        data[o + 3] = Math.max(alpha, 190);
      } else {
        data[o] = r;
        data[o + 1] = g;
        data[o + 2] = b;
        data[o + 3] = alpha;
      }
    }
  }
  ctx.putImageData(img, 0, 0);
}
