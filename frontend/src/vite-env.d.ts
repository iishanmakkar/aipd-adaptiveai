/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Optional on purpose: every use site falls back (dev localhost, or the
  // same-origin default), so tsc must flag an unset var as possibly
  // undefined instead of typing it as always present.
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_NIM_VLM_URL?: string;
  readonly VITE_NIM_VLM_MODEL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
