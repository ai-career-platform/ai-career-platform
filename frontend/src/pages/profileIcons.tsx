import type { ReactNode } from 'react';

/** 프로필 화면 전용 아이콘 (장식용이라 스크린리더에서는 숨김). */
const icon = (paths: ReactNode) => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {paths}
  </svg>
);

export const UserIcon = () => icon(<><circle cx="12" cy="8" r="4" /><path d="M4 20c1-4 4-6 8-6s7 2 8 6" /></>);
export const QuoteIcon = () => icon(<path d="M5 5h14v10H9l-4 4z" />);
export const NoteIcon = () => icon(<><path d="M6 3h9l4 4v14H6z" /><path d="M9 11h7M9 15h7" /></>);
export const PinIcon = () => icon(<><path d="M12 21s7-6 7-11a7 7 0 0 0-14 0c0 5 7 11 7 11z" /><circle cx="12" cy="10" r="2.5" /></>);
export const MailIcon = () => icon(<><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></>);
export const PencilIcon = () => icon(<><path d="M4 20h4L19 9l-4-4L4 16z" /><path d="m13 7 4 4" /></>);
export const BackIcon = () => icon(<path d="M19 12H5m6-6-6 6 6 6" />);
