/**
 * 기업 초대 수락 (T124). 링크는 `/company-invitations/accept#token=…` — 토큰은 URL fragment 라 서버 접근 로그·Referer 에
 * 남지 않습니다(T112 F-1). 화면을 열면 주소창에서 바로 지우고(뒤로 가기·공유로 새지 않게), 사용자가 버튼을 눌러야 수락합니다.
 * 실패(만료·취소·다른 이메일·없는 링크)는 서버가 구분하지 않으므로 화면도 한 문구로 안내합니다.
 */
import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { ApiError } from '../api/errors';
import { ROLE_LABELS, type MyOrganization } from '../api/companyAccounts';
import { useCompanyService } from '../company/companyContext';
import { Button } from '../components/Button';
import './CompanyConsolePage.css';

export function CompanyInvitationAcceptPage() {
  const service = useCompanyService();
  const location = useLocation();
  const navigate = useNavigate();
  const [token] = useState(() => new URLSearchParams(location.hash.replace(/^#/, '')).get('token'));
  const [result, setResult] = useState<{ kind: 'ok'; joined: MyOrganization } | { kind: 'error'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (location.hash) navigate(location.pathname, { replace: true });
  }, [location.hash, location.pathname, navigate]);

  async function accept() {
    if (!token) return;
    setBusy(true);
    try {
      setResult({ kind: 'ok', joined: await service.accept(token) });
    } catch (error) {
      const text = error instanceof ApiError && error.status === 409 ? '이미 이 조직의 멤버입니다.'
        : error instanceof ApiError && (error.status === 0 || error.status === 503) ? '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'
          : '초대가 만료되었거나, 취소되었거나, 지금 로그인한 계정의 이메일로 보낸 초대가 아닙니다. 기업 관리자에게 다시 요청해 주세요.';
      setResult({ kind: 'error', text });
    } finally { setBusy(false); }
  }

  return (
    <section className="company-page" aria-labelledby="accept-title">
      <h1 id="accept-title">기업 초대 수락</h1>
      {!token && !result && <p className="company-error" role="alert">초대 링크가 올바르지 않습니다. 메일의 링크를 다시 열어 주세요.</p>}
      {token && !result && (
        <>
          <p>초대를 수락하면 이 조직의 콘솔과 공고 관리에 참여합니다. 초대받은 이메일로 로그인했는지 확인해 주세요.</p>
          <Button onClick={() => void accept()} disabled={busy}>초대 수락</Button>
        </>
      )}
      {result?.kind === 'ok' && (
        <p className="company-ok" role="status">
          {result.joined.organization.name}에 {ROLE_LABELS[result.joined.role]}(으)로 합류했습니다.{' '}
          <Link to={`/company?org=${result.joined.organization.organization_id}`}>기업 콘솔로 이동</Link>
        </p>
      )}
      {result?.kind === 'error' && <p className="company-error" role="alert">{result.text}</p>}
    </section>
  );
}
