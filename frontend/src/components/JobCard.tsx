import './JobCard.css';
import './CardTone.css';

export type CardTone = 'blue' | 'purple' | 'green' | 'orange';
export type JobCardData = {
  id: string;
  category: string;
  company: string;
  initial: string;
  title: string;
  detail: string;
  tags: readonly string[];
  tone: CardTone;
};

type JobCardProps = {
  job: JobCardData;
  /** tags 목록의 접근성 이름. 기술이 아닌 값을 넣을 때 바꿉니다. */
  tagsLabel?: string;
};

export function JobCard({ job, tagsLabel = '관련 기술' }: JobCardProps) {
  return (
    <article className="home-job-card">
      <div className={`job-visual job-visual--${job.tone}`}>
        <span className="job-visual-category">{job.category}</span>
        <span className="job-monogram" aria-hidden="true">{job.initial}</span>
        <span className="job-visual-company">{job.company}</span>
      </div>
      <div className="job-card-content">
        <p className="job-company">{job.company}</p>
        <h3>{job.title}</h3>
        <p className="job-detail">{job.detail}</p>
        {job.tags.length > 0 && (
          <ul className="job-tags" aria-label={tagsLabel}>
            {job.tags.map((tag) => <li key={tag}>{tag}</li>)}
          </ul>
        )}
      </div>
    </article>
  );
}
