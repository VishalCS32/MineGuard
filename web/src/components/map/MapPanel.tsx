import { AnimatePresence, motion } from 'framer-motion';
import { useCallback, useRef, useState } from 'react';
import { LeafletMap } from './LeafletMap';
import { Scene3D, type Scene3DApi } from './Scene3D';
import { RISK_BANDS } from './heat';
import { IconCrosshair, IconLayers, IconMinus, IconPlus } from '@/components/ui/icons';
import type { MeshLink, NodeReading } from '@/data/types';

type Mode = '2D' | '3D';

const EXAGGERATIONS = [1, 10, 50, 100];

interface Props {
  nodes: NodeReading[];
  links: MeshLink[];
  day: number;
  selectedAddr: number;
  onSelect: (addr: number) => void;
  onToggleNode?: (addr: number) => void;
}

/**
 * Holds both views of the same ground and the chrome they share.
 *
 * 2-D is Leaflet: the plan view an operator navigates by, and the one that
 * answers "which node, which zone". 3-D is a Three.js terrain mesh: the same
 * surface with its actual shape, which answers "how bad, and where is it
 * steepest". Neither replaces the other, so the toggle is a peer switch rather
 * than a mode buried in a menu.
 */
export function MapPanel({ nodes, links, day, selectedAddr, onSelect, onToggleNode }: Props) {
  const [mode, setMode] = useState<Mode>('2D');
  const [showLinks, setShowLinks] = useState(true);
  const [satellite, setSatellite] = useState(true);
  const [exaggeration, setExaggeration] = useState(50);
  const apiRef = useRef<{ zoomIn: () => void; zoomOut: () => void; recentre: () => void } | null>(null);
  const scene3dRef = useRef<Scene3DApi | null>(null);
  const onReady = useCallback((api: NonNullable<typeof apiRef.current>) => {
    apiRef.current = api;
  }, []);
  const on3DReady = useCallback((api: Scene3DApi) => { scene3dRef.current = api; }, []);

  const is3D = mode === '3D';

  return (
    <div className="relative h-full w-full overflow-hidden">
      {/* Both views mount the same data; only one is shown at a time. */}
      {is3D ? (
        <Scene3D
          nodes={nodes}
          links={links}
          day={day}
          exaggeration={exaggeration}
          showLinks={showLinks}
          satellite={satellite}
          selectedAddr={selectedAddr}
          onSelect={onSelect}
          onReady={on3DReady}
        />
      ) : (
        <LeafletMap
          nodes={nodes}
          links={links}
          selectedAddr={selectedAddr}
          showLinks={showLinks}
          satellite={satellite}
          onSelect={onSelect}
          onToggleNode={onToggleNode}
          onReady={onReady}
        />
      )}

      {/* ---------------------------------------------------- mode switch */}
      <div className="pointer-events-auto absolute left-3 top-3 z-[500] flex gap-0.5 rounded-lg border border-white/12 bg-plane/85 p-0.5 backdrop-blur">
        {(['2D', '3D'] as Mode[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            aria-pressed={mode === m}
            className={`focus-ring relative rounded-md px-3 py-1 text-[11px] font-bold tracking-wide transition-colors ${
              mode === m ? 'text-white' : 'text-ink-3 hover:text-ink'
            }`}
          >
            {mode === m && (
              <motion.span
                layoutId="map-mode-pill"
                transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                className="absolute inset-0 rounded-md bg-brand-dim"
              />
            )}
            <span className="relative">{m}</span>
          </button>
        ))}
      </div>

      {/* ------------------------------------------------- view controls */}
      <div className="absolute left-3 top-[46px] z-[500] flex flex-col gap-1.5">
        {!is3D ? (
          <>
            <ControlButton label="Zoom in" onClick={() => apiRef.current?.zoomIn()}>
              <IconPlus size={16} />
            </ControlButton>
            <ControlButton label="Zoom out" onClick={() => apiRef.current?.zoomOut()}>
              <IconMinus size={16} />
            </ControlButton>
            <ControlButton label="Recentre on panel" onClick={() => apiRef.current?.recentre()}>
              <IconCrosshair size={16} />
            </ControlButton>
          </>
        ) : (
          <ControlButton label="Reset camera" onClick={() => scene3dRef.current?.resetView()}>
            <IconCrosshair size={16} />
          </ControlButton>
        )}
        <ControlButton
          label="Toggle satellite imagery"
          onClick={() => setSatellite((v) => !v)}
        >
          <IconLayers size={16} />
        </ControlButton>
      </div>

      {/* ------------------------------------------------------- legend */}
      <motion.div
        initial={{ opacity: 0, x: 12 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.25 }}
        className="absolute right-3 top-3 z-[500] rounded-lg border border-white/12 bg-plane/85 px-3 py-2.5 backdrop-blur"
      >
        <div className="mb-1.5 text-[11px] font-semibold text-ink">Deformation Risk</div>
        <ul className="space-y-1">
          {RISK_BANDS.map((b) => (
            <li key={b.key} className="flex items-center gap-2 text-[11px] text-ink-2">
              <span
                className="h-2.5 w-2.5 rounded-full ring-1 ring-black/40"
                style={{ background: b.hex }}
              />
              {b.label}
            </li>
          ))}
        </ul>
      </motion.div>

      {/* ------------------------------------- 3-D vertical exaggeration */}
      <AnimatePresence>
        {is3D && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            className="absolute bottom-3 left-3 z-[500] rounded-lg border border-white/12 bg-plane/85 px-3 py-2 backdrop-blur"
          >
            <div className="mb-1 flex items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-2">
                Vertical exaggeration
              </span>
              <span className="rounded bg-warning/15 px-1.5 py-0.5 text-[10px] font-bold text-warning">
                {exaggeration}×
              </span>
            </div>
            <div className="flex gap-1">
              {EXAGGERATIONS.map((x) => (
                <button
                  key={x}
                  type="button"
                  onClick={() => setExaggeration(x)}
                  className={`focus-ring rounded px-2 py-0.5 text-[10px] font-semibold transition-colors ${
                    x === exaggeration
                      ? 'bg-brand-dim text-white'
                      : 'bg-surface-2 text-ink-3 hover:text-ink'
                  }`}
                >
                  {x === 1 ? 'True' : `${x}×`}
                </button>
              ))}
            </div>
            {/* Stated plainly so an exaggerated bowl is never read as real depth. */}
            <p className="mt-1 max-w-[190px] text-[9px] leading-snug text-ink-3">
              Heights scaled {exaggeration}× — a 1.9 m trough spread over 800 m is
              near-invisible at true scale. Drag to orbit, scroll to zoom.
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* --------------------------------------------- mesh link toggle */}
      <label className="absolute bottom-9 right-3 z-[500] flex cursor-pointer select-none items-center gap-2 rounded-lg border border-white/12 bg-plane/85 px-3 py-2 text-[11px] font-medium text-ink backdrop-blur">
        <input
          type="checkbox"
          checked={showLinks}
          onChange={(e) => setShowLinks(e.target.checked)}
          className="focus-ring h-3.5 w-3.5 accent-brand"
        />
        Show Mesh Links
      </label>
    </div>
  );
}

function ControlButton({
  label, onClick, children,
}: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      whileTap={{ scale: 0.9 }}
      className="focus-ring grid h-8 w-8 place-items-center rounded-md border border-white/12 bg-plane/80 text-ink-2 backdrop-blur transition-colors hover:bg-surface-2 hover:text-ink"
    >
      {children}
    </motion.button>
  );
}
