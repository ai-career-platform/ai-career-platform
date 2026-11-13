/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { normalizeBasePath } from './src/config/basePath.ts';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const proxyTarget = env.DEV_API_PROXY_TARGET || 'http://127.0.0.1:18080';
  // 앱이 놓이는 URL 경로. 기본 '/'(로컬·테스트). Staging 이미지는 공유 Origin의 /career/ 아래에서 서비스되므로
  // VITE_BASE_PATH=/career/ 로 빌드합니다(poc/staging/frontend/Dockerfile.integrated, docs/ops/STAGING_CAREER_BASEPATH.md).
  const basePath = normalizeBasePath(env.VITE_BASE_PATH);

  return {
    base: basePath,
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      // 브라우저는 같은 Origin의 /api 만 호출 → CORS 불필요.
      // 로컬 PoC Nginx(18080)가 /api 접두어를 제거해 FastAPI로 전달합니다.
      proxy: {
        '/api': { target: proxyTarget, changeOrigin: true },
      },
    },
    preview: { host: '127.0.0.1', port: 4173, strictPort: true },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: false,
    },
  };
});
