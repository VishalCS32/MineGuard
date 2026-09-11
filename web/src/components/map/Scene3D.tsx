/**
 * The subsidence trough as actual three-dimensional ground.
 *
 * A top-down map shows *where* the ground is moving; this shows *what shape* it
 * has taken. The bowl, its steep flanks over the panel edge, and the pothole
 * punched into the goaf are the physics made directly visible -- and the flanks
 * are exactly where tilt and strain peak, so the shape an operator sees is the
 * shape that does the damage.
 *
 * Vertical exaggeration is applied and labelled. At true scale a 1.9 m trough
 * spread over 800 m of surface is a barely perceptible dish; exaggeration is
 * standard practice in subsidence visualisation, and stating the factor on screen
 * keeps it from being read as real depth.
 */
import { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { panelExtent, subsidenceAt, subsidenceGrid } from '@/sim/surface';
import { renderHeat } from './heat';
import { stitchSatellite } from './tiles';
import { GATEWAY_LATLON } from '@/sim/field';
import type { MeshLink, NodeReading } from '@/data/types';

const RISK_HEX: Record<string, number> = {
  low: 0x00c14f, medium: 0xf2dc00, high: 0xff7a00, critical: 0xe80038,
};

const EARTH_RADIUS_M = 6378137;

/** Terrain tessellation. Cheap because the surface sampler is separable. */
const GRID_X = 140;
const GRID_Y = 110;
/** Height of a node's marker pole above the deformed ground, in metres. */
const POLE_M = 26;
const TEX_W = 640;
const TEX_H = 512;

export interface Scene3DApi {
  resetView: () => void;
}

interface Props {
  nodes: NodeReading[];
  links: MeshLink[];
  day: number;
  exaggeration: number;
  showLinks: boolean;
  satellite: boolean;
  selectedAddr: number;
  onSelect: (addr: number) => void;
  onReady?: (api: Scene3DApi) => void;
}

export function Scene3D({
  nodes, links, day, exaggeration, showLinks, satellite, selectedAddr, onSelect, onReady,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    controls: OrbitControls;
    terrain: THREE.Mesh;
    heatCanvas: HTMLCanvasElement;
    texCanvas: HTMLCanvasElement;
    texture: THREE.CanvasTexture;
    satCanvas: HTMLCanvasElement | null;
    nodeGroup: THREE.Group;
    linkGroup: THREE.Group;
    poles: Map<number, { pole: THREE.Mesh; head: THREE.Mesh; sprite: THREE.Sprite }>;
    raycaster: THREE.Raycaster;
    pointer: THREE.Vector2;
    frame: number;
  } | null>(null);

  // Compute dynamic geographic centroid of the active nodes
  const { centerLat, centerLon } = useMemo(() => {
    if (nodes.length > 0) {
      let minLat = Infinity;
      let maxLat = -Infinity;
      let minLon = Infinity;
      let maxLon = -Infinity;
      for (const n of nodes) {
        if (n.lat < minLat) minLat = n.lat;
        if (n.lat > maxLat) maxLat = n.lat;
        if (n.lon < minLon) minLon = n.lon;
        if (n.lon > maxLon) maxLon = n.lon;
      }
      return {
        centerLat: (minLat + maxLat) / 2,
        centerLon: (minLon + maxLon) / 2,
      };
    }
    return {
      centerLat: 28.613917,
      centerLon: 77.208976,
    };
  }, [nodes]);

  // Key to stabilize satellite fetches against micro-jitter (4 decimals = ~11 m)
  const satKey = `${centerLat.toFixed(4)},${centerLon.toFixed(4)}`;
  const lastSatKeyRef = useRef<string>('');
  const fetchingSatRef = useRef<boolean>(false);

  // Props the animation loop and event handlers read without re-initialising.
  const liveRef = useRef({ nodes, links, day, exaggeration, showLinks, satellite, selectedAddr, onSelect });
  liveRef.current = { nodes, links, day, exaggeration, showLinks, satellite, selectedAddr, onSelect };

  // --------------------------------------------------------------- init
  useEffect(() => {
    const host = hostRef.current;
    if (!host || stateRef.current) return;

    const extent = panelExtent();
    const widthM = extent.xMax - extent.xMin;
    const depthM = extent.yMax - extent.yMin;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(host.clientWidth || 800, host.clientHeight || 500);
    renderer.setClearColor(0x0a0f16, 1);
    host.appendChild(renderer.domElement);
    renderer.domElement.style.outline = 'none';

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0a0f16, widthM * 1.4, widthM * 3.2);

    const camera = new THREE.PerspectiveCamera(
      45, (host.clientWidth || 800) / (host.clientHeight || 500), 1, widthM * 6);
    // Deliberately low and oblique. Relief reads from a grazing angle; from
    // overhead a subsidence bowl is almost indistinguishable from a flat plane.
    camera.position.set(widthM * 0.03, depthM * 0.42, depthM * 1.0);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = widthM * 0.25;
    controls.maxDistance = widthM * 2.2;
    // Stop the camera dropping below the ground plane.
    controls.maxPolarAngle = Math.PI * 0.49;
    controls.target.set(0, -40, 0);

    // Lighting chosen to reveal relief: a low key light rakes across the trough
    // so its flanks read as slope rather than as a flat colour wash.
    scene.add(new THREE.HemisphereLight(0x9ec5f4, 0x0a0f16, 1.05));
    const key = new THREE.DirectionalLight(0xffffff, 1.5);
    key.position.set(-widthM * 0.5, depthM * 0.9, depthM * 0.6);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x88aaff, 0.35);
    fill.position.set(widthM * 0.6, depthM * 0.4, -depthM * 0.5);
    scene.add(fill);

    // Undisturbed ground level, for reading trough depth against.
    const grid = new THREE.GridHelper(Math.max(widthM, depthM) * 1.05, 16, 0x2c3a4a, 0x1b232e);
    (grid.material as THREE.Material).opacity = 0.32;
    (grid.material as THREE.Material).transparent = true;
    scene.add(grid);

    const heatCanvas = document.createElement('canvas');
    heatCanvas.width = 300;
    heatCanvas.height = 240;

    const texCanvas = document.createElement('canvas');
    texCanvas.width = TEX_W;
    texCanvas.height = TEX_H;

    const texture = new THREE.CanvasTexture(texCanvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = renderer.capabilities.getMaxAnisotropy();

    const geometry = new THREE.PlaneGeometry(widthM, depthM, GRID_X - 1, GRID_Y - 1);
    const material = new THREE.MeshStandardMaterial({
      map: texture, roughness: 0.94, metalness: 0.02,
    });
    const terrain = new THREE.Mesh(geometry, material);
    // Local +z becomes world +y, so a vertex z of -depth sinks the ground.
    terrain.rotation.x = -Math.PI / 2;
    scene.add(terrain);

    const nodeGroup = new THREE.Group();
    const linkGroup = new THREE.Group();
    scene.add(nodeGroup, linkGroup);

    const state = {
      renderer, scene, camera, controls, terrain, heatCanvas, texCanvas, texture,
      satCanvas: null as HTMLCanvasElement | null, nodeGroup, linkGroup,
      poles: new Map(), raycaster: new THREE.Raycaster(), pointer: new THREE.Vector2(),
      frame: 0,
    };
    stateRef.current = state;

    const onResize = () => {
      const w = host.clientWidth;
      const h = host.clientHeight;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(host);

    const onClick = (ev: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      state.pointer.set(
        ((ev.clientX - rect.left) / rect.width) * 2 - 1,
        -((ev.clientY - rect.top) / rect.height) * 2 + 1,
      );
      state.raycaster.setFromCamera(state.pointer, camera);
      const hits = state.raycaster.intersectObjects(nodeGroup.children, true);
      const addr = hits[0]?.object.userData?.addr;
      if (typeof addr === 'number') liveRef.current.onSelect(addr);
    };
    renderer.domElement.addEventListener('click', onClick);

    const home = camera.position.clone();
    onReady?.({
      resetView: () => {
        camera.position.copy(home);
        controls.target.set(0, -40, 0);
        controls.update();
      },
    });

    const loop = () => {
      state.frame = requestAnimationFrame(loop);
      controls.update();
      renderer.render(scene, camera);
    };
    loop();

    return () => {
      cancelAnimationFrame(state.frame);
      renderer.domElement.removeEventListener('click', onClick);
      ro.disconnect();
      controls.dispose();
      geometry.dispose();
      material.dispose();
      texture.dispose();
      renderer.dispose();
      host.removeChild(renderer.domElement);
      stateRef.current = null;
    };
  }, []);

  // ------------------------------------------------- terrain & overlays
  useEffect(() => {
    const st = stateRef.current;
    if (!st) return;
    const extent = panelExtent();
    const widthM = extent.xMax - extent.xMin;
    const depthM = extent.yMax - extent.yMin;
    const centerPanelX = (extent.xMin + extent.xMax) / 2;
    const centerPanelY = (extent.yMin + extent.yMax) / 2;

    // --- dynamic satellite imagery draping ------------------------------
    if (satellite && satKey !== lastSatKeyRef.current && !fetchingSatRef.current) {
      fetchingSatRef.current = true;
      const latSpan = (depthM / EARTH_RADIUS_M) * (180 / Math.PI);
      const lonSpan = (widthM / (EARTH_RADIUS_M * Math.cos((centerLat * Math.PI) / 180))) * (180 / Math.PI);
      const satBounds = {
        north: centerLat + latSpan / 2,
        south: centerLat - latSpan / 2,
        east: centerLon + lonSpan / 2,
        west: centerLon - lonSpan / 2,
      };

      stitchSatellite(satBounds)
        .then((canvas) => {
          fetchingSatRef.current = false;
          if (canvas && stateRef.current) {
            stateRef.current.satCanvas = canvas;
            lastSatKeyRef.current = satKey;
            // Update texture immediately with newly fetched satellite imagery
            const currSt = stateRef.current;
            const ctx = currSt.texCanvas.getContext('2d');
            if (ctx) {
              ctx.clearRect(0, 0, TEX_W, TEX_H);
              ctx.drawImage(canvas, 0, 0, TEX_W, TEX_H);
              ctx.globalAlpha = 0.82;
              ctx.drawImage(currSt.heatCanvas, 0, 0, TEX_W, TEX_H);
              ctx.globalAlpha = 1;
              currSt.texture.needsUpdate = true;
            }
          }
        })
        .catch(() => {
          fetchingSatRef.current = false;
        });
    }

    // --- displace the surface -------------------------------------------
    const heights = subsidenceGrid(day, GRID_X, GRID_Y, extent);
    const pos = st.terrain.geometry.attributes.position as THREE.BufferAttribute;
    for (let v = 0; v < pos.count; v++) {
      const lx = pos.getX(v);
      const ly = pos.getY(v);
      const i = Math.round(((lx + widthM / 2) / widthM) * (GRID_X - 1));
      const j = Math.round(((depthM / 2 - ly) / depthM) * (GRID_Y - 1));
      const mm = heights[Math.min(GRID_Y - 1, Math.max(0, j)) * GRID_X
        + Math.min(GRID_X - 1, Math.max(0, i))];
      pos.setZ(v, (-mm / 1000) * exaggeration);
    }
    pos.needsUpdate = true;
    st.terrain.geometry.computeVertexNormals();

    // --- heat mapping: map nodes to panel coordinates matching 3D space --
    const heatNodes = nodes.map((n) => {
      const dx = (n.lon - centerLon) * (Math.PI / 180) * EARTH_RADIUS_M * Math.cos((centerLat * Math.PI) / 180);
      const dy = (n.lat - centerLat) * (Math.PI / 180) * EARTH_RADIUS_M;
      return {
        ...n,
        x: centerPanelX + dx,
        y: centerPanelY + dy,
      };
    });

    // --- texture: imagery with the risk field over it --------------------
    const ctx = st.texCanvas.getContext('2d');
    if (ctx) {
      ctx.clearRect(0, 0, TEX_W, TEX_H);
      if (satellite && st.satCanvas) {
        ctx.drawImage(st.satCanvas, 0, 0, TEX_W, TEX_H);
      } else {
        ctx.fillStyle = '#1d2630';
        ctx.fillRect(0, 0, TEX_W, TEX_H);
      }
      renderHeat(st.heatCanvas, heatNodes, extent);
      ctx.globalAlpha = 0.82;
      ctx.drawImage(st.heatCanvas, 0, 0, TEX_W, TEX_H);
      ctx.globalAlpha = 1;
      st.texture.needsUpdate = true;
    }

    // --- node poles standing on the deformed ground ----------------------
    const live = new Set<number>();
    for (const n of nodes) {
      live.add(n.addr);
      // Metric displacement in meters from the terrain centroid
      const dx = (n.lon - centerLon) * (Math.PI / 180) * EARTH_RADIUS_M * Math.cos((centerLat * Math.PI) / 180);
      const dy = (n.lat - centerLat) * (Math.PI / 180) * EARTH_RADIUS_M;
      const wx = dx;
      // Local +y maps to world -z, so north sits at negative z
      const wz = -dy;

      const panelX = centerPanelX + dx;
      const panelY = centerPanelY + dy;
      const groundM = (-subsidenceAt(panelX, panelY, day) / 1000) * exaggeration;
      const colour = n.online ? RISK_HEX[n.risk] : 0x4b5563;

      let entry = st.poles.get(n.addr);
      if (!entry) {
        const pole = new THREE.Mesh(
          new THREE.CylinderGeometry(1.6, 1.6, POLE_M, 6),
          new THREE.MeshStandardMaterial({ color: colour, roughness: 0.6 }),
        );
        const head = new THREE.Mesh(
          new THREE.SphereGeometry(7, 18, 14),
          new THREE.MeshStandardMaterial({
            color: colour, emissive: colour, emissiveIntensity: 0.85, roughness: 0.28,
          }),
        );
        pole.userData.addr = n.addr;
        head.userData.addr = n.addr;

        const label = document.createElement('canvas');
        label.width = 128;
        label.height = 64;
        const lctx = label.getContext('2d')!;
        lctx.fillStyle = '#e8eef5';
        lctx.font = 'bold 44px system-ui, sans-serif';
        lctx.textAlign = 'center';
        lctx.textBaseline = 'middle';
        lctx.fillText(n.id, 64, 32);
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
          map: new THREE.CanvasTexture(label), depthTest: false, transparent: true,
        }));
        sprite.scale.set(58, 29, 1);

        st.nodeGroup.add(pole, head, sprite);
        entry = { pole, head, sprite };
        st.poles.set(n.addr, entry);
      }

      entry.pole.position.set(wx, groundM + POLE_M / 2, wz);
      entry.head.position.set(wx, groundM + POLE_M, wz);
      entry.sprite.position.set(wx, groundM + POLE_M + 26, wz);

      const selected = n.addr === selectedAddr;
      for (const mesh of [entry.pole, entry.head]) {
        const mat = mesh.material as THREE.MeshStandardMaterial;
        mat.color.setHex(colour);
        if ('emissive' in mat) {
          mat.emissive.setHex(selected ? 0xffffff : colour);
          mat.emissiveIntensity = selected ? 1.3 : 0.85;
        }
        mat.opacity = n.online ? 1 : 0.4;
        mat.transparent = !n.online;
      }
      entry.head.scale.setScalar(selected ? 1.45 : 1);
    }
    // Drop poles for nodes that no longer exist.
    for (const [addr, entry] of st.poles) {
      if (live.has(addr)) continue;
      st.nodeGroup.remove(entry.pole, entry.head, entry.sprite);
      st.poles.delete(addr);
    }

    // --- mesh links, drawn between pole heads ----------------------------
    st.linkGroup.clear();
    if (showLinks) {
      const byAddr = new Map(nodes.map((n) => [n.addr, n]));
      const routePts: number[] = [];
      const idlePts: number[] = [];
      for (const l of links) {
        const a = byAddr.get(l.a);
        const b = byAddr.get(l.b);
        if (!a || !b) continue;
        const target = l.onRoute ? routePts : idlePts;
        for (const n of [a, b]) {
          const dx = (n.lon - centerLon) * (Math.PI / 180) * EARTH_RADIUS_M * Math.cos((centerLat * Math.PI) / 180);
          const dy = (n.lat - centerLat) * (Math.PI / 180) * EARTH_RADIUS_M;
          const panelX = centerPanelX + dx;
          const panelY = centerPanelY + dy;
          const g = (-subsidenceAt(panelX, panelY, day) / 1000) * exaggeration;
          target.push(
            dx,
            g + POLE_M,
            -dy,
          );
        }
      }

      // Gateway uplink line, mirroring 2D Leaflet map
      const isShifted = nodes.length > 0 && Math.abs(nodes[0].lat - 23.75) > 1.0;
      const gwLon = isShifted && nodes.length > 0
        ? Math.min(...nodes.map((n) => n.lon)) - 0.0015
        : GATEWAY_LATLON.lon;
      const gwLat = isShifted && nodes.length > 0
        ? Math.min(...nodes.map((n) => n.lat))
        : GATEWAY_LATLON.lat;

      const dxGw = (gwLon - centerLon) * (Math.PI / 180) * EARTH_RADIUS_M * Math.cos((centerLat * Math.PI) / 180);
      const dyGw = (gwLat - centerLat) * (Math.PI / 180) * EARTH_RADIUS_M;
      const panelXGw = centerPanelX + dxGw;
      const panelYGw = centerPanelY + dyGw;
      const gGw = (-subsidenceAt(panelXGw, panelYGw, day) / 1000) * exaggeration;

      for (const n of nodes.filter((x) => x.online && x.hops === 1)) {
        const dx = (n.lon - centerLon) * (Math.PI / 180) * EARTH_RADIUS_M * Math.cos((centerLat * Math.PI) / 180);
        const dy = (n.lat - centerLat) * (Math.PI / 180) * EARTH_RADIUS_M;
        const panelX = centerPanelX + dx;
        const panelY = centerPanelY + dy;
        const g = (-subsidenceAt(panelX, panelY, day) / 1000) * exaggeration;
        routePts.push(
          dx, g + POLE_M, -dy,
          dxGw, gGw + POLE_M * 0.5, -dyGw,
        );
      }

      for (const [pts, opacity, width] of [
        [idlePts, 0.22, 1], [routePts, 0.8, 1],
      ] as [number[], number, number][]) {
        if (!pts.length) continue;
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
        st.linkGroup.add(new THREE.LineSegments(
          g,
          new THREE.LineBasicMaterial({
            color: 0xffffff, transparent: true, opacity, linewidth: width,
          }),
        ));
      }
    }
  }, [nodes, links, day, exaggeration, showLinks, satellite, selectedAddr, centerLat, centerLon, satKey]);

  return <div ref={hostRef} className="absolute inset-0 cursor-grab active:cursor-grabbing" />;
}
