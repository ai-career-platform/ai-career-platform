import { Navigate, Outlet, useLocation } from 'react-router';
import { useAuth } from './useAuth';
import { ForbiddenPage } from '../pages/ForbiddenPage';

/** 로그인 필요 경로 가드. roles 를 주면 그 중 하나라도 있어야 하고, 없으면 403 화면을 보여줍니다. */
export function RequireAuth({ roles }: { roles?: string[] }) {
  const { state } = useAuth();
  const location = useLocation();

  if (state.status === 'loading') return <p role="status">로그인 상태를 확인하는 중…</p>;
  if (state.status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  if (roles && !roles.some((role) => state.user.roles.includes(role))) return <ForbiddenPage />;
  return <Outlet />;
}
