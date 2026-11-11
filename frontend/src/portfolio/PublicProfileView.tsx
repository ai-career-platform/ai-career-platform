import type { PublicProfile } from '../api/publicPortfolio';

const period = (p?: { start: string | null; end: string | null }) => (p ? `${p.start ?? '?'} ~ ${p.end ?? '현재'}` : null);

/** 공개 화면과 미리보기가 **같은 컴포넌트**로 그립니다 — 미리보기 = 실제로 보이는 모습(T128 PP-INV-7). */
export function PublicProfileView({ profile, headingLevel = 2 }: { profile: PublicProfile; headingLevel?: 2 | 3 }) {
  const H = headingLevel === 2 ? 'h2' : 'h3';
  const empty = Object.keys(profile).filter((k) => k !== 'shared_until').length === 0;
  if (empty) return <p className="portfolio-muted">공개하는 항목이 없습니다(비공개).</p>;
  return (
    <article className="portfolio-view">
      {profile.display_name && <H className="portfolio-name">{profile.display_name}</H>}
      {profile.headline && <p className="portfolio-headline">{profile.headline}</p>}
      {profile.location_text && <p className="portfolio-muted">{profile.location_text}</p>}
      {profile.bio && <p>{profile.bio}</p>}
      {profile.experiences && profile.experiences.length > 0 && (
        <section aria-label="경력">
          <H className="portfolio-sub">경력</H>
          <ul>
            {profile.experiences.map((e, i) => (
              <li key={i}>
                {[e.organization, e.title].filter(Boolean).join(' · ')}
                {e.period && <span className="portfolio-muted"> ({period(e.period)})</span>}
                {e.description && <p className="portfolio-muted">{e.description}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {profile.projects && profile.projects.length > 0 && (
        <section aria-label="프로젝트">
          <H className="portfolio-sub">프로젝트</H>
          <ul>
            {profile.projects.map((p, i) => (
              <li key={i}>{p.title}{p.period && <span className="portfolio-muted"> ({period(p.period)})</span>}
                {p.summary && <p className="portfolio-muted">{p.summary}</p>}</li>
            ))}
          </ul>
        </section>
      )}
      {profile.skills && profile.skills.length > 0 && (
        <section aria-label="보유 기술">
          <H className="portfolio-sub">보유 기술</H>
          <ul className="portfolio-tags">{profile.skills.map((s) => <li key={s.name}>{s.name}{s.proficiency ? ` · ${s.proficiency}/5` : ''}</li>)}</ul>
        </section>
      )}
      {profile.target_roles && profile.target_roles.length > 0 && (
        <section aria-label="희망 직무">
          <H className="portfolio-sub">희망 직무</H>
          <ul className="portfolio-tags">{profile.target_roles.map((r) => <li key={r}>{r}</li>)}</ul>
        </section>
      )}
    </article>
  );
}
