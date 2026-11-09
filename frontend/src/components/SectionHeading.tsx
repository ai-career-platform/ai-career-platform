import type { ReactNode } from 'react';
import './SectionHeading.css';

type SectionHeadingProps = {
  id: string;
  title: string;
  eyebrow?: string;
  aside?: ReactNode;
};

export function SectionHeading({ id, title, eyebrow, aside }: SectionHeadingProps) {
  return (
    <div className="home-section-heading">
      <div>
        {eyebrow && <p className="home-eyebrow">{eyebrow}</p>}
        <h2 id={id}>{title}</h2>
      </div>
      {aside && <div className="home-demo-label">{aside}</div>}
    </div>
  );
}
