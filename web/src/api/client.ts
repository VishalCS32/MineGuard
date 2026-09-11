import { ApiConfig, ApiError } from './types';

const ENV_API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://mineguard-api.tenant.eu.org';
const ENV_WS_BASE = import.meta.env.VITE_WS_BASE_URL || 'wss://mineguard-api.tenant.eu.org';
const ENV_DEFAULT_NODE_ID = import.meta.env.VITE_DEFAULT_NODE_ID || 'NODE-001';

export class ApiClient {
  private config: ApiConfig;

  constructor(customConfig?: Partial<ApiConfig>) {
    this.config = {
      baseUrl: customConfig?.baseUrl ?? ENV_API_BASE,
      wsUrl: customConfig?.wsUrl ?? ENV_WS_BASE,
      defaultNodeId: customConfig?.defaultNodeId ?? ENV_DEFAULT_NODE_ID,
      timeoutMs: customConfig?.timeoutMs ?? 8000,
      maxRetries: customConfig?.maxRetries ?? 2,
    };
  }

  get baseUrl(): string {
    return this.config.baseUrl;
  }

  get wsUrl(): string {
    return this.config.wsUrl;
  }

  get defaultNodeId(): string {
    return this.config.defaultNodeId;
  }

  updateConfig(newConfig: Partial<ApiConfig>): void {
    this.config = { ...this.config, ...newConfig };
  }

  /**
   * Type-safe fetch with timeout, automatic retries with exponential backoff,
   * and uniform ApiError handling.
   */
  async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = endpoint.startsWith('http')
      ? endpoint
      : `${this.config.baseUrl.replace(/\/$/, '')}/${endpoint.replace(/^\//, '')}`;

    let attempt = 0;
    let lastError: unknown;

    while (attempt <= this.config.maxRetries) {
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), this.config.timeoutMs);

      try {
        const res = await fetch(url, {
          credentials: 'include',
          ...options,
          signal: controller.signal,
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            ...(options.headers || {}),
          },
        });

        window.clearTimeout(timeoutId);

        if (!res.ok) {
          const errorBody = await res.text().catch(() => '');
          throw new ApiError(
            `HTTP ${res.status}: ${res.statusText || 'Request failed'}${errorBody ? ` - ${errorBody}` : ''}`,
            res.status,
            endpoint,
          );
        }

        const data = (await res.json()) as T;
        return data;
      } catch (err: unknown) {
        window.clearTimeout(timeoutId);
        lastError = err;

        if (err instanceof ApiError && err.statusCode && err.statusCode >= 400 && err.statusCode < 500) {
          // Do not retry 4xx client errors
          throw err;
        }

        attempt++;
        if (attempt <= this.config.maxRetries) {
          const backoff = Math.min(2000, 300 * Math.pow(2, attempt));
          await new Promise((r) => setTimeout(r, backoff));
        }
      }
    }

    if (lastError instanceof ApiError) {
      throw lastError;
    }

    const message = lastError instanceof Error ? lastError.message : 'Network request failed';
    throw new ApiError(message, undefined, endpoint, lastError);
  }
}

export const apiClient = new ApiClient();
