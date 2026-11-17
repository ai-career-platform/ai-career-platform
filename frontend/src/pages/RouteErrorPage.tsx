import { Link, useRouteError } from 'react-router';
import { displayRequestId } from '../api/errors';
import { StatePanel } from '../components/StatePanel';

/**
 * 라우트 렌더링 중 예기치 않은 오류가 났을 때의 화면(E2E-006 D-1).
 * React Router 기본 오류 화면 대신 일반 안내만 보여 주고, 오류 메시지·스택트레이스는 화면에 넣지 않습니다.
 * 인증·레이아웃 Context 없이도 그려지므로 루트 경계와 레이아웃 안쪽 경계에서 함께 씁니다.
 */
export function RouteErrorPage() {
  const error = useRouteError();
  return (
    <section className="route-error" aria-labelledby="route-error-title">
      <h1 id="route-error-title" className="sr-only">화면 오류</h1>
      <StatePanel variant="error" title="화면을 표시하지 못했습니다"
        description="일시적인 문제일 수 있습니다. 다시 시도하거나 홈으로 이동해 주세요."
        actionLabel="다시 시도" onAction={() => window.location.reload()} requestId={displayRequestId(error)} />
      <p><Link to="/">홈으로 이동</Link></p>
    </section>
  );
}
