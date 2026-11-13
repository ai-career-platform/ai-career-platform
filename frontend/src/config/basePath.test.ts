import { describe, expect, it } from 'vitest';
import { defaultApiBaseUrl, normalizeBasePath, routerBasename } from './basePath';

describe('base path helpers', () => {
  it('normalizes the Vite base path', () => {
    expect(normalizeBasePath(undefined)).toBe('/');
    expect(normalizeBasePath('')).toBe('/');
    expect(normalizeBasePath('/')).toBe('/');
    expect(normalizeBasePath('career')).toBe('/career/');
    expect(normalizeBasePath('/career')).toBe('/career/');
    expect(normalizeBasePath('/career/')).toBe('/career/');
  });

  it('rejects values that are not a plain path', () => {
    for (const bad of ['https://evil.example/', '/ca reer/', '/career/../x', '/a//b/', '/x?y', '/./']) {
      expect(() => normalizeBasePath(bad)).toThrow('Invalid VITE_BASE_PATH');
    }
  });

  it('turns BASE_URL into a router basename (none at the root)', () => {
    expect(routerBasename('/')).toBeUndefined();
    expect(routerBasename('/career/')).toBe('/career');
  });

  it('derives the API base from the app path unless set explicitly', () => {
    expect(defaultApiBaseUrl(undefined, '/')).toBe('/api');
    expect(defaultApiBaseUrl(undefined, '/career/')).toBe('/career/api');
    expect(defaultApiBaseUrl('/career/api', '/career/')).toBe('/career/api');
    expect(defaultApiBaseUrl('/api', '/')).toBe('/api');
  });
});
