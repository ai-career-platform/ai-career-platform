import { describe, expect, it } from 'vitest';
import { ApiError, displayRequestId } from './errors';

describe('displayRequestId (E2E-006 D-2)', () => {
  const withId = (requestId?: string) => new ApiError(500, '/v1/x', undefined, 'INTERNAL_ERROR', undefined, requestId);

  it('returns the response X-Request-ID as-is when it has the backend-safe format', () => {
    expect(displayRequestId(withId('req-0123456789abcdef'))).toBe('req-0123456789abcdef');
    expect(displayRequestId(withId('nginx.Trace_ID-12345678'))).toBe('nginx.Trace_ID-12345678');
  });

  it('never invents an id: missing, unsafe or non-ApiError errors give undefined', () => {
    expect(displayRequestId(withId(undefined))).toBeUndefined();
    expect(displayRequestId(withId(''))).toBeUndefined();
    expect(displayRequestId(withId('short'))).toBeUndefined();                       // < 8
    expect(displayRequestId(withId('x'.repeat(65)))).toBeUndefined();               // > 64
    expect(displayRequestId(withId('<script>alert(1)</script>'))).toBeUndefined();
    expect(displayRequestId(withId('req 0123456789'))).toBeUndefined();
    expect(displayRequestId(new Error('req-0123456789abcdef'))).toBeUndefined();
    expect(displayRequestId(undefined)).toBeUndefined();
  });
});
