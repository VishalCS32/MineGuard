import L from 'leaflet';
import { useEffect, useMemo, useRef } from 'react';
import { GATEWAY_LATLON, localToWgs84 } from '@/sim/field';
import { panelExtent } from '@/sim/surface';
import { renderHeat } from './heat';
import type { MeshLink, NodeReading } from '@/data/types';

const RISK_HEX: Record<string, string> = {
  low: '#00c14f', medium: '#f2dc00', high: '#ff7a00', critical: '#e80038',
};

const HEAT_W = 300;
const HEAT_H = 240;
/** The heat overlay is a data URL; regenerating it every 250 ms tick is wasteful
 *  and invisible, so it refreshes about once a second. */
const HEAT_EVERY_MS = 900;

const SATELLITE =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

interface Props {
  nodes: NodeReading[];
  links: MeshLink[];
  selectedAddr: number;
  showLinks: boolean;
  satellite: boolean;
  onSelect: (addr: number) => void;
  onToggleNode?: (addr: number) => void;
  /** Registers imperative zoom/recentre handles with the parent chrome. */
  onReady?: (api: { zoomIn: () => void; zoomOut: () => void; recentre: () => void }) => void;
}

export function LeafletMap({
  nodes, links, selectedAddr, showLinks, satellite, onSelect, onToggleNode, onReady,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const satLayerRef = useRef<L.TileLayer | null>(null);
  const heatRef = useRef<L.ImageOverlay | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const lastHeatRef = useRef(0);
  const linkLayerRef = useRef<L.LayerGroup | null>(null);
  const markersRef = useRef<Map<number, L.Marker>>(new Map());
  const handlersRef = useRef({ onSelect, onToggleNode });
  handlersRef.current = { onSelect, onToggleNode };

  const extent = useMemo(() => panelExtent(), []);
  const bounds = useMemo(() => {
    const sw = localToWgs84(extent.xMin, extent.yMin);
    const ne = localToWgs84(extent.xMax, extent.yMax);
    return L.latLngBounds([sw.lat, sw.lon], [ne.lat, ne.lon]);
  }, [extent]);

  // ------------------------------------------------------------------ setup
  useEffect(() => {
    if (!hostRef.current || mapRef.current) return;

    const map = L.map(hostRef.current, {
      center: bounds.getCenter(),
      zoom: 15,
      zoomControl: false,
      attributionControl: true,
      preferCanvas: false,
      zoomSnap: 0.25,
    });
    mapRef.current = map;

    satLayerRef.current = L.tileLayer(SATELLITE, {
      maxZoom: 19,
      attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics',
      className: 'mg-tiles',
    }).addTo(map);

    L.control.scale({ metric: true, imperial: false, maxWidth: 110 }).addTo(map);

    const canvas = document.createElement('canvas');
    canvas.width = HEAT_W;
    canvas.height = HEAT_H;
    canvasRef.current = canvas;

    linkLayerRef.current = L.layerGroup().addTo(map);

    // Leaflet caches the container size at construction. Inside a flex/grid
    // dashboard the panel has not been laid out yet at that point, so fitting the
    // bounds immediately fits them to the wrong box and overshoots the zoom --
    // which is why the field ran off the bottom of the map. Re-measure whenever
    // the panel resizes, and only frame the field once a real size exists.
    let framed = false;
    const ro = new ResizeObserver(() => {
      map.invalidateSize({ animate: false });
      if (!framed && hostRef.current && hostRef.current.clientHeight > 80) {
        framed = true;
        map.fitBounds(bounds, { padding: [24, 24] });
      }
    });
    ro.observe(hostRef.current);

    onReady?.({
      zoomIn: () => map.zoomIn(1),
      zoomOut: () => map.zoomOut(1),
      recentre: () => map.flyToBounds(bounds, { padding: [24, 24], duration: 0.7 }),
    });

    return () => {
      ro.disconnect();
      markersRef.current.clear();
      map.remove();
      mapRef.current = null;
      heatRef.current = null;
      linkLayerRef.current = null;
    };
  }, [bounds, onReady]);

  // ------------------------------------------------------------- basemap
  useEffect(() => {
    const map = mapRef.current;
    const layer = satLayerRef.current;
    if (!map || !layer) return;
    if (satellite && !map.hasLayer(layer)) layer.addTo(map);
    if (!satellite && map.hasLayer(layer)) map.removeLayer(layer);
  }, [satellite]);

  // ---------------------------------------------------------------- heat
  useEffect(() => {
    const map = mapRef.current;
    const canvas = canvasRef.current;
    if (!map || !canvas) return;
    const now = performance.now();
    if (now - lastHeatRef.current < HEAT_EVERY_MS && heatRef.current) return;
    lastHeatRef.current = now;

    renderHeat(canvas, nodes, extent);
    const url = canvas.toDataURL();
    if (!heatRef.current) {
      heatRef.current = L.imageOverlay(url, bounds, {
        opacity: 0.76,
        interactive: false,
        className: 'mg-heat',
      }).addTo(map);
    } else {
      heatRef.current.setUrl(url);
    }
  }, [nodes, extent, bounds]);

  // --------------------------------------------------------------- links
  useEffect(() => {
    const group = linkLayerRef.current;
    if (!group) return;
    group.clearLayers();
    if (!showLinks) return;

    const byAddr = new Map(nodes.map((n) => [n.addr, n]));
    for (const l of links) {
      const a = byAddr.get(l.a);
      const b = byAddr.get(l.b);
      if (!a || !b) continue;
      L.polyline([[a.lat, a.lon], [b.lat, b.lon]], {
        color: '#ffffff',
        weight: l.onRoute ? 1.8 : 1,
        opacity: l.onRoute ? 0.78 : 0.26,
        dashArray: l.onRoute ? '4 4' : '2 5',
        className: l.onRoute ? 'mg-link mg-link--route' : 'mg-link',
        interactive: false,
      }).addTo(group);
    }
    // The gateway uplink, so routes visibly terminate somewhere.
    for (const n of nodes.filter((x) => x.online && x.hops === 1)) {
      L.polyline([[n.lat, n.lon], [GATEWAY_LATLON.lat, GATEWAY_LATLON.lon]], {
        color: '#ffffff', weight: 1.8, opacity: 0.7, dashArray: '4 4',
        className: 'mg-link mg-link--route', interactive: false,
      }).addTo(group);
    }
  }, [links, nodes, showLinks]);

  // ------------------------------------------------------------- markers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    for (const n of nodes) {
      const colour = n.online ? RISK_HEX[n.risk] : '#4b5563';
      const selected = n.addr === selectedAddr;
      const html = `
        <span class="mg-node__wrap">
          ${n.risk === 'critical' && n.online
            ? `<span class="mg-node__ring" style="background:${colour}"></span>` : ''}
          <span class="mg-node__dot" style="border-color:${colour};${
            selected ? `box-shadow:0 0 0 3px rgba(255,255,255,.75), 0 0 16px ${colour};` : ''
          }">
            <span class="mg-node__id">${n.id}</span>
          </span>
        </span>`;
      const icon = L.divIcon({
        html, className: 'mg-node', iconSize: [30, 30], iconAnchor: [15, 15],
      });

      let marker = markersRef.current.get(n.addr);
      if (!marker) {
        marker = L.marker([n.lat, n.lon], { icon, keyboard: true, riseOnHover: true })
          .addTo(map)
          .on('click', (ev) => {
            const orig = (ev as unknown as { originalEvent: MouseEvent }).originalEvent;
            if (orig?.shiftKey) handlersRef.current.onToggleNode?.(n.addr);
            else handlersRef.current.onSelect(n.addr);
          });
        markersRef.current.set(n.addr, marker);
      } else {
        marker.setIcon(icon);
      }
      marker.setOpacity(n.online ? 1 : 0.45);
      const detail = n.online
        ? `Tilt ${n.tiltDeg.toFixed(2)}° · Strain ${n.strainMmPerM >= 0 ? '+' : ''}${n.strainMmPerM.toFixed(2)} mm/m · ${n.hops} hop${n.hops === 1 ? '' : 's'}`
        : 'Offline';
      marker.getElement()?.setAttribute(
        'title', `Node ${n.id} · ${n.zone}\n${detail}\nShift-click to toggle power`);
      marker.getElement()?.setAttribute(
        'aria-label', `Node ${n.id}, ${n.zone}, ${n.online ? `${n.risk} risk` : 'offline'}`);
    }
  }, [nodes, selectedAddr]);

  return <div ref={hostRef} className="absolute inset-0" />;
}
