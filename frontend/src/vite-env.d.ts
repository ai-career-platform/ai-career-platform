/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_API_MOCK?: string;
  readonly VITE_ADMIN_MODERATION_UI?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
