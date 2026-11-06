// VITE_* 값은 빌드 시 브라우저 번들에 포함됩니다. 비밀정보(API Key, 비밀번호)를 넣지 않습니다.
export const env = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api',
  useMock: import.meta.env.VITE_API_MOCK === 'true',
} as const;
