import { Link } from 'react-router';

export function NotFoundPage() {
  return (
    <section aria-labelledby="not-found-title">
      <h1 id="not-found-title">페이지를 찾을 수 없습니다</h1>
      <p>요청한 주소가 없거나 아직 구현되지 않은 화면입니다.</p>
      <Link to="/">홈으로 이동</Link>
    </section>
  );
}
