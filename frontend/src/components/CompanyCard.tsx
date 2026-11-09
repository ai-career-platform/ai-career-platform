import type { CardTone } from './JobCard';
import './CompanyCard.css';
import './CardTone.css';

export type CompanyCardData = {
  name: string;
  initial: string;
  description: string;
  tone: CardTone;
};

export function CompanyCard({ company }: { company: CompanyCardData }) {
  return (
    <article className="home-company-card">
      <span className={`company-logo job-visual--${company.tone}`} aria-hidden="true">
        {company.initial}
      </span>
      <h3>{company.name}</h3>
      <p>{company.description}</p>
    </article>
  );
}
