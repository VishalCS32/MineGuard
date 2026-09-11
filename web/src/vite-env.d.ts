/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_WS_BASE_URL?: string;
  readonly VITE_DEFAULT_NODE_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
