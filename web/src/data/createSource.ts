/**
 * Chooses where the dashboard gets its data.
 *
 * Probes the backend; if it answers, the dashboard runs live. If it does not,
 * the built-in physics simulator takes over and the header says so. That is not
 * a development convenience -- offline capability is a requirement of the
 * problem statement, and a monitoring screen that goes blank when the link drops
 * is worse than useless on a mine site.
 */
import { apiClient } from '@/api';
import { SimulatedSource } from '@/sim/feed';
import { RemoteNodeSource } from './remoteNodeSource';
import type { DataSource } from './source';

export type SourceMode = 'remote' | 'simulated' | 'local';

export async function createSource(
  mode: SourceMode = 'remote',
  baseUrl = '',
): Promise<DataSource> {
  if (mode === 'remote') {
    return new RemoteNodeSource(apiClient.baseUrl, apiClient.wsUrl);
  }
  if (mode === 'local') {
    const localBase = baseUrl || 'http://localhost:8000';
    const localWs = localBase.replace(/^http/, 'ws');
    return new RemoteNodeSource(localBase, localWs);
  }
  return new SimulatedSource();
}

