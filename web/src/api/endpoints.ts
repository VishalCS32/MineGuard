import { apiClient } from './client';
import type {
  AnomalyInjectResponse,
  BackendHealthResponse,
  BackendSnapshotResponse,
  RemoteTelemetryFrame,
} from './types';

export interface TelemetrySocketHandlers {
  onFrame: (frame: RemoteTelemetryFrame) => void;
  onOpen?: () => void;
  onClose?: (code: number, reason: string) => void;
  onError?: (error: Event) => void;
}

export const api = {
  /**
   * Check system health and connection status
   */
  async getHealth(): Promise<BackendHealthResponse> {
    try {
      return await apiClient.request<BackendHealthResponse>('/api/health');
    } catch {
      // Fallback for Node 1 live API that mounts /health at root
      return await apiClient.request<BackendHealthResponse>('/health');
    }
  },

  /**
   * Fetch the latest telemetry frame for a given node ID
   */
  async getNodeLatest(nodeId: string = apiClient.defaultNodeId): Promise<RemoteTelemetryFrame> {
    try {
      // Primary route exposed by Node 1 live API: /api/v1/nodes/{id}/latest
      return await apiClient.request<RemoteTelemetryFrame>(`/api/v1/nodes/${nodeId}/latest`);
    } catch {
      // Fallback route for backend simulator: /api/nodes/{id}/latest
      return await apiClient.request<RemoteTelemetryFrame>(`/api/nodes/${nodeId}/latest`);
    }
  },

  /**
   * Fetch list of all known nodes from the backend
   */
  async getNodes(): Promise<string[]> {
    try {
      const res = await apiClient.request<string[] | { addr: number; label?: string }[]>('/api/nodes');
      if (Array.isArray(res)) {
        if (typeof res[0] === 'string') {
          return res as string[];
        }
        return (res as { addr: number; label?: string }[]).map(
          (n) => n.label || `NODE-${String(n.addr).padStart(3, '0')}`,
        );
      }
      return [apiClient.defaultNodeId];
    } catch {
      return [apiClient.defaultNodeId];
    }
  },

  /**
   * Fetch snapshot of all nodes currently tracked
   */
  async getSnapshot(): Promise<BackendSnapshotResponse> {
    return await apiClient.request<BackendSnapshotResponse>('/api/snapshot');
  },

  /**
   * Fetch recent telemetry history frames for a node (oldest first)
   */
  async getNodeHistory(nodeId: string = apiClient.defaultNodeId, limit = 100): Promise<RemoteTelemetryFrame[]> {
    try {
      return await apiClient.request<RemoteTelemetryFrame[]>(`/api/nodes/${nodeId}/history?limit=${limit}`);
    } catch {
      // If history endpoint is not provided by backend, return empty array so client accumulates live stream
      return [];
    }
  },

  /**
   * Trigger an anomaly injection test on the simulator (if supported)
   */
  async injectAnomaly(nodeId: string = apiClient.defaultNodeId, ticks = 6): Promise<AnomalyInjectResponse> {
    return await apiClient.request<AnomalyInjectResponse>(`/api/nodes/${nodeId}/inject-anomaly?ticks=${ticks}`, {
      method: 'POST',
    });
  },

  /**
   * Establish real-time WebSocket connection
   */
  connectWebSocket(nodeId: string = apiClient.defaultNodeId, handlers: TelemetrySocketHandlers): () => void {
    const wsBase = apiClient.wsUrl.replace(/^http/, 'ws').replace(/\/$/, '');
    
    // Remote Node 1 API streams on /ws/{node_id} (e.g. /ws/NODE-001), simulator on /ws/live
    const primaryUrl = `${wsBase}/ws/${nodeId}`;
    const fallbackUrl = `${wsBase}/ws/live`;

    let socket: WebSocket | null = null;
    let isDisposed = false;

    const connect = (url: string, isRetry = false) => {
      if (isDisposed) return;

      try {
        socket = new WebSocket(url);
      } catch (err) {
        if (!isRetry) {
          connect(fallbackUrl, true);
        }
        return;
      }

      socket.onopen = () => {
        handlers.onOpen?.();
      };

      socket.onmessage = (ev) => {
        try {
          const raw = JSON.parse(ev.data as string);
          // Ignore ping frames
          if (raw && typeof raw === 'object' && raw.type === 'ping') return;

          // If frame matches RemoteTelemetryFrame contract
          if (raw && raw.orientation && raw.vibration) {
            handlers.onFrame(raw as RemoteTelemetryFrame);
          }
        } catch (err) {
          console.warn('[MineGuard WS] Parse error:', err);
        }
      };

      socket.onerror = (ev) => {
        handlers.onError?.(ev);
        if (!isRetry && !isDisposed) {
          try {
            socket?.close();
          } catch {}
          connect(fallbackUrl, true);
        }
      };

      socket.onclose = (ev) => {
        handlers.onClose?.(ev.code, ev.reason);
      };
    };

    connect(primaryUrl);

    return () => {
      isDisposed = true;
      if (socket) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;
        try {
          socket.close();
        } catch {}
        socket = null;
      }
    };
  },
};
