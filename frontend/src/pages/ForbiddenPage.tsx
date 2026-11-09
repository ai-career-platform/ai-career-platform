import { Link } from 'react-router';

export function ForbiddenPage() {
  return (
    <section aria-labelledby="forbidden-title">
      <h1 id="forbidden-title">접근 권한이 없습니다</h1>
      <p>이 화면을 볼 수 있는 역할이 없습니다. 권한이 필요하다면 운영자에게 문의하세요.</p>
      <Link to="/">홈으로 이동</Link>
    </section>
  );
}
