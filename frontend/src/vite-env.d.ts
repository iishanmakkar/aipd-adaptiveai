/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_NIM_VLM_URL: string;
  readonly VITE_NIM_VLM_MODEL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
