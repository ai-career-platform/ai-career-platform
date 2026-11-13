/**
 * 앱이 놓이는 URL 경로(Vite `base`)와 React Router `basename` 계산.
 * Vite 설정(Node)과 브라우저 코드가 같이 씁니다. 외부 의존성 없음.
 */

/** 빈 값은 '/', 그 외는 앞뒤 '/'를 붙인 형태('/career/')로 맞춥니다. 경로 문자 외 값은 거부합니다. */
export function normalizeBasePath(value: string | undefined): string {
  const trimmed = (value ?? '').trim().replace(/^\/+|\/+$/g, '');
  if (trimmed === '') return '/';
  const segments = trimmed.split('/');
  if (segments.some((s) => !/^[A-Za-z0-9._~-]+$/.test(s) || s === '.' || s === '..')) {
    throw new Error(`Invalid VITE_BASE_PATH: ${value}`);
  }
  return `/${trimmed}/`;
}

/** Vite `import.meta.env.BASE_URL`('/', '/career/') → Router basename(undefined, '/career') */
export function routerBasename(baseUrl: string): string | undefined {
  const base = normalizeBasePath(baseUrl);
  return base === '/' ? undefined : base.slice(0, -1);
}

/** API 기본 경로. VITE_API_BASE_URL 이 있으면 그 값, 없으면 앱 경로 아래 'api'('/api', '/career/api') */
export function defaultApiBaseUrl(explicit: string | undefined, baseUrl: string): string {
  if (explicit) return explicit;
  return `${normalizeBasePath(baseUrl)}api`;
}
