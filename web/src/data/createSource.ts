/**
 * Chooses where the dashboard gets its data.
 *
 * Probes the backend; if it answers, the dashboard runs live. If it does not,
 * the built-in physics simulator takes over and the header says so. That is not
 * a development convenience -- offline capability is a requirement of the
 * problem statement, and a monitoring screen that goes blank when the link drops
 * is worse than useless on a mine site.
 */
import { SimulatedSource } from '@/sim/feed';
import { LiveSource } from './liveSource';
import type { DataSource } from './source';

const PROBE_TIMEOUT_MS = 2500;

export async function createSource(baseUrl = ''): Promise<DataSource> {
  if (await backendAlive(baseUrl)) return new LiveSource(baseUrl);
  return new SimulatedSource();
}

async function backendAlive(baseUrl: string): Promise<boolean> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const res = await fetch(`${baseUrl}/api/health`, { signal: controller.signal });
    if (!res.ok) return false;
    const body = (await res.json()) as { status?: string };
    return body.status === 'ok';
  } catch {
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}
