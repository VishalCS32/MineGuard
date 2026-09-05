/**
 * Minimal SVG line chart with a crosshair + tooltip.
 *
 * Deliberately single-axis. Two measures on different scales get two charts or
 * small multiples, never a second y-axis: the alignment between two scales is
 * arbitrary, so a dual axis invents a correlation the data does not contain.
 */
import { useMemo, useState } from 'react';
import { useSize } from '@/hooks/useSize';

export interface Pt {
  x: number;
  y: number | null;
}

export interface Series {
  key: string;
  label: string;
  color: string;
  points: Pt[];
  dashed?: boolean;
}

interface Props {
  series: Series[];
  height?: number;
  yDomain?: [number, number];
  yTicks?: number;
  formatY?: (v: number) => string;
  formatX?: (v: number) => string;
  xTickValues?: number[];
  unit?: string;
  showLegend?: boolean;
  hideXAxis?: boolean;
  padLeft?: number;
}

const AXIS = '#383835';
const GRID = '#2c2c2a';
const MUTED = '#898781';

export function LineChart({
  series, height = 160, yDomain, yTicks = 4, formatY = (v) => v.toFixed(1),
  formatX = (v) => String(v), xTickValues, unit, showLegend = true,
  hideXAxis = false, padLeft = 40,
}: Props) {
  const { ref, width } = useSize<HTMLDivElement>();
  const [hoverX, setHoverX] = useState<number | null>(null);

  const pad = { top: 10, right: 12, bottom: hideXAxis ? 8 : 22, left: padLeft };
  const w = Math.max(0, width - pad.left - pad.right);
  const h = Math.max(0, height - pad.top - pad.bottom);

  const { xMin, xMax, yMin, yMax } = useMemo(() => {
    const xs = series.flatMap((s) => s.points.map((p) => p.x));
    const ys = series.flatMap((s) => s.points.filter((p) => p.y !== null).map((p) => p.y as number));
    const yLo = yDomain ? yDomain[0] : Math.min(0, ...ys);
    const yHi = yDomain ? yDomain[1] : Math.max(...ys, yLo + 1e-6);
    const span = yHi - yLo || 1;
    // Domain from the data alone. Forcing 0 in here would be harmless for a
    // 0..1 score and catastrophic for epoch-millisecond timestamps, which would
    // all collapse onto the right-hand edge.
    return {
      xMin: xs.length ? Math.min(...xs) : 0,
      xMax: xs.length ? Math.max(...xs) : 1,
      yMin: yDomain ? yLo : yLo - span * 0.06,
      yMax: yDomain ? yHi : yHi + span * 0.12,
    };
  }, [series, yDomain]);

  const sx = (x: number) => (w <= 0 ? 0 : ((x - xMin) / (xMax - xMin || 1)) * w);
  const sy = (y: number) => (h <= 0 ? 0 : h - ((y - yMin) / (yMax - yMin || 1)) * h);

  const path = (s: Series) => {
    let d = '';
    let pen = false;
    for (const p of s.points) {
      if (p.y === null) { pen = false; continue; }
      d += `${pen ? 'L' : 'M'}${sx(p.x).toFixed(2)} ${sy(p.y).toFixed(2)}`;
      pen = true;
    }
    return d;
  };

  const ticks = useMemo(() => {
    const out: number[] = [];
    for (let i = 0; i <= yTicks; i++) out.push(yMin + ((yMax - yMin) * i) / yTicks);
    return out;
  }, [yMin, yMax, yTicks]);

  // Nearest sample to the pointer, shared by every series (they share an x grid).
  const hoverIndex = useMemo(() => {
    if (hoverX === null || !series[0]?.points.length) return null;
    const target = xMin + (hoverX / (w || 1)) * (xMax - xMin);
    let best = 0;
    let bestD = Infinity;
    series[0].points.forEach((p, i) => {
      const d = Math.abs(p.x - target);
      if (d < bestD) { bestD = d; best = i; }
    });
    return best;
  }, [hoverX, series, w, xMin, xMax]);

  const hoveredPoint = hoverIndex !== null ? series[0].points[hoverIndex] : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {showLegend && series.length > 1 && (
        <ul className="mb-1 flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[10px] text-ink-2">
          {series.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <svg width="14" height="8" aria-hidden="true">
                <line
                  x1="0" y1="4" x2="14" y2="4"
                  stroke={s.color} strokeWidth="2"
                  strokeDasharray={s.dashed ? '3 2.5' : undefined}
                  strokeLinecap="round"
                />
              </svg>
              {s.label}
            </li>
          ))}
        </ul>
      )}

      <div ref={ref} className="relative min-h-0 flex-1" style={{ height }}>
        {width > 0 && (
          <svg
            width={width}
            height={height}
            role="img"
            aria-label={`Line chart: ${series.map((s) => s.label).join(', ')}`}
            onPointerMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              setHoverX(e.clientX - rect.left - pad.left);
            }}
            onPointerLeave={() => setHoverX(null)}
          >
            <g transform={`translate(${pad.left},${pad.top})`}>
              {/* Recessive grid */}
              {ticks.map((t) => (
                <g key={t}>
                  <line x1={0} x2={w} y1={sy(t)} y2={sy(t)} stroke={GRID} strokeWidth={1} />
                  <text
                    x={-8} y={sy(t)} dy="0.32em" textAnchor="end"
                    fill={MUTED} fontSize={9.5} style={{ fontVariantNumeric: 'tabular-nums' }}
                  >
                    {formatY(t)}
                  </text>
                </g>
              ))}

              {!hideXAxis && (
                <>
                  <line x1={0} x2={w} y1={h} y2={h} stroke={AXIS} strokeWidth={1} />
                  {(xTickValues ?? []).map((t) => (
                    <text
                      key={t} x={sx(t)} y={h + 14} textAnchor="middle"
                      fill={MUTED} fontSize={9.5}
                    >
                      {formatX(t)}
                    </text>
                  ))}
                </>
              )}

              {series.map((s) => (
                <path
                  key={s.key}
                  d={path(s)}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeDasharray={s.dashed ? '5 4' : undefined}
                />
              ))}

              {/* Crosshair */}
              {hoverIndex !== null && hoveredPoint && (
                <g pointerEvents="none">
                  <line
                    x1={sx(hoveredPoint.x)} x2={sx(hoveredPoint.x)} y1={0} y2={h}
                    stroke="#ffffff" strokeOpacity={0.35} strokeWidth={1}
                  />
                  {series.map((s) => {
                    const p = s.points[hoverIndex];
                    if (!p || p.y === null) return null;
                    return (
                      <circle
                        key={s.key} cx={sx(p.x)} cy={sy(p.y)} r={4}
                        fill={s.color} stroke="#151c25" strokeWidth={2}
                      />
                    );
                  })}
                </g>
              )}
            </g>
          </svg>
        )}

        {hoverIndex !== null && hoveredPoint && (
          <div
            className="pointer-events-none absolute z-10 min-w-[132px] rounded-lg border border-hairline bg-plane/95 px-2.5 py-2 text-[11px] shadow-card backdrop-blur"
            style={{
              left: Math.min(Math.max(sx(hoveredPoint.x) + pad.left + 12, 4), Math.max(4, width - 150)),
              top: 4,
            }}
          >
            <div className="mb-1 font-semibold text-ink">{formatX(hoveredPoint.x)}</div>
            {series.map((s) => {
              const p = s.points[hoverIndex];
              return (
                <div key={s.key} className="flex items-center justify-between gap-3 text-ink-2">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                    {s.label}
                  </span>
                  <span className="font-semibold tabular-nums text-ink">
                    {p?.y === null || p?.y === undefined ? '—' : `${formatY(p.y)}${unit ?? ''}`}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
