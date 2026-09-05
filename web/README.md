# MineGuard — web dashboard

React 18 + Vite + TypeScript + Tailwind + Framer Motion, with MapLibre GL for the
GIS layer. Dark, single-mode by design.

```bash
npm install
npm run dev        # http://localhost:5173
npm run build
npm run typecheck
```

## Where the data comes from

Today the dashboard runs against `src/sim/`, a browser port of the same
influence-function subsidence model used by `ml/simulator` and the backend. Every
number on screen is derived rather than invented: tilt is the gradient of the
subsidence surface, crack width follows tensile strain, hop counts come from a
shortest-path solve over the radio graph, and alerts fire from threshold
crossings on those values.

`DataSource` in `src/sim/feed.ts` is the seam. When the FastAPI backend is up, a
`LiveSocketSource` implements the same interface against the WebSocket and no
component changes. The simulator then stays on as the offline demo path.

The clock is compressed but internally consistent: one tick is fifteen simulated
minutes delivered every 250 ms, and chart timestamps are simulated time — so the
1H / 6H / 24H / 7D range tabs mean exactly what they say.

## Interactions worth knowing

- **Click a node** — drives the trend chart and the gauges.
- **Shift-click a node** — cuts its power. Watch hop counts change and the field
  re-route around it; this is the mesh self-healing demo.
- **Layers button** — toggles the satellite basemap.

## Visualisation rules this follows

- **No dual-axis charts.** Tilt (°), vibration (mg) and crack width (mm) are three
  scales, so the trend panel is small multiples on a shared time axis. Aligning
  two y-scales on one plot invents a correlation the data does not contain.
- **Risk uses the reserved status palette**, never a rainbow ramp, and every band
  carries a label, an icon and a contour stroke — the warning and serious steps
  sit closer together than the normal-vision separation floor, so hue alone must
  never be the thing distinguishing them.
- **The heat overlay stops where the evidence does.** Inverse-distance weighting
  will happily extrapolate a confident value across ground no node can see, so
  confidence decays with distance to the nearest node.
- Series colours were validated against this dark surface rather than eyeballed.
