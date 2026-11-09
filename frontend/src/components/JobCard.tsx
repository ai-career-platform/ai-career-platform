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

export function JobCard({ job }: { job: JobCardData }) {
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
        <ul className="job-tags" aria-label="관련 기술">
          {job.tags.map((tag) => <li key={tag}>{tag}</li>)}
        </ul>
      </div>
    </article>
  );
}
