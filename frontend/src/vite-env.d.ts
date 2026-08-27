/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_NIM_VLM_URL: string;
  readonly VITE_NIM_VLM_MODEL: string;
  readonly VITE_NIM_API_KEY: string;
  readonly VITE_USE_MOCK: string;
  readonly VITE_MOCK_API_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}