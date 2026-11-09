import { useState } from 'react';
import { Button } from '../components/Button';
import { FilterChips } from '../components/FilterChips';
import { SectionHeading } from '../components/SectionHeading';
import { JobCard, type JobCardData } from '../components/JobCard';
import { CompanyCard } from '../components/CompanyCard';

const job: JobCardData = {
  id: 'preview-job', category: '개발', company: '가상 기업', initial: 'A',
  title: '프론트엔드 개발자', detail: '서울 · 신입', tags: ['React'], tone: 'blue',
};
const options = [{ value: 'all', label: '전체' }, { value: 'dev', label: '개발' }];

export function LandingComponentsPreview() {
  const [filter, setFilter] = useState('all');
  const [count, setCount] = useState(0);
  return (
    <div style={{ display: 'grid', gap: '24px' }}>
      <SectionHeading id="landing-parts-title" title="메인 공통 컴포넌트"
        eyebrow="COMPONENT PREVIEW" aside="디자인 검토 전 초안" />
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
        <Button onClick={() => setCount((value) => value + 1)}>기본 버튼</Button>
        <Button variant="outline" onClick={() => setCount(0)}>초기화</Button>
        <Button disabled>비활성 버튼</Button>
      </div>
      <p role="status">공통 버튼 클릭 횟수: {count}</p>
      <FilterChips label="미리보기 직무 선택" options={options} value={filter} onChange={setFilter} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(240px, 100%), 1fr))', gap: '20px', maxWidth: '680px' }}>
        <JobCard job={job} />
        <CompanyCard company={{ name: '가상 기업', initial: 'A', description: '공통 기업 카드 예시입니다.', tone: 'green' }} />
      </div>
    </div>
  );
}
