/**
 * Fetches and stitches Esri World Imagery tiles into a single canvas, cropped to
 * the field extent, for use as the 3-D terrain texture.
 *
 * Leaflet handles this for the 2-D view; the 3-D view needs the imagery as one
 * bitmap it can drape over the deformed mesh, so we assemble it ourselves. If the
 * network is unavailable the caller gets null and falls back to a plain shaded
 * surface -- the demo must survive a room with no wifi.
 */

const TILE_SIZE = 256;
const URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile';

const lonToTileX = (lon: number, z: number) => ((lon + 180) / 360) * 2 ** z;

const latToTileY = (lat: number, z: number) => {
  const rad = (lat * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * 2 ** z;
};

function loadImage(src: string, timeoutMs = 6000): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    const timer = setTimeout(() => resolve(null), timeoutMs);
    img.onload = () => { clearTimeout(timer); resolve(img); };
    img.onerror = () => { clearTimeout(timer); resolve(null); };
    img.src = src;
  });
}

export interface LatLonBounds {
  north: number;
  south: number;
  east: number;
  west: number;
}

/**
 * Returns a canvas covering exactly `bounds`, or null if no tile could be
 * fetched. `zoom` is chosen so the result is roughly 1024 px across.
 */
export async function stitchSatellite(
  bounds: LatLonBounds, zoom = 16,
): Promise<HTMLCanvasElement | null> {
  const xMinF = lonToTileX(bounds.west, zoom);
  const xMaxF = lonToTileX(bounds.east, zoom);
  const yMinF = latToTileY(bounds.north, zoom);   // north is the smaller y
  const yMaxF = latToTileY(bounds.south, zoom);

  const x0 = Math.floor(xMinF);
  const x1 = Math.floor(xMaxF);
  const y0 = Math.floor(yMinF);
  const y1 = Math.floor(yMaxF);

  const cols = x1 - x0 + 1;
  const rows = y1 - y0 + 1;
  if (cols > 12 || rows > 12) return null;   // refuse an unreasonable fetch

  const sheet = document.createElement('canvas');
  sheet.width = cols * TILE_SIZE;
  sheet.height = rows * TILE_SIZE;
  const sctx = sheet.getContext('2d');
  if (!sctx) return null;

  const jobs: Promise<void>[] = [];
  let loaded = 0;
  for (let ty = y0; ty <= y1; ty++) {
    for (let tx = x0; tx <= x1; tx++) {
      jobs.push(
        loadImage(`${URL}/${zoom}/${ty}/${tx}`).then((img) => {
          if (!img) return;
          loaded += 1;
          sctx.drawImage(img, (tx - x0) * TILE_SIZE, (ty - y0) * TILE_SIZE);
        }),
      );
    }
  }
  await Promise.all(jobs);
  if (loaded === 0) return null;

  // Crop the stitched sheet to the exact extent.
  const sx = (xMinF - x0) * TILE_SIZE;
  const sy = (yMinF - y0) * TILE_SIZE;
  const sw = (xMaxF - xMinF) * TILE_SIZE;
  const sh = (yMaxF - yMinF) * TILE_SIZE;

  const out = document.createElement('canvas');
  out.width = Math.max(2, Math.round(sw));
  out.height = Math.max(2, Math.round(sh));
  const octx = out.getContext('2d');
  if (!octx) return null;
  octx.drawImage(sheet, sx, sy, sw, sh, 0, 0, out.width, out.height);
  return out;
}
