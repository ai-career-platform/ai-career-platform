import { useState } from 'react';
import { Button } from '../components/Button';
import { SectionHeading } from '../components/SectionHeading';
import { FilterChips } from '../components/FilterChips';
import { JobCard, type JobCardData } from '../components/JobCard';
import { CompanyCard } from '../components/CompanyCard';
import './LandingPage.css';

const categories = ['전체', '개발', '디자인', '기획', '데이터'] as const;

const jobs: JobCardData[] = [
  {
    id: '1',
    category: '개발',
    company: '노바랩',
    initial: 'N',
    title: '프론트엔드 개발자',
    detail: '서울 · 신입–3년',
    tags: ['React', 'TypeScript'],
    tone: 'blue',
  },
  {
    id: '2',
    category: '디자인',
    company: '스튜디오 모브',
    initial: 'M',
    title: '프로덕트 디자이너',
    detail: '서울 · 경력 2년 이상',
    tags: ['Figma', 'UX/UI'],
    tone: 'purple',
  },
  {
    id: '3',
    category: '데이터',
    company: '데이터포레스트',
    initial: 'D',
    title: '데이터 분석가',
    detail: '판교 · 신입–3년',
    tags: ['SQL', 'Python'],
    tone: 'green',
  },
  {
    id: '4',
    category: '기획',
    company: '넥스트웨이브',
    initial: 'W',
    title: '서비스 기획자',
    detail: '서울 · 경력 3년 이상',
    tags: ['서비스 기획', '협업'],
    tone: 'orange',
  },
];

const categoryOptions = categories.map((value) => ({ value, label: value }));

const shortcuts = [
  { number: '01', title: '채용공고', subtitle: '새로운 기회 찾기', href: '#positions' },
  { number: '02', title: '관심 기업', subtitle: '함께하고 싶은 팀', href: '#companies' },
  { number: '03', title: 'AI 커리어 분석', subtitle: '나의 다음 단계', href: '#career' },
  { number: '04', title: '역량 점검', subtitle: '목표와의 차이 확인', href: '#career' },
];

export function LandingPage() {
  const [category, setCategory] = useState<string>('전체');
  const [query, setQuery] = useState('');
  const [notice, setNotice] = useState('');

  const filteredJobs = jobs.filter((job) => {
    const matchesCategory = category === '전체' || job.category === category;
    const searchText = [job.title, job.company, ...job.tags]
      .join(' ')
      .toLowerCase();

    return matchesCategory && searchText.includes(query.trim().toLowerCase());
  });

  return (
    <div className="career-home">
      <section className="home-hero" aria-labelledby="home-title">
        <div className="home-hero-copy">
          <p className="home-eyebrow">YOUR NEXT CAREER</p>
          <h1 id="home-title">
            더 나다운 일,
            <br />
            여기서 시작하세요.
          </h1>
          <p className="home-hero-description">
            새로운 기회를 탐색하고,
            <br />
            AI와 함께 다음 커리어의 방향을 찾아보세요.
          </p>
          <a className="home-primary-link" href="#positions">
            포지션 둘러보기 <span aria-hidden="true">↗</span>
          </a>
        </div>

        <div className="home-hero-art" aria-hidden="true">
          <div className="hero-orbit" />
          <div className="hero-orbit hero-orbit-inner" />
          <div className="hero-center">NEXT</div>
          <span className="hero-pill hero-pill-one">새로운 가능성</span>
          <span className="hero-pill hero-pill-two">나만의 커리어</span>
          <span className="hero-spark">✦</span>
        </div>
      </section>

      <nav className="home-shortcuts" aria-label="메인 바로가기">
        {shortcuts.map((item) => (
          <a href={item.href} key={item.number} className="home-shortcut">
            <span className="shortcut-icon" aria-hidden="true">
              {item.number}
            </span>
            <span>
              <strong>{item.title}</strong>
              <small>{item.subtitle}</small>
            </span>
            <span className="shortcut-arrow" aria-hidden="true">↗</span>
          </a>
        ))}
      </nav>

      <section
        id="positions"
        className="home-section"
        aria-labelledby="positions-title"
      >
        <SectionHeading id="positions-title" title="지금 눈여겨볼 포지션"
          eyebrow="FIND YOUR OPPORTUNITY" aside="가상 공고 · 화면 예시" />

        <div className="home-search-row">
          <FilterChips label="직무 선택" options={categoryOptions}
            value={category} onChange={setCategory} />

          <div className="home-search">
            <label className="home-sr-only" htmlFor="job-search">
              직무, 기업, 기술 검색
            </label>
            <input
              id="job-search"
              type="search"
              placeholder="직무, 기업, 기술 검색"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
        </div>

        <p className="home-result-count" role="status">
          {filteredJobs.length}개의 예시 포지션
        </p>

        <div className="home-job-grid">
          {filteredJobs.map((job) => <JobCard key={job.id} job={job} />)}
        </div>

        {filteredJobs.length === 0 && (
          <div className="home-empty">
            <h3>조건에 맞는 예시 공고가 없어요.</h3>
            <p>다른 직무나 검색어로 찾아보세요.</p>
            <Button
              variant="outline"
              onClick={() => {
                setCategory('전체');
                setQuery('');
              }}
            >
              검색 조건 초기화
            </Button>
          </div>
        )}
      </section>

      <section
        id="career"
        className="home-career-banner"
        aria-labelledby="career-title"
      >
        <div>
          <p className="home-eyebrow">AI CAREER GUIDE</p>
          <h2 id="career-title">내 경험은 어떤 가능성으로 이어질까요?</h2>
          <p>보유 기술과 목표 직무를 연결해 다음 성장 방향을 살펴보세요.</p>
        </div>

        <Button
          onClick={() => setNotice('AI 커리어 분석은 현재 준비 중입니다.')}
        >
          AI 커리어 분석 안내 <span aria-hidden="true">↗</span>
        </Button>

        <p className="career-banner-notice" role="status">{notice}</p>
      </section>

      <section
        id="companies"
        className="home-section"
        aria-labelledby="companies-title"
      >
        <SectionHeading id="companies-title" title="함께 성장하고 싶은 팀"
          eyebrow="MEET YOUR NEXT TEAM" aside="가상 기업" />

        <div className="home-company-grid">
          {jobs.map((job) => (
            <CompanyCard key={job.id} company={{ name: job.company, initial: job.initial,
              description: `${job.category} 분야의 새로운 기회를 만나보세요.`, tone: job.tone }} />
          ))}
        </div>
      </section>
    </div>
  );
}
