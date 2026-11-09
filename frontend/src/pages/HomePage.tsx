import { useEffect, useState } from 'react';
import { useApi } from '../api/ApiContext';
import { env } from '../config/env';

type Status =
  | { state: 'loading' }
  | { state: 'ready'; backend: boolean; database: boolean; version: string | null };

/**
 * 골격 확인용 홈 화면: PoC와 동일하게 Backend 3개 헬스 API 연결 상태를 표시합니다.
 * 실제 서비스 홈 화면은 기능 일감(T20~T24)에서 교체합니다.
 */
export function HomePage() {
  const { system } = useApi();
  const [status, setStatus] = useState<Status>({ state: 'loading' });

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([system.health(), system.version(), system.dbHealth()]).then(([health, version, db]) => {
      if (cancelled) return;
      setStatus({
        state: 'ready',
        backend: health.status === 'fulfilled' && health.value.status === 'ok',
        database: db.status === 'fulfilled' && db.value.status === 'ok',
        version: version.status === 'fulfilled' ? version.value.version : null,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [system]);

  const operational = status.state === 'ready' && status.backend && status.database;

  return (
    <section aria-labelledby="home-title">
      <h1 id="home-title">AI Career Platform</h1>
      <p>Frontend 기본 구조(T19){env.mockEnabled ? ' — Mock API 모드' : ''}</p>
      <dl aria-label="시스템 상태" aria-busy={status.state === 'loading'}>
        <dt>Backend connection</dt>
        <dd data-testid="backend-status">
          {status.state === 'loading' ? 'Checking...' : status.backend ? 'Connected' : 'Unavailable'}
        </dd>
        <dt>Backend version</dt>
        <dd data-testid="backend-version">
          {status.state === 'loading' ? 'Checking...' : (status.version ?? 'Unknown')}
        </dd>
        <dt>System status</dt>
        <dd data-testid="system-status">
          {status.state === 'loading' ? 'Checking...' : operational ? 'Operational' : 'Degraded'}
        </dd>
      </dl>
    </section>
  );
}
