# MineGuard — web dashboard

React 18 + Vite + TypeScript + Tailwind + Framer Motion. Leaflet for the 2-D map,
Three.js for the 3-D terrain. Dark, single-mode by design.

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

## The two map views

Leaflet has no camera pitch — it is a 2-D renderer with no third axis — so the two
views are two renderers over one surface model (`src/sim/surface.ts`):

- **2-D (Leaflet)** — the plan view. Esri satellite tiles, node markers, animated
  mesh links, and the interpolated risk field as an image overlay. Answers *which
  node, which zone*.
- **3-D (Three.js)** — the same ground as real geometry. The subsidence trough is
  a displaced mesh with the satellite imagery and risk field draped over it, and
  the nodes stand on poles rooted in the deformed surface. Answers *what shape,
  how deep, where is it steepest* — and the flanks you can see are exactly where
  tilt and strain peak.

Vertical exaggeration defaults to 50x and is stated on screen. A 1.9 m trough
spread over 800 m of surface is a barely perceptible dish at true scale;
exaggeration is standard practice in subsidence visualisation, and labelling the
factor stops it being read as real depth. `True` shows the honest 1x geometry.

The 3-D terrain re-tessellates every frame because the surface sampler is
separable: `S(x,y) = A*Fx(x)*Fy(y) + D*Gx(x)*Gy(y)`, so a 140x110 grid costs 250
profile evaluations instead of 15,400.

## Interactions worth knowing

- **Click a node** — drives the trend chart and the gauges.
- **Shift-click a node** — cuts its power. Watch hop counts change and the field
  re-route around it; this is the mesh self-healing demo.
- **2D / 3D** — switches renderer. Both read the same live data.
- **Drag / scroll in 3D** — orbit and zoom. The camera sits low on purpose;
  from overhead a subsidence bowl is nearly indistinguishable from a flat plane.
- **Layers button** — toggles the satellite basemap in either view.

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
- **Colours were computed, not eyeballed.** Vibrance means maximum chroma at a
  fixed lightness, not raising lightness — the first attempt at "more vibrant"
  failed the lightness band precisely because it went lighter instead of more
  chromatic. Every palette is checked with the validator against this surface:

  | Palette | Worst adjacent CVD | Worst adjacent normal-vision | Contrast |
  |---|---|---|---|
  | Series (charts) | 10.0 deutan / 13.3 tritan | 28.3 | all >= 3:1 |
  | Status (risk bands) | 13.1 protan / 8.9 tritan | 17.9 | all >= 3:1 |

  Targets are CVD >= 8 and normal-vision >= 15. The risk ramp needed its hue
  spread widened and its lightness staggered to clear the normal-vision floor:
  green -> amber -> orange -> red crowds at both warm joins, which is why the
  earlier, duller ramp sat at 13.6 and failed it.
