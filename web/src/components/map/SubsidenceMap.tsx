import maplibregl, { type Map as MapLibreMap, type Marker } from 'maplibre-gl';
import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useMemo, useRef, useState } from 'react';
import { GATEWAY_LATLON, localToWgs84 } from '@/sim/field';
import { panelExtent } from '@/sim/feed';
import { RISK_BANDS, renderHeat } from './heat';
import { IconCrosshair, IconLayers, IconMinus, IconPlus } from '@/components/ui/icons';
import type { MeshLink, NodeReading } from '@/data/types';

const RISK_HEX: Record<string, string> = {
  low: '#0ca30c', medium: '#fab219', high: '#ec835a', critical: '#d03b3b',
};

const HEAT_W = 260;
const HEAT_H = 200;

/** Esri World Imagery -- no API key, and the only key-free global satellite
 *  basemap that survives being embedded. Tiles failing offline is graceful:
 *  the dark plane shows through and every overlay still renders. */
const SATELLITE_TILES =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

interface Props {
  nodes: NodeReading[];
  links: MeshLink[];
  selectedAddr: number;
  onSelect: (addr: number) => void;
  onToggleNode?: (addr: number) => void;
}

export function SubsidenceMap({ nodes, links, selectedAddr, onSelect, onToggleNode }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markersRef = useRef<Map<number, Marker>>(new Map());
  const [ready, setReady] = useState(false);
  const [showLinks, setShowLinks] = useState(true);
  const [satellite, setSatellite] = useState(true);

  const extent = useMemo(() => panelExtent(), []);
  const corners = useMemo(() => {
    const tl = localToWgs84(extent.xMin, extent.yMax);
    const tr = localToWgs84(extent.xMax, extent.yMax);
    const br = localToWgs84(extent.xMax, extent.yMin);
    const bl = localToWgs84(extent.xMin, extent.yMin);
    return [
      [tl.lon, tl.lat], [tr.lon, tr.lat], [br.lon, br.lat], [bl.lon, bl.lat],
    ] as [[number, number], [number, number], [number, number], [number, number]];
  }, [extent]);

  // ---------------------------------------------------------------- map init
  useEffect(() => {
    if (!containerRef.current || !canvasRef.current || mapRef.current) return;

    const centre = localToWgs84((extent.xMin + extent.xMax) / 2, (extent.yMin + extent.yMax) / 2);
    const map = new maplibregl.Map({
      container: containerRef.current,
      center: [centre.lon, centre.lat],
      zoom: 14.6,
      attributionControl: false,
      style: {
        version: 8,
        sources: {
          sat: {
            type: 'raster',
            tiles: [SATELLITE_TILES],
            tileSize: 256,
            maxzoom: 19,
            attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
          },
        },
        layers: [
          { id: 'plane', type: 'background', paint: { 'background-color': '#0a0f16' } },
          {
            id: 'sat',
            type: 'raster',
            source: 'sat',
            // Knocked back so the deformation overlay stays the brightest thing.
            paint: { 'raster-brightness-max': 0.82, 'raster-saturation': -0.2, 'raster-contrast': 0.05 },
          },
        ],
      },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: 'metric' }), 'bottom-left');

    map.on('load', () => {
      map.addSource('heat', {
        type: 'canvas',
        canvas: canvasRef.current!,
        coordinates: corners,
        animate: true,
      });
      map.addLayer({
        id: 'heat',
        type: 'raster',
        source: 'heat',
        paint: { 'raster-opacity': 0.66, 'raster-resampling': 'linear' },
      });

      map.addSource('links', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
      // Idle links: thin, static. Route links: brighter, animated dash.
      map.addLayer({
        id: 'links-idle',
        type: 'line',
        source: 'links',
        filter: ['!', ['get', 'onRoute']],
        paint: {
          'line-color': '#ffffff',
          'line-opacity': 0.28,
          'line-width': 1,
          'line-dasharray': [2, 3],
        },
      });
      map.addLayer({
        id: 'links-route',
        type: 'line',
        source: 'links',
        filter: ['get', 'onRoute'],
        paint: {
          'line-color': '#ffffff',
          'line-opacity': 0.78,
          'line-width': 1.8,
          'line-dasharray': [1.5, 2],
        },
      });
      setReady(true);
    });

    return () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current.clear();
      map.remove();
      mapRef.current = null;
    };
  }, [corners, extent]);

  // Animate the dash offset so traffic visibly flows toward the gateway.
  useEffect(() => {
    if (!ready) return;
    let raf = 0;
    let phase = 0;
    const step = () => {
      phase = (phase + 0.06) % 3.5;
      const map = mapRef.current;
      if (map?.getLayer('links-route')) {
        map.setPaintProperty('links-route', 'line-dasharray', [1.5, 2, phase * 0.0001 + 0.0001]);
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [ready]);

  // -------------------------------------------------------------- basemap toggle
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map?.getLayer('sat')) return;
    map.setLayoutProperty('sat', 'visibility', satellite ? 'visible' : 'none');
  }, [satellite, ready]);

  // ------------------------------------------------------------------- heat
  useEffect(() => {
    if (!canvasRef.current) return;
    renderHeat(canvasRef.current, nodes, extent);
  }, [nodes, extent]);

  // ------------------------------------------------------------------ links
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const byAddr = new Map(nodes.map((n) => [n.addr, n]));
    const features = links.flatMap((l) => {
      const a = byAddr.get(l.a);
      const b = byAddr.get(l.b);
      if (!a || !b) return [];
      return [{
        type: 'Feature' as const,
        properties: { onRoute: l.onRoute },
        geometry: {
          type: 'LineString' as const,
          coordinates: [[a.lon, a.lat], [b.lon, b.lat]],
        },
      }];
    });
    // The gateway uplink itself, so the route visibly terminates somewhere.
    for (const n of nodes.filter((x) => x.online && x.hops === 1)) {
      features.push({
        type: 'Feature',
        properties: { onRoute: true },
        geometry: {
          type: 'LineString',
          coordinates: [[n.lon, n.lat], [GATEWAY_LATLON.lon, GATEWAY_LATLON.lat]],
        },
      });
    }
    const src = map.getSource('links') as maplibregl.GeoJSONSource | undefined;
    src?.setData({ type: 'FeatureCollection', features });

    const visibility = showLinks ? 'visible' : 'none';
    for (const id of ['links-idle', 'links-route']) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visibility);
    }
  }, [links, nodes, ready, showLinks]);

  // ---------------------------------------------------------------- markers
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;

    for (const n of nodes) {
      let marker = markersRef.current.get(n.addr);
      if (!marker) {
        const el = document.createElement('button');
        el.type = 'button';
        el.className = 'mg-node';
        el.addEventListener('click', (ev) => {
          if (ev.shiftKey) onToggleNode?.(n.addr);
          else onSelect(n.addr);
        });
        marker = new maplibregl.Marker({ element: el }).setLngLat([n.lon, n.lat]).addTo(map);
        markersRef.current.set(n.addr, marker);
      }
      const el = marker.getElement();
      const colour = n.online ? RISK_HEX[n.risk] : '#4b5563';
      const selected = n.addr === selectedAddr;
      el.setAttribute(
        'aria-label',
        `Node ${n.id}, ${n.zone}, ${n.online ? `${n.risk} risk` : 'offline'}`,
      );
      el.title = `Node ${n.id} · ${n.zone}\n${
        n.online
          ? `Tilt ${n.tiltDeg.toFixed(2)}° · Crack ${n.crackMm.toFixed(2)} mm · ${n.hops} hop${n.hops === 1 ? '' : 's'}`
          : 'Offline'
      }\nShift-click to toggle power`;
      el.innerHTML = `
        <span class="mg-node__wrap">
          ${n.risk === 'critical' && n.online
            ? `<span class="mg-node__ring" style="background:${colour}"></span>` : ''}
          <span class="mg-node__dot" style="border-color:${colour};${
            selected ? `box-shadow:0 0 0 3px rgba(255,255,255,.75), 0 0 16px ${colour};` : ''
          }">
            <span class="mg-node__id">${n.id}</span>
          </span>
        </span>`;
      el.style.opacity = n.online ? '1' : '0.45';
    }
  }, [nodes, ready, selectedAddr, onSelect, onToggleNode]);

  const zoom = (delta: number) => mapRef.current?.zoomTo((mapRef.current?.getZoom() ?? 14) + delta, { duration: 320 });
  const recentre = () => {
    const c = localToWgs84((extent.xMin + extent.xMax) / 2, (extent.yMin + extent.yMax) / 2);
    mapRef.current?.easeTo({ center: [c.lon, c.lat], zoom: 14.6, duration: 700 });
  };

  return (
    <div className="relative h-full w-full overflow-hidden rounded-b-xl">
      <div ref={containerRef} className="absolute inset-0" />
      <canvas ref={canvasRef} width={HEAT_W} height={HEAT_H} className="hidden" />

      {/* Map controls */}
      <div className="absolute left-3 top-3 flex flex-col gap-1.5">
        {[
          { Icon: IconPlus, label: 'Zoom in', onClick: () => zoom(1) },
          { Icon: IconMinus, label: 'Zoom out', onClick: () => zoom(-1) },
          { Icon: IconCrosshair, label: 'Recentre on panel', onClick: recentre },
          { Icon: IconLayers, label: 'Toggle satellite imagery', onClick: () => setSatellite((v) => !v) },
        ].map(({ Icon, label, onClick }) => (
          <motion.button
            key={label}
            type="button"
            onClick={onClick}
            aria-label={label}
            title={label}
            whileTap={{ scale: 0.9 }}
            className="focus-ring grid h-8 w-8 place-items-center rounded-md border border-white/12 bg-plane/80 text-ink-2 backdrop-blur transition-colors hover:bg-surface-2 hover:text-ink"
          >
            <Icon size={16} />
          </motion.button>
        ))}
      </div>

      {/* Legend -- bands are named, never carried by colour alone. */}
      <motion.div
        initial={{ opacity: 0, x: 12 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.3 }}
        className="absolute right-3 top-3 rounded-lg border border-white/12 bg-plane/85 px-3 py-2.5 backdrop-blur"
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

      {/* Mesh link toggle */}
      <AnimatePresence>
        <motion.label
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.35 }}
          className="absolute bottom-9 right-3 flex cursor-pointer select-none items-center gap-2 rounded-lg border border-white/12 bg-plane/85 px-3 py-2 text-[11px] font-medium text-ink backdrop-blur"
        >
          <input
            type="checkbox"
            checked={showLinks}
            onChange={(e) => setShowLinks(e.target.checked)}
            className="focus-ring h-3.5 w-3.5 accent-brand"
          />
          Show Mesh Links
        </motion.label>
      </AnimatePresence>
    </div>
  );
}
