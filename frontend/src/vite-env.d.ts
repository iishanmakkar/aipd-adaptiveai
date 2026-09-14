/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_NIM_VLM_URL: string;
  readonly VITE_NIM_VLM_MODEL: string;
  readonly VITE_NIM_API_KEY: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
